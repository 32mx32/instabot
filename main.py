import asyncio
import html
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from apify_client import ApifyClient
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    ADMIN_IDS,
    APIFY_API_KEYS,
    DELETE_AFTER_SEND,
    MAX_PARALLEL_DOWNLOADS,
    TELEGRAM_BOT_TOKEN,
    USE_YTDLP,
    YTDLP_COOKIES_FILE,
)
from links import MediaLink, extract_link, is_instagram_stories, link_from_resolved_url
from ytdlp_downloader import FileTooLargeError, download_with_ytdlp

# Версия бота
BOT_VERSION = "2.3.0"
RELEASE_DATE = "Ноябрь 2026"

# Логирование настраивается в config.py
logger = logging.getLogger(__name__)

DOWNLOAD_FOLDER = "instagram_downloads"
MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024

# Кэши в памяти
COMMENTS_CACHE: Dict[str, str] = {}
RETRY_LINK_CACHE: Dict[str, MediaLink] = {}
MAX_CACHE_SIZE = 1000

# Rate limiting
user_requests: Dict[int, List[datetime]] = defaultdict(list)
MAX_REQUESTS_PER_MINUTE = 5

# Статистика
stats: Dict[str, Any] = {
    'total_downloads': 0,
    'successful_downloads': 0,
    'failed_downloads': 0,
    'ytdlp_downloads': 0,
    'apify_downloads': 0,
    'users': set(),
}

# Кэш скачанных файлов (URL -> (file_path, timestamp)).
# Используется только при DELETE_AFTER_SEND=false — по умолчанию файлы удаляются сразу после отправки.
file_cache: Dict[str, Tuple[str, float]] = {}
CACHE_TTL = 3600  # 1 час
MAX_FILE_CACHE_SIZE = 50

# Префиксы для callback данных
SHOW_COMMENT_PREFIX = "show_comment:"
RETRY_DOWNLOAD_PREFIX = "retry:"

# Попытки скачивания на один запрос пользователя
DOWNLOAD_ATTEMPTS = 2
# Максимальное время работы одного запуска актора Apify
APIFY_ACTOR_TIMEOUT_SECS = 120

# Ротация Apify API ключей
APIFY_KEY_COOLDOWN_SECONDS = 15 * 60
APIFY_ROTATION_STATUS_CODES = {401, 402, 403, 429}
APIFY_ROTATION_ERROR_MARKERS = (
    "rate limit", "too many requests",
    "usage limit", "monthly usage", "hard limit", "limit exceeded",
    "not enough usage", "insufficient", "payment required",
    "authentication token", "api token",
)


# ---------------------------------------------------------------------------
# Apify: ротация ключей
# ---------------------------------------------------------------------------

def mask_apify_key(api_key: str) -> str:
    """Маскирует API ключ для безопасного логирования."""
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:10]}...{api_key[-4:]}"


def is_apify_rotation_error(error: Exception) -> bool:
    """Определяет ошибки, при которых стоит переключиться на другой Apify ключ."""
    if getattr(error, "status_code", None) in APIFY_ROTATION_STATUS_CODES:
        return True
    error_msg = str(error).lower()
    return any(marker in error_msg for marker in APIFY_ROTATION_ERROR_MARKERS)


class ApifyKeyManager:
    """Управляет доступными Apify ключами и временно отключает проблемные.

    Методы вызываются из рабочих потоков, поэтому состояние защищено блокировкой.
    """

    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.current_index = 0
        self.disabled_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get_available_keys(self) -> List[str]:
        if not self.api_keys:
            return []
        with self._lock:
            now = time.time()
            available = {
                key for key in self.api_keys
                if self.disabled_until.get(key, 0) <= now
            }

            if not available:
                logger.warning("Все Apify ключи временно отключены, пробуем полный список повторно")
                self.disabled_until.clear()
                available = set(self.api_keys)

            total_keys = len(self.api_keys)
            return [
                self.api_keys[(self.current_index + offset) % total_keys]
                for offset in range(total_keys)
                if self.api_keys[(self.current_index + offset) % total_keys] in available
            ]

    def mark_success(self, api_key: str) -> None:
        with self._lock:
            if api_key in self.api_keys:
                self.current_index = self.api_keys.index(api_key)
            self.disabled_until.pop(api_key, None)

    def mark_limited(self, api_key: str, error: Exception) -> None:
        if len(self.api_keys) == 1:
            return

        with self._lock:
            self.disabled_until[api_key] = time.time() + APIFY_KEY_COOLDOWN_SECONDS
            self.current_index = (self.api_keys.index(api_key) + 1) % len(self.api_keys)
        logger.warning(
            "Apify ключ %s временно отключен на %s секунд: %s",
            mask_apify_key(api_key),
            APIFY_KEY_COOLDOWN_SECONDS,
            error,
        )


