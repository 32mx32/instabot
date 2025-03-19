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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

# API ключ Apify
APIFY_API_KEY = os.getenv("APIFY_API_KEY", "YOUR_APIFY_API_KEY")

# Удалять файлы после отправки
DELETE_AFTER_SEND_STR = os.getenv("DELETE_AFTER_SEND", "True")
DELETE_AFTER_SEND = DELETE_AFTER_SEND_STR.lower() in ("true", "1", "t", "yes", "y")

# Вывод информации о конфигурации (без секретных значений)
logger.info(f"Конфигурация загружена: DELETE_AFTER_SEND={DELETE_AFTER_SEND}")
logger.info(f"TELEGRAM_BOT_TOKEN {'задан' if TELEGRAM_BOT_TOKEN else 'не задан'}")
logger.info(f"APIFY_API_KEY {'задан' if APIFY_API_KEY else 'не задан'}") 