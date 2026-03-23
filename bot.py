#!/usr/bin/env python3

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
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
        async def ocr_work() -> str:
            parts: list[str] = []
            for message in messages:
                text = await self._extract_text_from_message(message, context)
                parts.append(text.strip())

            joined = "\n----\n".join(parts).strip()
            return joined or EMPTY_OCR_RESPONSE

        response_text = await self._run_with_typing(
            chat_id=chat_id,
            context=context,
            coro=ocr_work(),
        )
        await context.bot.send_message(chat_id=chat_id, text=response_text)

    async def _run_with_typing(
        self,
        chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        coro,
    ):
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
        try:
            return await coro
        finally:
            stop_event.set()
            await typing_task

    async def _extract_text_from_message(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> str:
        telegram_file = await self._get_telegram_file(message, context)
        suffix = self._guess_file_suffix(message)

        with tempfile.TemporaryDirectory(prefix="telegram-ocr-") as temp_dir:
            image_path = Path(temp_dir) / f"input{suffix}"
            await telegram_file.download_to_drive(custom_path=str(image_path))
            return self._run_tesseract(image_path)

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
    application = Application.builder().token(token).build()

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
