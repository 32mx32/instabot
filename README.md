# 🤖 Instagram Telegram Bot

Telegram-бот для скачивания видео из Instagram, TikTok и YouTube Shorts. Сначала бот пробует бесплатный yt-dlp, при неудаче для Instagram переключается на Apify. Есть автоматические повторы, защита от спама и статистика.

<p align="center">
  <img src="https://img.shields.io/badge/Version-2.4.0-blue.svg" alt="Version">
  <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/Status-Production%20Ready-brightgreen" alt="Status">
</p>

## ✨ Возможности

### 📥 Скачивание контента
- ✅ Instagram Reels, посты, IGTV, share-ссылки (`/reel/`, `/reels/`, `/p/`, `/tv/`, `/share/`)
- ✅ TikTok (включая короткие ссылки `vm.tiktok.com`)
- ✅ YouTube Shorts
- ✅ Ссылку можно вставить в любом месте сообщения
- ✅ Кнопка «🔄 Повторить» для ручной повторной попытки

### ⭐ Избранное
- Кнопка «⭐ В избранное» под каждым видео (повторное нажатие убирает)
- `/saved` — личная коллекция, новые сверху, по 10 на страницу
- `/saved рецепт` — поиск по подписи, автору или платформе
- Видео из коллекции присылается мгновенно, даже если оригинал удалили из Instagram

### 💸 Как бот скачивает
0. **Кэш file_id**: если ролик уже отправлялся, бот пересылает его мгновенно, без скачивания
1. **yt-dlp** — бесплатно и быстро, прямо с вашего сервера
2. **Apify** — резерв, только для Instagram, если yt-dlp не справился

В `/stats` видно, сколько скачиваний прошло бесплатно, а сколько через Apify.

### 🛡️ Защита и надежность
- ⚡ Скачивания идут параллельно: один медленный запрос не блокирует остальных пользователей
- ⏱️ Rate limiting (5 запросов/минуту на пользователя, в том числе для кнопки «Повторить»)
- 🔁 Ротация нескольких Apify API ключей при лимитах и ограничениях
- 📦 Проверка лимита Telegram в 50 МБ до отправки
- 🧹 Файлы удаляются сразу после отправки, место на сервере не расходуется
- 📝 Логи в консоль и в `logs/bot.log` с ротацией (до 4 файлов по 5 МБ)
- 🔐 Токен бота не попадает в логи

## 🚀 Быстрый старт

### Установка локально

1. **Клонируйте репозиторий:**
```bash
git clone https://github.com/32mx32/instabot.git
cd instabot
```

2. **Создайте виртуальное окружение (Python 3.10+):**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

3. **Установите зависимости:**
```bash
pip install -r requirements.txt
```
Для склейки видео и аудио yt-dlp нужен `ffmpeg` (`brew install ffmpeg` / `apt install ffmpeg`). Без него бот тоже работает, но выбирает готовые mp4.

4. **Настройте переменные окружения:**
```bash
cp .env.example .env
nano .env  # или любой другой редактор
```

5. **Запустите бота:**
```bash
python main.py
```

## 🐳 Docker развертывание

### Локально с Docker

```bash
cp .env.example .env   # заполните токены
docker compose up -d --build
docker compose logs -f
```

### На сервере (автоматическая установка)

```bash
curl -O https://raw.githubusercontent.com/32mx32/instabot/main/install.sh
chmod +x install.sh
./install.sh
```

### Обновление на сервере

```bash
./quick-update.sh
```
При каждой пересборке образ подтягивает свежий yt-dlp. Это важно: Instagram и TikTok регулярно меняют свои API.

### Проверка yt-dlp на сервере

Перед тем как полагаться на yt-dlp, проверьте, пускают ли платформы ваш сервер:
```bash
docker compose run --rm instabot python scripts/test_ytdlp.py \
    "https://www.instagram.com/reel/XXXX/" "https://www.tiktok.com/@user/video/123"
```

### Cookies для Instagram (рекомендуется)

