#!/bin/bash
# Развертывание локальной копии на сервер через rsync (альтернатива git pull + quick-update.sh)
set -e

# Конфигурация
SERVER_USER="user"
SERVER_HOST="your-server"
REPO_PATH="/path/to/repo"

command -v rsync >/dev/null 2>&1 || { echo "rsync не установлен. Установите его для продолжения."; exit 1; }

echo "Копирование файлов на сервер..."
# .env, cookies, логи и скачанные файлы на сервере не трогаем
rsync -avz \
    --exclude 'venv' --exclude '__pycache__' --exclude '.git' \
    --exclude '.env' --exclude 'cookies' --exclude 'logs' --exclude 'instagram_downloads' \
    ./ "$SERVER_USER@$SERVER_HOST:$REPO_PATH/"

echo "Пересборка и перезапуск контейнера на сервере..."
ssh "$SERVER_USER@$SERVER_HOST" "cd $REPO_PATH && docker compose up -d --build"

echo "Развертывание завершено!"
