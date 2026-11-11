import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Тестовое окружение до импорта config/main
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST")
os.environ.setdefault("APIFY_API_KEYS", "apify_api_testkey1111,apify_api_testkey2222")
os.environ["LOG_FILE"] = ""
os.environ["DB_PATH"] = ":memory:"