Анонимные запросы Instagram часто отклоняет с ошибкой «login required». Тогда yt-dlp не справляется, и каждое скачивание уходит в платный Apify.
1. Заведите **отдельный** аккаунт Instagram. Основной использовать не стоит: есть риск блокировки.
2. Войдите в него в браузере и экспортируйте cookies в формате Netscape, например расширением «Get cookies.txt LOCALLY».
3. Положите файл на сервер в `./cookies/instagram.txt` и добавьте в `.env`:
   ```env
   YTDLP_COOKIES_FILE=/app/cookies/instagram.txt
   ```
4. Перезапустите контейнер: `docker compose up -d`.

## 📖 Использование

### Команды бота

- `/start` — начать работу
- `/help` — подробная справка
- `/saved` — ⭐ избранное, `/saved слово` — поиск по нему
- `/stats` — статистика (если задан `ADMIN_IDS`, то только для администраторов)

### Как скачать контент

Нажмите **Поделиться** → **Копировать ссылку** и отправьте ссылку боту. Поддерживаются:
```
https://www.instagram.com/reel/ABC123/      (а также /reels/, m.instagram.com, /<user>/reel/)
https://www.instagram.com/p/ABC123/
https://www.instagram.com/tv/ABC123/
https://www.instagram.com/share/...
https://www.tiktok.com/@user/video/123...   (а также vm.tiktok.com/...)
https://www.youtube.com/shorts/ABC123
```

**Кнопки под видео:** «💬 Подпись» показывает текст поста, «⭐ В избранное» сохраняет видео в коллекцию.

**Повторная попытка:** если скачивание не удалось, нажмите «🔄 Повторить».

## 🔧 Конфигурация

### Переменные окружения (.env)

