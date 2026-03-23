#!/usr/bin/env python3

import asyncio
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from openai import AsyncOpenAI
from pathlib import Path

from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger(__name__)

ALBUM_SETTLE_SECONDS = float(os.getenv("ALBUM_SETTLE_SECONDS", "1.2"))
TESSERACT_TIMEOUT_SECONDS = int(os.getenv("TESSERACT_TIMEOUT_SECONDS", "120"))
TESSERACT_LANG = os.getenv("TESSERACT_LANG")
MAX_CONCURRENT_OCR = int(os.getenv("MAX_CONCURRENT_OCR", "2"))
EMPTY_OCR_RESPONSE = "\u200b"
MAX_TELEGRAM_BYTES = 4096
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def split_message(text: str, max_bytes: int = MAX_TELEGRAM_BYTES) -> list[str]:
    """Split text into chunks that each fit within max_bytes UTF-8 bytes.

    Tries to keep paragraphs (double-newline separated) intact.  If a single
    paragraph is itself too large it falls back to splitting on spaces (words).
    """
    if len(text.encode()) <= max_bytes:
        return [text]

    chunks: list[str] = []
    current = ""

    for para in text.split("\n\n"):
        sep = "\n\n" if current else ""
        candidate = current + sep + para

        if len(candidate.encode()) <= max_bytes:
            current = candidate
        else:
            if current:
                chunks.append(current)
                current = ""

            if len(para.encode()) <= max_bytes:
                current = para
            else:
                # Paragraph too long — split by words
                for word in para.split(" "):
                    sep = " " if current else ""
                    candidate = current + sep + word
                    if len(candidate.encode()) <= max_bytes:
                        current = candidate
                    else:
                        if current:
                            chunks.append(current)
                        current = word

    if current:
        chunks.append(current)

    return chunks or [text]


async def _ai_format_text(raw: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY no definida")
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Ets un editor de textos. El text que t'envio ha estat extret "
                    "de diverses imatges escanejades per parts mitjançant OCR. "
                    "Pot contenir errors, espais trencats, paràgrafs tallats o altres "
                    "artefactes d'OCR. Neteja i formata el text mantenint tot el contingut "
                    "original. Retorna únicament el text net, sense explicacions addicionals."
                ),
            },
            {"role": "user", "content": raw},
        ],
    )
    return response.choices[0].message.content or ""


@dataclass
class AlbumBatch:

    messages: list[Message] = field(default_factory=list)
    job_name: str | None = None