apify_key_manager = ApifyKeyManager(APIFY_API_KEYS)


# ---------------------------------------------------------------------------
# Кэши и rate limit
# ---------------------------------------------------------------------------

def trim_cache(cache: Dict[str, Any], name: str) -> None:
    """Удаляет половину самых старых записей, если кэш превысил лимит."""
    if len(cache) > MAX_CACHE_SIZE:
        items_to_remove = len(cache) - MAX_CACHE_SIZE // 2
        for key in list(cache.keys())[:items_to_remove]:
            del cache[key]
        logger.info(f"Очищен кэш {name}: удалено {items_to_remove} записей")


def _remove_file(file_path: str) -> None:
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Файл {file_path} удален.")
    except OSError as e:
        logger.warning(f"Не удалось удалить файл {file_path}: {e}")


def clean_file_cache() -> None:
    """Удаляет устаревшие файлы из кэша и самые старые при превышении лимита."""
    current_time = time.time()
    for url in [u for u, (_, ts) in file_cache.items() if current_time - ts > CACHE_TTL]:
        _remove_file(file_cache.pop(url)[0])

    if len(file_cache) > MAX_FILE_CACHE_SIZE:
        sorted_cache = sorted(file_cache.items(), key=lambda item: item[1][1])
        for url, (file_path, _) in sorted_cache[:len(file_cache) - MAX_FILE_CACHE_SIZE]:
            _remove_file(file_path)
            del file_cache[url]


def get_cached_file(url: str) -> Optional[str]:
    """Возвращает файл из кэша, если он существует и не устарел."""
    if url not in file_cache:
        return None
    file_path, timestamp = file_cache[url]
    if time.time() - timestamp > CACHE_TTL or not os.path.exists(file_path):
        _remove_file(file_path)
        del file_cache[url]
        return None
    logger.info(f"Файл найден в кэше: {url}")
    return file_path


def add_to_file_cache(url: str, file_path: str) -> None:
    file_cache[url] = (file_path, time.time())
    if len(file_cache) > MAX_FILE_CACHE_SIZE:
        clean_file_cache()


def check_rate_limit(user_id: int) -> bool:
    """Проверяет rate limit для пользователя."""
    now = datetime.now()
    recent = [t for t in user_requests[user_id] if now - t < timedelta(minutes=1)]
    if len(recent) >= MAX_REQUESTS_PER_MINUTE:
        user_requests[user_id] = recent
        return False
    recent.append(now)
    user_requests[user_id] = recent
    return True


# ---------------------------------------------------------------------------
# Скачивание (синхронный код — выполняется в отдельном потоке)
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    file_path: Optional[str] = None
    file_type: Optional[str] = None
    caption: Optional[str] = None
    error: Optional[str] = None  # "too_large" | None
    source: Optional[str] = None  # "ytdlp" | "apify" | "cache"


