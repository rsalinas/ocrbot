#!/usr/bin/env python3

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
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
TESSERACT_TIMEOUT_SECONDS = int(os.getenv("TESSERACT_TIMEOUT_SECONDS", "60"))
TESSERACT_LANG = os.getenv("TESSERACT_LANG")
EMPTY_OCR_RESPONSE = "\u200b"
MAX_TELEGRAM_BYTES = 4096


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


@dataclass
class AlbumBatch:
    messages: list[Message] = field(default_factory=list)
    job_name: str | None = None


class OcrTelegramBot:
    def __init__(self) -> None:
        self.album_batches: dict[tuple[int, str], AlbumBatch] = {}
        self.album_lock = asyncio.Lock()

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
        # inside the loop we can always overlap: OCR[i] || download[i+1].
        next_dl_task: asyncio.Task = asyncio.create_task(
            self._download_image(messages[0], context)
        )

        try:
            for i, message in enumerate(messages):
                image_path, tmp_dir, file_size = await next_dl_task

                # Start OCR in a thread so the event loop stays free.
                ocr_future = loop.run_in_executor(
                    None, self._run_tesseract, image_path
                )

                # While OCR runs, kick off the next download.
                if i + 1 < num_images:
                    next_dl_task = asyncio.create_task(
                        self._download_image(messages[i + 1], context)
                    )

                try:
                    text = await ocr_future
                finally:
                    tmp_dir.cleanup()

                text = text.strip()
                total_image_bytes += file_size
                total_chars += len(text)
                total_words += len(text.split()) if text else 0

                for chunk in split_message(text or EMPTY_OCR_RESPONSE):
                    await context.bot.send_message(chat_id=chat_id, text=chunk)
        finally:
            stop_event.set()
            await typing_task

        elapsed = time.monotonic() - start_time
        avg_per_image = elapsed / num_images if num_images else 0.0
        stats = (
            f"Estadístiques\n"
            f"Imatges processades: {num_images}\n"
            f"Bytes rebuts (imatges): {total_image_bytes:,}\n"
            f"Caràcters retornats: {total_chars:,}\n"
            f"Paraules retornades: {total_words:,}\n"
            f"Temps total: {elapsed:.1f} s\n"
            f"Temps mitjà per imatge: {avg_per_image:.1f} s"
        )
        LOGGER.info("stats chat_id=%d — %s", chat_id, stats.replace("\n", " | "))
        await context.bot.send_message(chat_id=chat_id, text=stats)

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

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TESSERACT_TIMEOUT_SECONDS,
            check=False,
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
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None:
        return

    await message.reply_text(
        "Envia'm una imatge i extrauré el text amb OCR.\n"
        "Si m'envies diverses imatges agrupades, et respondré en un únic missatge, separant cada resultat amb ----.\n"
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
    application.add_handler(CommandHandler("start", start_handler))
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