class OcrTelegramBot:
    def __init__(self) -> None:
        self.album_batches: dict[tuple[int, str], AlbumBatch] = {}
        self.album_lock = asyncio.Lock()
        self._ocr_semaphore = asyncio.Semaphore(MAX_CONCURRENT_OCR)
        # Per-user accumulated OCR texts (chat_id -> list of extracted strings)
        self._user_buffers: dict[int, list[str]] = {}
        # Per-user default email address
        self._user_emails: dict[int, str] = {}

    async def image_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is None:
            return

        if not self._contains_supported_image(message):
            return

        media_group_id = message.media_group_id
        if media_group_id:
            await self._queue_album_message(message, context)
            return

        await self._process_and_reply(
            chat_id=message.chat_id,
            messages=[message],
            context=context,
        )

    async def _queue_album_message(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        assert message.media_group_id is not None
        batch_key = (message.chat_id, message.media_group_id)
        job_name = f"album:{message.chat_id}:{message.media_group_id}"

        async with self.album_lock:
            batch = self.album_batches.setdefault(batch_key, AlbumBatch())
            batch.messages.append(message)
            batch.job_name = job_name

            current_jobs = context.job_queue.get_jobs_by_name(job_name)
            for job in current_jobs:
                job.schedule_removal()

            context.job_queue.run_once(
                self._flush_album_batch,
                when=ALBUM_SETTLE_SECONDS,
                chat_id=message.chat_id,
                name=job_name,
                data={
                    "chat_id": message.chat_id,
                    "media_group_id": message.media_group_id,
                },
            )

    async def _flush_album_batch(
        self, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        job_data = context.job.data
        batch_key = (job_data["chat_id"], job_data["media_group_id"])

        async with self.album_lock:
            batch = self.album_batches.pop(batch_key, None)

        if batch is None:
            return

        messages = sorted(batch.messages, key=lambda item: item.message_id)
        await self._process_and_reply(
            chat_id=job_data["chat_id"],
            messages=messages,
            context=context,
        )

    async def _process_and_reply(
        self,
        chat_id: int,
        messages: list[Message],
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        start_time = time.monotonic()
        total_image_bytes = 0
        total_chars = 0
        total_words = 0
        num_images = len(messages)
        loop = asyncio.get_running_loop()

        stop_event = asyncio.Event()

        async def typing_loop() -> None:
            while not stop_event.is_set():
                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action=ChatAction.TYPING,
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=4)
                except asyncio.TimeoutError:
                    continue

        typing_task = asyncio.create_task(typing_loop())

        # Pre-download the first image before entering the loop so that
        # inside the loop we can always overlap: download[i+1] || OCR[i].
        next_dl_task: asyncio.Task = asyncio.create_task(
            self._download_image(messages[0], context)
        )

        errors = 0
        try:
            for i, message in enumerate(messages):
                image_path, tmp_dir, file_size = await next_dl_task
                total_image_bytes += file_size

                # Kick off the next download immediately — runs in parallel
                # while we wait for the OCR semaphore and while OCR executes.
                if i + 1 < num_images:
                    next_dl_task = asyncio.create_task(
                        self._download_image(messages[i + 1], context)
                    )

                try:
                    async with self._ocr_semaphore:
                        text = await loop.run_in_executor(
                            None, self._run_tesseract, image_path
                        )
                    text = text.strip()
                    total_chars += len(text)
                    total_words += len(text.split()) if text else 0
                    if text:
                        self._user_buffers.setdefault(chat_id, []).append(text)
                    for chunk in split_message(text or EMPTY_OCR_RESPONSE):
                        await context.bot.send_message(chat_id=chat_id, text=chunk)
                except RuntimeError as exc:
                    errors += 1
                    LOGGER.error("OCR error (chat=%d img=%d): %s", chat_id, i + 1, exc)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"\u26a0\ufe0f Error processant imatge {i + 1}: {exc}",
                    )
                finally:
                    tmp_dir.cleanup()
        finally:
            stop_event.set()
            await typing_task

        elapsed = time.monotonic() - start_time
        avg_per_image = elapsed / num_images if num_images else 0.0
        stats = (
            f"Estadístiques\n"
            f"Imatges processades: {num_images}"
            + (f" ({errors} errors)" if errors else "") + "\n"
            f"Bytes rebuts (imatges): {total_image_bytes:,}\n"
            f"Caràcters retornats: {total_chars:,}\n"
            f"Paraules retornades: {total_words:,}\n"
            f"Temps total: {elapsed:.1f} s\n"
            f"Temps mitjà per imatge: {avg_per_image:.1f} s"
        )
        LOGGER.info("stats chat_id=%d — %s", chat_id, stats.replace("\n", " | "))
        await context.bot.send_message(chat_id=chat_id, text=stats)

    async def email_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is None:
            return

        # Resolve address: explicit arg > saved address
        if context.args and "@" in context.args[0]:
            address = context.args[0]
            if not _EMAIL_RE.match(address):
                await message.reply_text("Adreça de correu no vàlida.")
                return
            self._user_emails[message.chat_id] = address
        else:
            address = self._user_emails.get(message.chat_id)
            if not address:
                await message.reply_text(
                    "No tinc cap adreça desada. Usa:\n/email adreça@exemple.com"
                )
                return

        entries = self._user_buffers.get(message.chat_id)
        if not entries:
            await message.reply_text("No hi ha text acumulat. Envia'm imatges primer.")
            return

        raw_content = "\n\n----\n\n".join(entries)

        await message.reply_text(
            f"⏳ Formatejant {len(entries)} imatge(s) amb IA i enviant a {address}…"
        )

        # AI formatting (fallback to raw if OpenAI fails)
        try:
            formatted = await _ai_format_text(raw_content)
        except Exception as exc:
            LOGGER.error("OpenAI error (chat=%d): %s", message.chat_id, exc)
            formatted = raw_content
            await message.reply_text(
                f"⚠️ Error de la IA, s'envia el text sense formatejar: {exc}"
            )

        # Multipart email: formatted body + raw as attachment
        msg = EmailMessage()
        msg["Subject"] = f"OCR Bot — text extret ({len(entries)} imatge(s))"
        msg["To"] = address
        msg.set_content(formatted)
        msg.add_attachment(
            raw_content.encode(),
            maintype="text",
            subtype="plain",
            filename="ocr_brut.txt",
        )

        try:
            subprocess.run(
                ["sendmail", "-t"],
                input=msg.as_bytes(),
                capture_output=True,
                timeout=30,
                check=True,
            )
        except FileNotFoundError:
            await message.reply_text("⚠️ Error: sendmail no està disponible en aquest servidor.")
            return
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode(errors="replace").strip()
            LOGGER.error("sendmail failed (chat=%d): %s", message.chat_id, stderr)
            await message.reply_text(f"⚠️ Error enviant el correu: {stderr[:200]}")
            return
        except subprocess.TimeoutExpired:
            await message.reply_text("⚠️ Timeout enviant el correu via sendmail.")
            return

        LOGGER.info(
            "email sent chat_id=%d to=%s raw_chars=%d formatted_chars=%d",
            message.chat_id, address, len(raw_content), len(formatted),
        )
        await message.reply_text(
            f"✉️ Enviat a {address} — {len(entries)} imatge(s), "
            f"{len(raw_content):,} caràcters (brut) / {len(formatted):,} (formatejat)."
        )

    async def reset_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is None:
            return
        self._user_buffers.pop(message.chat_id, None)
        await message.reply_text("Buffer buidat. Pots enviar noves imatges.")

    async def get_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is None:
            return
        entries = self._user_buffers.pop(message.chat_id, None)
        if not entries:
            await message.reply_text("No hi ha text acumulat. Envia'm imatges primer.")
            return
        content = "\n\n----\n\n".join(entries)
        buf = io.BytesIO(content.encode())
        buf.name = "ocr.txt"
        await context.bot.send_document(
            chat_id=message.chat_id,
            document=buf,
            filename="ocr.txt",
            caption=f"{len(entries)} imatge(s) · {len(content):,} caràcters · {len(content.split()):,} paraules",
        )

    async def _download_image(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[Path, tempfile.TemporaryDirectory, int]:
        """Download the image to a temp dir. Caller is responsible for cleanup."""
        telegram_file = await self._get_telegram_file(message, context)
        file_size = telegram_file.file_size or 0
        suffix = self._guess_file_suffix(message)
        tmp_dir = tempfile.TemporaryDirectory(prefix="telegram-ocr-")
        image_path = Path(tmp_dir.name) / f"input{suffix}"
        await telegram_file.download_to_drive(custom_path=str(image_path))
        return image_path, tmp_dir, file_size

    async def _get_telegram_file(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ):
        if message.photo:
            return await context.bot.get_file(message.photo[-1].file_id)

        if message.document:
            return await context.bot.get_file(message.document.file_id)

        raise ValueError("Message does not contain a supported image")

    def _guess_file_suffix(self, message: Message) -> str:
        if message.document and message.document.file_name:
            suffix = Path(message.document.file_name).suffix
            if suffix:
                return suffix

        return ".jpg"

    def _run_tesseract(self, image_path: Path) -> str:
        command = ["tesseract", str(image_path), "stdout"]
        if TESSERACT_LANG:
            command.extend(["-l", TESSERACT_LANG])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=TESSERACT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Tesseract timeout (>{TESSERACT_TIMEOUT_SECONDS} s)"
            )

        if result.returncode not in (0, 1):
            stderr = result.stderr.strip() or "unknown error"
            raise RuntimeError(f"Tesseract failed: {stderr}")

        return result.stdout.strip()

    def _contains_supported_image(self, message: Message) -> bool:
        if message.photo:
            return True

        if not message.document:
            return False

        mime_type = message.document.mime_type or ""
        if mime_type.startswith("image/"):
            return True

        extension = Path(message.document.file_name or "").suffix.lower()
        return extension in {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    LOGGER.exception("Unhandled exception", exc_info=context.error)


async def start_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    ocr_bot: "OcrTelegramBot | None" = None,
) -> None:
    message = update.effective_message
    if message is None:
        return

    email_notice = ""
    if context.args:
        candidate = context.args[0]
        if "@" in candidate:
            if _EMAIL_RE.match(candidate) and ocr_bot is not None:
                ocr_bot._user_emails[message.chat_id] = candidate
                email_notice = f"\nAdreça desada: {candidate}"
            else:
                email_notice = "\n⚠️ Adreça de correu no vàlida, no s'ha desat."

    await message.reply_text(
        "Envia'm una imatge i extrauré el text amb OCR.\n"
        "Les imatges agrupades es processen juntes.\n\n"
        "/get — baixa tot el text acumulat com a fitxer .txt (i buida el buffer)\n"
        "/email [addr] — envia el text acumulat per correu\n"
        "/reset — buida el buffer sense descarregar res"
        + email_notice
    )


def build_application(token: str) -> Application:
    if shutil.which("tesseract") is None:
        raise RuntimeError("L'executable 'tesseract' no està disponible en PATH")

    ocr_bot = OcrTelegramBot()
    application = (
        Application.builder()
        .token(token)
        .get_updates_read_timeout(60)
        .get_updates_connect_timeout(30)
        .build()
    )

    image_filter = filters.PHOTO | filters.Document.IMAGE
    application.add_handler(CommandHandler("start", lambda u, c: start_handler(u, c, ocr_bot)))
    application.add_handler(CommandHandler("reset", ocr_bot.reset_handler))
    application.add_handler(CommandHandler("get", ocr_bot.get_handler))
    application.add_handler(CommandHandler("email", ocr_bot.email_handler))
    application.add_handler(MessageHandler(image_filter, ocr_bot.image_handler))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Defineix TELEGRAM_BOT_TOKEN abans d'executar el bot")

    application = build_application(token)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