def download_file(url: str, folder: str = DOWNLOAD_FOLDER, timeout: int = 30) -> Tuple[Optional[str], Optional[str]]:
    """Скачивает файл по прямой ссылке (используется для результатов Apify)."""
    try:
        os.makedirs(folder, exist_ok=True)
        with requests.get(url, stream=True, timeout=timeout) as response:
            if response.status_code != 200:
                logger.error(f"Ошибка при скачивании файла. Код статуса: {response.status_code}")
                return None, None

            content_length = int(response.headers.get('Content-Length') or 0)
            if content_length > MAX_TELEGRAM_FILE_SIZE:
                raise FileTooLargeError(f"Файл больше 50 МБ ({content_length / 1024 / 1024:.1f} МБ)")

            content_type = response.headers.get('Content-Type', '').lower()
            url_path = url.split('?')[0].lower()
            if 'image' in content_type or url_path.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                file_type, extension = "photo", ".jpg"
            else:
                # Для Reels видео — самый вероятный вариант
                file_type, extension = "video", ".mp4"

            # Уникальное имя: параллельные загрузки не перезаписывают друг друга
            file_path = os.path.join(folder, f"{uuid.uuid4().hex}{extension}")
            written = 0
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        written += len(chunk)
                        if written > MAX_TELEGRAM_FILE_SIZE:
                            f.close()
                            _remove_file(file_path)
                            raise FileTooLargeError("Файл больше 50 МБ")
                        f.write(chunk)

        logger.info(f"Файл успешно скачан: {file_path}")
        return file_path, file_type
    except FileTooLargeError:
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка HTTP запроса при скачивании файла: {e}")
        return None, None
    except OSError as e:
        logger.error(f"Ошибка записи файла: {e}")
        return None, None


def retry_apify_request(func, max_retries: int = 2, delay: int = 2):
    """Вызывает Apify с переключением API ключей при лимитах."""
    last_error = None

    for api_key in apify_key_manager.get_available_keys():
        client = ApifyClient(api_key)
        current_delay = delay

        for attempt in range(max_retries):
            try:
                result = func(client)
                apify_key_manager.mark_success(api_key)
                return result, client
            except Exception as e:
                last_error = e

                if is_apify_rotation_error(e):
                    apify_key_manager.mark_limited(api_key, e)
                    logger.warning("Переключаем Apify ключ после ошибки на %s: %s", mask_apify_key(api_key), e)
                    break

                if attempt == max_retries - 1:
                    logger.warning("Все попытки для Apify ключа %s исчерпаны: %s", mask_apify_key(api_key), e)
                    break

                logger.warning(
                    "Попытка %s/%s для Apify ключа %s не удалась: %s. Повторяем через %s секунд...",
                    attempt + 1, max_retries, mask_apify_key(api_key), e, current_delay,
                )
                time.sleep(current_delay)
                current_delay *= 2

    if last_error:
        raise last_error
    raise RuntimeError("Нет доступных Apify API ключей")


def _extract_media_url(actor: str, item: Dict[str, Any]) -> Optional[str]:
    if actor == "apify/instagram-reel-scraper":
        for media_item in item.get("media") or []:
            if isinstance(media_item, dict) and (media_item.get("videoUrl") or media_item.get("url")):
                return media_item.get("videoUrl") or media_item.get("url")
    return (
        item.get("videoUrl") or item.get("mediaUrl") or item.get("downloadUrl")
        or item.get("video_url") or item.get("url")
    )


# (актор, функция построения входных данных)
APIFY_ACTORS = (
    ("easyapi/instagram-reels-downloader", lambda url: {"reelUrls": [url]}),
    ("apify/instagram-reel-scraper", lambda url: {"usernames": [], "urls": [url], "resultsLimit": 1}),
    ("presetshubham/instagram-reel-downloader", lambda url: {"reelLinks": [url]}),
)