| Переменная | Описание | Обязательна | По умолчанию |
|------------|----------|-------------|--------------|
| `TELEGRAM_BOT_TOKEN` | Токен бота от [@BotFather](https://t.me/BotFather) | ✅ Да | — |
| `APIFY_API_KEY` | Один API ключ [Apify](https://console.apify.com/settings/integrations) | ⚠️ Желательно* | — |
| `APIFY_API_KEYS` | Несколько ключей Apify через запятую, с переключением при лимитах | ⚠️ Желательно* | — |
| `USE_YTDLP` | Сначала пробовать бесплатный yt-dlp | ❌ Нет | `true` |
| `YTDLP_COOKIES_FILE` | Путь к cookies (Netscape) для yt-dlp | ❌ Нет | — |
| `MAX_PARALLEL_DOWNLOADS` | Сколько скачиваний идёт одновременно | ❌ Нет | `3` |
| `ADMIN_IDS` | ID администраторов через запятую (доступ к `/stats`) | ❌ Нет | все |
| `DELETE_AFTER_SEND` | Удалять файлы после отправки | ❌ Нет | `true` |
| `LOG_FILE` | Путь к файлу лога (пусто — только консоль) | ❌ Нет | `logs/bot.log` |
| `DB_PATH` | Путь к базе SQLite | ❌ Нет | `data/bot.db` |

`*` Без ключей Apify бот работает только через yt-dlp. Для надёжного скачивания из Instagram резерв через Apify рекомендуется.

Если Apify вернёт ошибку лимита, квоты, оплаты или авторизации (HTTP 401/402/403/429), бот временно отключит этот ключ и попробует следующий.

## 📊 Мониторинг

```bash
docker compose logs -f     # консоль
tail -f logs/bot.log       # файл (на хосте, папка logs/ примонтирована в контейнер)
```

Команда `/stats` показывает количество запросов, успешных скачиваний и ошибок, сколько роликов отправлено из кэша (мгновенно), через yt-dlp (бесплатно) и через Apify (платно), а также число пользователей. Статистика хранится в базе и не сбрасывается при перезапуске.

### База данных и бэкап

Всё состояние бота лежит в одном файле `data/bot.db` (SQLite): кэш file_id, избранное, статистика. Самих видео в базе нет, только их идентификаторы в Telegram, поэтому файл весит килобайты.

Бэкап (можно делать на работающем боте):
```bash
docker compose exec instabot python -c "import sqlite3; sqlite3.connect('data/bot.db').backup(sqlite3.connect('data/backup.db'))"
```

⚠️ Кэш file_id привязан к токену бота. Если сменить токен через `/revoke`, бот получит новый токен, но останется тем же ботом, и кэш продолжит работать. Если же создать **нового** бота, старые file_id не подойдут: бот сам скачает видео заново, а кэш обновится автоматически.

## ⚠️ Ограничения

| Ограничение | Значение |
|-------------|----------|
| Rate limit | 5 запросов/минуту на пользователя |
| Размер файла | до 50 МБ (лимит Telegram Bot API) |
| Автоматических попыток | 2, плюс ручные повторы |

**Не поддерживается:**
- ❌ Instagram Stories
- ❌ Приватные аккаунты
- ❌ Альбомы с несколькими фото/видео (отправляется первый элемент)

## 🛠️ Технический стек

- **Python 3.10+** (Docker-образ: 3.12)
- **python-telegram-bot** — Telegram API
- **yt-dlp** + **ffmpeg** — бесплатное скачивание
- **apify-client** — резервное скачивание Instagram
- **requests**, **python-dotenv**
- **Docker & Docker Compose**

## 📁 Структура проекта

```
instabot/
├── main.py                 # Обработчики Telegram и логика скачивания
├── config.py               # Конфигурация, переменные окружения, логирование
├── links.py                # Распознавание и нормализация ссылок
├── ytdlp_downloader.py     # Скачивание через yt-dlp
├── storage.py              # SQLite: кэш file_id, избранное, статистика
├── scripts/test_ytdlp.py   # Проверка yt-dlp на сервере
├── tests/                  # Тесты (pytest)
├── requirements.txt
├── .env.example
├── Dockerfile / docker-compose.yml / .dockerignore
├── install.sh / quick-update.sh / update.sh
├── CHANGELOG.md
├── data/                   # База бота (создаётся автоматически)
└── instagram_downloads/    # Временные файлы (удаляются после отправки)
```

## 🧪 Тесты

```bash
pip install pytest
pytest tests
```

## 🔄 Обновления

См. [CHANGELOG.md](CHANGELOG.md).

**v2.4.0 (Ноябрь 2026):** ⭐ избранное с поиском (`/saved`), мгновенная повторная отправка по file_id, статистика в базе SQLite.

**v2.3.0 (Ноябрь 2026):** бесплатное скачивание через yt-dlp, TikTok и YouTube Shorts, параллельная обработка, токен бота убран из логов, исправления ошибок.

**v2.2.0 (Май 2026):** ротация нескольких Apify API ключей.

## 🐛 Troubleshooting

### Бот не отвечает
1. Проверьте, что бот запущен: `docker compose ps` или `ps aux | grep python`
2. Проверьте логи: `docker compose logs` или `tail -f logs/bot.log`
3. Проверьте токены в `.env`

### Ошибка "Rate limit exceeded"
- Подождите 1 минуту и попробуйте снова
- Это защита от спама (максимум 5 запросов/минуту)

### Не скачивается контент
1. Проверьте, что ссылка правильная
2. Убедитесь, что аккаунт не приватный
3. Попробуйте кнопку "🔄 Повторить"
4. Проверьте Apify API ключ
5. Запустите `scripts/test_ytdlp.py` (см. выше). Если Instagram отвечает «login required», добавьте cookies

### Apify ошибка "Please wait a few minutes"
- Instagram временно заблокировал IP Apify
- Подождите 5-10 минут и попробуйте снова
- Используйте кнопку "🔄 Повторить"

## 🤝 Вклад в проект

Приветствуются Pull Request'ы! Для больших изменений сначала откройте Issue для обсуждения.

## 📄 Лицензия

MIT License - см. файл [LICENSE](LICENSE)

## 👨‍💻 Автор

Создано с ❤️ для удобного скачивания Instagram контента

---

**⭐ Если проект полезен, поставьте звезду на GitHub!**
