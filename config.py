# config.py

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Определение пути к .env файлу
env_path = Path(__file__).parent / '.env'

# Загрузка переменных окружения из .env файла
if env_path.exists():
    logger.info(f"Загружаю переменные окружения из {env_path}")
    load_dotenv(dotenv_path=env_path)
else:
    logger.info("Файл .env не найден, использую переменные окружения из системы")
    load_dotenv()  # Пытаемся загрузить переменные из системы

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
if not APIFY_API_KEYS:
    raise ValueError("APIFY_API_KEY или APIFY_API_KEYS не заданы в .env файле или переменных окружения")

# Обратная совместимость для старого кода и внешних импортов
APIFY_API_KEY = APIFY_API_KEYS[0]

# Удалять файлы после отправки
DELETE_AFTER_SEND_STR = os.getenv("DELETE_AFTER_SEND", "True")
DELETE_AFTER_SEND = DELETE_AFTER_SEND_STR.lower() in ("true", "1", "t", "yes", "y")

# Вывод информации о конфигурации (без секретных значений)
logger.info(f"Конфигурация загружена: DELETE_AFTER_SEND={DELETE_AFTER_SEND}")
logger.info(f"TELEGRAM_BOT_TOKEN {'задан' if TELEGRAM_BOT_TOKEN else 'не задан'}")
logger.info(f"APIFY_API_KEYS задано: {len(APIFY_API_KEYS)}")
