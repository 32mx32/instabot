# config.py

import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv

# Определение пути к .env файлу
env_path = Path(__file__).parent / '.env'

# Загрузка переменных окружения из .env файла
_env_found = env_path.exists()
load_dotenv(dotenv_path=env_path if _env_found else None)


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "t", "yes", "y")


# Настройка логирования (единственное место, где вызывается basicConfig).
# Файл лога ротируется, чтобы не занимать место на диске VPS.
LOG_FILE = os.getenv("LOG_FILE", "logs/bot.log")
_log_handlers = [logging.StreamHandler()]
if LOG_FILE:
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    _log_handlers.append(
        RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    )



class _RedactingFormatter(logging.Formatter):
    """Вырезает токен бота из любых строк лога, включая трейсбеки."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        return text.replace(token, "***TOKEN***") if token else text


_formatter = _RedactingFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
for _handler in _log_handlers:
    _handler.setFormatter(_formatter)

logging.basicConfig(level=logging.INFO, handlers=_log_handlers)
# httpx на уровне INFO пишет URL каждого запроса к Telegram — вместе с токеном бота
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
if _env_found:
    logger.info(f"Переменные окружения загружены из {env_path}")
else:
    logger.info("Файл .env не найден, использую переменные окружения из системы")

# Токен вашего Telegram-бота
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не задан в .env файле или переменных окружения")

# API ключи Apify.
# Поддерживаются оба формата:
# APIFY_API_KEY=apify_api_xxx
# APIFY_API_KEYS=apify_api_xxx,apify_api_yyy
def _parse_apify_api_keys():
    keys = []

    single_key = os.getenv("APIFY_API_KEY")
    if single_key:
        keys.append(single_key.strip())

    keys_list = os.getenv("APIFY_API_KEYS")
    if keys_list:
        normalized_keys = keys_list.replace("\n", ",").replace(";", ",")
        keys.extend(key.strip() for key in normalized_keys.split(","))

    indexed_keys = [
        value.strip()
        for name, value in sorted(os.environ.items())
        if name.startswith("APIFY_API_KEY_") and value.strip()
    ]
    keys.extend(indexed_keys)

    unique_keys = []
    for key in keys:
        if key and key not in unique_keys:
            unique_keys.append(key)

    return unique_keys


APIFY_API_KEYS = _parse_apify_api_keys()

# Скачивание через yt-dlp (без Apify). Apify используется как резерв для Instagram.
USE_YTDLP = _env_bool("USE_YTDLP", "true")
# Необязательный файл cookies (формат Netscape) для yt-dlp — помогает, если Instagram
# требует вход при запросах с IP сервера
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip() or None

if not APIFY_API_KEYS and not USE_YTDLP:
    raise ValueError(
        "Не задан ни один способ скачивания: укажите APIFY_API_KEY/APIFY_API_KEYS или включите USE_YTDLP"
    )

# Обратная совместимость для старого кода и внешних импортов
APIFY_API_KEY = APIFY_API_KEYS[0] if APIFY_API_KEYS else None

# Удалять файлы после отправки (экономия места на сервере)
DELETE_AFTER_SEND = _env_bool("DELETE_AFTER_SEND", "true")

# База SQLite: кэш file_id, избранное, статистика (файлы медиа в ней не хранятся)
DB_PATH = os.getenv("DB_PATH", "data/bot.db")

# Сколько скачиваний может идти одновременно
MAX_PARALLEL_DOWNLOADS = max(1, int(os.getenv("MAX_PARALLEL_DOWNLOADS", "3")))

# ID администраторов (через запятую) — им доступна команда /stats
ADMIN_IDS = {
    int(value) for value in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if value.isdigit()
}

# Вывод информации о конфигурации (без секретных значений)
logger.info(f"Конфигурация загружена: DELETE_AFTER_SEND={DELETE_AFTER_SEND}, USE_YTDLP={USE_YTDLP}")
logger.info(f"TELEGRAM_BOT_TOKEN {'задан' if TELEGRAM_BOT_TOKEN else 'не задан'}")
logger.info(f"APIFY_API_KEYS задано: {len(APIFY_API_KEYS)}")
if YTDLP_COOKIES_FILE:
    logger.info(f"Cookies для yt-dlp: {YTDLP_COOKIES_FILE}")