def download_instagram_reel(post_url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Скачивает Instagram медиа через акторы Apify (по очереди до первого успеха)."""
    caption = None
    for actor, build_input in APIFY_ACTORS:
        try:
            logger.info(f"Apify: пробуем {actor} для {post_url}")

            def run_actor(client, actor=actor, build_input=build_input):
                return client.actor(actor).call(
                    run_input=build_input(post_url),
                    timeout_secs=APIFY_ACTOR_TIMEOUT_SECS,
                )

            run, client = retry_apify_request(run_actor)
            if not run:
                continue
            if run.get("status") != "SUCCEEDED":
                logger.warning(f"Apify: {actor} завершился со статусом {run.get('status')}")

            dataset_items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            logger.debug(f"Apify ({actor}) данные: {dataset_items}")
            if not dataset_items:
                continue

            item = dataset_items[0]
            caption = caption or item.get("caption") or item.get("description") or item.get("text")
            media_url = _extract_media_url(actor, item)
            logger.info(f"Apify ({actor}) media URL найден: {bool(media_url)}")

            if media_url:
                file_path, file_type = download_file(media_url)
                if file_path:
                    return file_path, file_type, caption
        except FileTooLargeError:
            raise
        except Exception as e:
            logger.warning(f"Ошибка при скачивании через {actor}: {e}")

    logger.error("Все методы скачивания через Apify не удались.")
    return None, None, None


def resolve_share_link(link: MediaLink) -> MediaLink:
    """Раскрывает instagram.com/share/... в каноническую ссылку на пост или Reels."""
    try:
        with requests.get(
            link.url, allow_redirects=True, timeout=15, stream=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as response:
            final_url = response.url
    except requests.RequestException as e:
        logger.warning(f"Не удалось раскрыть share-ссылку {link.url}: {e}")
        return link

    resolved = link_from_resolved_url(final_url)
    if resolved:
        logger.info(f"Share-ссылка раскрыта: {link.url} -> {resolved.url}")
        return resolved
    logger.warning(f"Share-ссылка не раскрылась в пост: {final_url}")
    return link


def fetch_media_sync(link: MediaLink) -> DownloadResult:
    """Скачивает медиа: сначала yt-dlp (бесплатно), затем Apify (только Instagram)."""
    if link.needs_resolve:
        link = resolve_share_link(link)

    if USE_YTDLP:
        try:
            file_path, file_type, caption = download_with_ytdlp(link.url, DOWNLOAD_FOLDER, YTDLP_COOKIES_FILE)
            logger.info(f"yt-dlp: скачано {link.url}")
            return DownloadResult(file_path, file_type, caption, source="ytdlp")
        except FileTooLargeError as e:
            logger.warning(f"yt-dlp: {e}")
            return DownloadResult(error="too_large")
        except Exception as e:
            logger.warning(f"yt-dlp не справился с {link.url}: {e}")

    if link.platform == "instagram" and APIFY_API_KEYS:
        try:
            file_path, file_type, caption = download_instagram_reel(link.url)
        except FileTooLargeError:
            return DownloadResult(error="too_large")
        if file_path:
            return DownloadResult(file_path, file_type, caption, source="apify")

    return DownloadResult()


# ---------------------------------------------------------------------------
# Асинхронная обвязка
# ---------------------------------------------------------------------------

_download_semaphore: Optional[asyncio.Semaphore] = None


def get_download_semaphore() -> asyncio.Semaphore:
    # Создаём лениво внутри работающего event loop
    global _download_semaphore
    if _download_semaphore is None:
        _download_semaphore = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)
    return _download_semaphore


async def safe_edit(message: Optional[Message], text: str, **kwargs) -> None:
    if not message:
        return
    try:
        await message.edit_text(text, **kwargs)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning(f"Не удалось обновить сообщение: {e}")
    except Exception as e:
        logger.warning(f"Не удалось обновить сообщение: {e}")


async def safe_delete(message: Optional[Message]) -> None:
    if not message:
        return
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение: {e}")


async def fetch_media(link: MediaLink, status_message: Optional[Message]) -> DownloadResult:
    """Скачивает медиа с повторными попытками, не блокируя event loop."""
    cached_file = get_cached_file(link.url)
    if cached_file:
        file_type = 'video' if cached_file.lower().endswith(('.mp4', '.mov', '.webm')) else 'photo'
        return DownloadResult(cached_file, file_type, source="cache")

    result = DownloadResult()
    semaphore = get_download_semaphore()
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        logger.info(f"Попытка скачивания {attempt}/{DOWNLOAD_ATTEMPTS}: {link.url}")
        if semaphore.locked():
            await safe_edit(status_message, "🕐 Ожидаю очереди на скачивание...")
        async with semaphore:
            await safe_edit(status_message, f"⏳ Скачиваю... (попытка {attempt}/{DOWNLOAD_ATTEMPTS})")
            result = await asyncio.to_thread(fetch_media_sync, link)

        if result.file_path or result.error:
            return result
        if attempt < DOWNLOAD_ATTEMPTS:
            await asyncio.sleep(3)
    return result


def _comment_keyboard(caption_text: Optional[str]) -> Optional[InlineKeyboardMarkup]:
    if not caption_text:
        return None
    trim_cache(COMMENTS_CACHE, "комментариев")
    comment_id = uuid.uuid4().hex
    COMMENTS_CACHE[comment_id] = caption_text
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Показать комментарий", callback_data=f"{SHOW_COMMENT_PREFIX}{comment_id}")]
    ])


def _retry_keyboard(link: MediaLink) -> InlineKeyboardMarkup:
    trim_cache(RETRY_LINK_CACHE, "ссылок для повтора")
    retry_id = uuid.uuid4().hex[:12]
    RETRY_LINK_CACHE[retry_id] = link
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Повторить", callback_data=f"{RETRY_DOWNLOAD_PREFIX}{retry_id}")]
    ])


async def send_media(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    thread_id: Optional[int],
    link: MediaLink,
    result: DownloadResult,
) -> Optional[str]:
    """Отправляет файл в чат. Возвращает текст ошибки или None при успехе."""
    kwargs: Dict[str, Any] = {
        "chat_id": chat_id,
        "caption": f'<a href="{html.escape(link.url, quote=True)}">{link.label}</a>',
        "parse_mode": ParseMode.HTML,
        "reply_markup": _comment_keyboard(result.caption),
        "read_timeout": 120,
        "write_timeout": 120,
    }
    if thread_id is not None:
        kwargs["message_thread_id"] = thread_id

    try:
        with open(result.file_path, "rb") as media_file:
            if result.file_type == "photo":
                await context.bot.send_photo(photo=media_file, **kwargs)
            else:
                await context.bot.send_video(video=media_file, supports_streaming=True, **kwargs)
        return None
    except FileNotFoundError:
        logger.error(f"Файл не найден при отправке: {result.file_path}")
        return "⚠️ Файл не найден. Попробуйте ещё раз."
    except TimedOut as e:
        size_mb = os.path.getsize(result.file_path) / (1024 * 1024) if os.path.exists(result.file_path) else 0
        logger.error(f"Таймаут при отправке файла ({size_mb:.1f} MB): {e}")
        return (
            "⏱️ <b>Превышено время отправки файла</b>\n\n"
            f"Размер файла: {size_mb:.1f} MB\n"
            "Возможно, медленное соединение или временные проблемы Telegram API."
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке файла: {e}")
        return f"⚠️ Ошибка при отправке файла: {html.escape(str(e))}"


async def report_failure(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    thread_id: Optional[int],
    status_message: Optional[Message],
    link: MediaLink,
    text: str,
    allow_retry: bool = True,
) -> None:
    """Показывает ошибку (по возможности — заменяя статусное сообщение) с кнопкой повтора."""
    keyboard = _retry_keyboard(link) if allow_retry else None
    if status_message:
        try:
            await status_message.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True
            )
            return
        except Exception as e:
            logger.warning(f"Не удалось обновить статус ошибкой: {e}")

    kwargs: Dict[str, Any] = {}
    if thread_id is not None:
        kwargs["message_thread_id"] = thread_id
    await context.bot.send_message(
        chat_id=chat_id, text=text, parse_mode=ParseMode.HTML,
        reply_markup=keyboard, disable_web_page_preview=True, **kwargs,
    )


def _download_failed_text(link: MediaLink) -> str:
    return (
        f"⚠️ Не удалось скачать {html.escape(link.label)} после {DOWNLOAD_ATTEMPTS} попыток.\n"
        f"Ссылка: {html.escape(link.url)}\n\n"
        "Возможные причины:\n"
        "• Пост недоступен или был удален\n"
        "• Аккаунт является приватным\n"
        "• Временные ограничения со стороны платформы\n\n"
        "Вы можете попробовать снова, нажав кнопку ниже."
    )


async def process_link(
    context: ContextTypes.DEFAULT_TYPE,
    link: MediaLink,
    chat_id: int,
    thread_id: Optional[int],
    status_message: Optional[Message],
) -> bool:
    """Полный цикл: скачать → отправить → убрать за собой. Возвращает True при успехе."""
    stats['total_downloads'] += 1
    result = await fetch_media(link, status_message)

    if not result.file_path:
        stats['failed_downloads'] += 1
        if result.error == "too_large":
            await report_failure(
                context, chat_id, thread_id, status_message, link,
                "📦 Файл больше 50 МБ — Telegram не позволяет ботам отправлять такие файлы.",
                allow_retry=False,
            )
        else:
            await report_failure(context, chat_id, thread_id, status_message, link, _download_failed_text(link))
        return False

    await safe_edit(status_message, "📤 Отправляю...")
    try:
        send_error = await send_media(context, chat_id, thread_id, link, result)
    finally:
        if DELETE_AFTER_SEND:
            _remove_file(result.file_path)
        else:
            add_to_file_cache(link.url, result.file_path)

    if send_error:
        stats['failed_downloads'] += 1
        await report_failure(context, chat_id, thread_id, status_message, link, send_error)
        return False

    stats['successful_downloads'] += 1
    if result.source in ("ytdlp", "apify"):
        stats[f"{result.source}_downloads"] += 1
    await safe_delete(status_message)
    return True


def _thread_id(message: Message) -> Optional[int]:
    return message.message_thread_id if message.is_topic_message else None


# ---------------------------------------------------------------------------
# Обработчики Telegram
# ---------------------------------------------------------------------------

SUPPORTED_LINKS_TEXT = (
    "• instagram.com/reel/… и /reels/… (Reels)\n"
    "• instagram.com/p/… (посты), /tv/… (IGTV), /share/…\n"
    "• tiktok.com/… (TikTok)\n"
    "• youtube.com/shorts/… (YouTube Shorts)"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 Привет! Я скачиваю видео из Instagram, TikTok и YouTube Shorts.\n\n"
        "📌 <b>Как пользоваться:</b>\n"
        "Просто отправьте мне ссылку — можно прямо в тексте сообщения.\n\n"
        "🔧 <b>Команды:</b>\n"
        "/start — начать работу\n"
        "/help — справка\n\n"
        f"ℹ️ Версия: <b>{BOT_VERSION}</b> ({RELEASE_DATE})"
    )
    await update.effective_message.reply_text(welcome_text, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>Подробная справка</b>\n\n"
        f"<b>Поддерживаемые ссылки:</b>\n{SUPPORTED_LINKS_TEXT}\n\n"
        "<b>Как скачать:</b>\n"
        "1. Нажмите «Поделиться» → «Копировать ссылку»\n"
        "2. Отправьте ссылку мне\n\n"
        "<b>Подпись к посту:</b>\n"
        "Если у поста есть подпись, появится кнопка «Показать комментарий».\n\n"
        "<b>Ограничения:</b>\n"
        f"• Максимум {MAX_REQUESTS_PER_MINUTE} запросов в минуту\n"
        "• Файлы до 50 МБ (лимит Telegram)\n"
        "• Приватные аккаунты и Stories недоступны\n\n"
        f"ℹ️ <b>Версия бота:</b> {BOT_VERSION} ({RELEASE_DATE})\n\n"
        "❓ Если скачивание не удалось — нажмите «🔄 Повторить»."
    )
    await update.effective_message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if ADMIN_IDS and (not user or user.id not in ADMIN_IDS):
        return

    total = stats['total_downloads']
    success_rate = (stats['successful_downloads'] / total * 100) if total else 0
    stats_text = (
        "📊 <b>Статистика бота</b> (с момента запуска)\n\n"
        f"📥 Всего запросов: {total}\n"
        f"✅ Успешно: {stats['successful_downloads']}\n"
        f"❌ Ошибок: {stats['failed_downloads']}\n"
        f"🆓 Через yt-dlp: {stats['ytdlp_downloads']}\n"
        f"💳 Через Apify: {stats['apify_downloads']}\n"
        f"👥 Уникальных пользователей: {len(stats['users'])}\n\n"
        f"🎯 Процент успеха: {success_rate:.1f}%"
    )
    await update.effective_message.reply_text(stats_text, parse_mode=ParseMode.HTML)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback_data = query.data or ""
    logger.info(f"Получен callback: {callback_data}")

    if callback_data.startswith(SHOW_COMMENT_PREFIX):
        comment_text = COMMENTS_CACHE.get(callback_data[len(SHOW_COMMENT_PREFIX):])
        if comment_text is None:
            await query.answer("Комментарий больше недоступен (бот перезапускался).", show_alert=True)
            return
        # Лимит текста alert в Telegram — 200 символов
        shown = comment_text if len(comment_text) <= 195 else comment_text[:195] + "..."
        await query.answer(f"💬 {shown}", show_alert=True)
        return

    if callback_data.startswith(RETRY_DOWNLOAD_PREFIX):
        link = RETRY_LINK_CACHE.get(callback_data[len(RETRY_DOWNLOAD_PREFIX):])
        if link is None:
            await query.answer("⚠️ Ссылка устарела. Отправьте её снова.", show_alert=True)
            return

        user = query.from_user
        if user and not check_rate_limit(user.id):
            await query.answer(
                f"⏰ Слишком много запросов. Максимум {MAX_REQUESTS_PER_MINUTE} в минуту.", show_alert=True
            )
            return

        await query.answer()
        logger.info(f"Повторная попытка скачивания: {link.url}")
        status_message = query.message
        if not isinstance(status_message, Message):
            return
        await safe_edit(status_message, "⏳ Скачиваю...", reply_markup=None)
        await process_link(context, link, status_message.chat_id, _thread_id(status_message), status_message)
        return

    await query.answer()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return
    user = update.effective_user
    text = message.text.strip()

    if is_instagram_stories(text):
        await message.reply_text(
            "⚠️ Instagram Stories скачать нельзя.\n"
            "Бот поддерживает Reels, посты, TikTok и YouTube Shorts."
        )
        return

    link = extract_link(text)
    if not link:
        if any(domain in text.lower() for domain in ("instagram.com", "tiktok.com", "youtube.com")):
            await message.reply_text(
                f"⚠️ Не распознал ссылку. Поддерживаются:\n{SUPPORTED_LINKS_TEXT}"
            )
        else:
            logger.debug("Сообщение без поддерживаемой ссылки проигнорировано")
        return

    if user:
        stats['users'].add(user.id)
        if not check_rate_limit(user.id):
            await message.reply_text(
                "⏰ Слишком много запросов!\n\n"
                f"Максимум {MAX_REQUESTS_PER_MINUTE} запросов в минуту. Попробуйте чуть позже."
            )
            logger.warning(f"Rate limit exceeded for user {user.id}")
            return

    logger.info(f"Получена ссылка ({link.platform}/{link.kind}): {link.url}")
    try:
        status_message = await message.reply_text("⏳ Скачиваю...")
    except Exception as e:
        logger.error(f"Не удалось отправить статусное сообщение: {e}")
        status_message = None

    await process_link(context, link, message.chat_id, _thread_id(message), status_message)

    # Удаляем исходное сообщение со ссылкой — результат (или ошибка со ссылкой) уже в чате
    await safe_delete(message)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Необработанная ошибка при обработке апдейта", exc_info=context.error)


def build_application() -> Application:
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)  # пользователи не ждут друг друга
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    # Только новые сообщения: на отредактированных update.message == None
    app.add_handler(MessageHandler(
        filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND, handle_message
    ))
    app.add_error_handler(error_handler)
    return app


if __name__ == "__main__":
    logger.info(f"Запуск бота v{BOT_VERSION}...")
    try:
        build_application().run_polling()
    except Exception:
        # Трейсбек пишем только через логгер — в нём токен вырезается
        logger.exception("Ошибка при запуске бота")
        raise SystemExit(1)
