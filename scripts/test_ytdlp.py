"""Проверка, работает ли скачивание через yt-dlp с этого сервера (без Apify и без Telegram).

Запуск на VPS:
    docker compose run --rm instabot python scripts/test_ytdlp.py <ссылка> [<ссылка> ...]

С cookies (если Instagram требует вход):
    docker compose run --rm -e YTDLP_COOKIES_FILE=/app/cookies/instagram.txt instabot \
        python scripts/test_ytdlp.py <ссылка>

Скачанные файлы удаляются сразу после проверки.
"""

import logging
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from links import extract_link  # noqa: E402
from ytdlp_downloader import download_with_ytdlp  # noqa: E402

logging.basicConfig(level=logging.ERROR)


def main() -> int:
    urls = sys.argv[1:]
    if not urls:
        print(__doc__)
        return 2

    cookies = os.getenv("YTDLP_COOKIES_FILE") or None
    print(f"cookies: {cookies or 'нет'}\n")
    ok = 0
    with tempfile.TemporaryDirectory() as folder:
        for raw in urls:
            link = extract_link(raw)
            if not link:
                print(f"❓ не распознана ссылка: {raw}")
                continue
            started = time.time()
            try:
                path, file_type, _caption, author = download_with_ytdlp(link.url, folder, cookies)
                size_mb = os.path.getsize(path) / 1024 / 1024
                print(f"✅ {time.time() - started:5.1f}s {size_mb:6.2f} MB {file_type:5} {link.url}  @{author or '?'}")
                os.remove(path)
                ok += 1
            except Exception as error:
                print(f"❌ {time.time() - started:5.1f}s {link.url}\n   {str(error)[:200]}")

    print(f"\nИтог: {ok}/{len(urls)} успешно")
    return 0 if ok == len(urls) else 1


if __name__ == "__main__":
    sys.exit(main())
