"""Скачивание медиа напрямую через yt-dlp — без Apify."""

import logging
import os
import shutil
import uuid
from typing import Optional, Tuple

import yt_dlp

logger = logging.getLogger(__name__)

# Лимит Telegram Bot API на отправку файлов
MAX_FILE_SIZE = 50 * 1024 * 1024

VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


class YtDlpError(Exception):
    """Ошибка скачивания через yt-dlp."""


class FileTooLargeError(YtDlpError):
    """Файл больше лимита Telegram."""


class _YtDlpLogger:
    """Перенаправляет вывод yt-dlp в наш логгер (без шума в INFO)."""

    def debug(self, msg: str) -> None:
        logger.debug(msg)

    def info(self, msg: str) -> None:
        logger.debug(msg)

    def warning(self, msg: str) -> None:
        logger.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)  # ошибка всё равно придёт исключением


def _build_options(folder: str, cookies_file: Optional[str]) -> dict:
    has_ffmpeg = shutil.which("ffmpeg") is not None
    options = {
        "outtmpl": os.path.join(folder, f"{uuid.uuid4().hex}.%(ext)s"),
        # С ffmpeg склеиваем лучшее видео + аудио, без него берём готовый mp4
        "format": (
            "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
            if has_ffmpeg else "b[ext=mp4]/b"
        ),
        "merge_output_format": "mp4",
        "max_filesize": MAX_FILE_SIZE,
        "noplaylist": True,
        "playlist_items": "1",  # для каруселей берём первый элемент
        "socket_timeout": 30,
        "retries": 2,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "logger": _YtDlpLogger(),
    }
    if cookies_file:
        if os.path.exists(cookies_file):
            options["cookiefile"] = cookies_file
        else:
            logger.warning("Файл cookies для yt-dlp не найден: %s", cookies_file)
    return options


def _pick_downloaded_path(info: dict) -> Optional[str]:
    if info.get("_type") == "playlist":
        entries = [entry for entry in info.get("entries") or [] if entry]
        if not entries:
            return None
        info = entries[0]
    for item in info.get("requested_downloads") or []:
        path = item.get("filepath")
        if path and os.path.exists(path):
            return path
    return None


def _pick_caption(info: dict) -> Optional[str]:
    if info.get("_type") == "playlist":
        entries = [entry for entry in info.get("entries") or [] if entry]
        caption = info.get("description") or (entries[0].get("description") if entries else None)
    else:
        caption = info.get("description")
    return caption.strip() if caption and caption.strip() else None


def download_with_ytdlp(
    url: str,
    folder: str = "instagram_downloads",
    cookies_file: Optional[str] = None,
) -> Tuple[str, str, Optional[str]]:
    """Скачивает видео. Возвращает (file_path, file_type, caption) или бросает YtDlpError."""
    os.makedirs(folder, exist_ok=True)
    options = _build_options(folder, cookies_file)

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as error:
        raise YtDlpError(str(error)) from error

    if not info:
        raise YtDlpError("yt-dlp не вернул информацию о медиа")

    file_path = _pick_downloaded_path(info)
    if not file_path:
        size = info.get("filesize") or info.get("filesize_approx")
        if size and size > MAX_FILE_SIZE:
            raise FileTooLargeError(f"Файл больше 50 МБ ({size / 1024 / 1024:.1f} МБ)")
        raise YtDlpError("yt-dlp не скачал файл (возможно, он больше 50 МБ)")

    file_type = "video" if file_path.lower().endswith(VIDEO_EXTENSIONS) else "photo"
    return file_path, file_type, _pick_caption(info)
