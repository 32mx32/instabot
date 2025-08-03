#!/bin/bash

# Конфигурация
SERVER_USER="user"
SERVER_HOST="your-server"
REPO_PATH="/path/to/repo"

# Проверяем наличие необходимых команд
command -v rsync >/dev/null 2>&1 || { echo "rsync не установлен. Установите его для продолжения."; exit 1; }

# Копируем файлы на сервер
echo "Копирование файлов на сервер..."
rsync -avz --exclude 'venv' --exclude '__pycache__' --exclude '.git' ./ $SERVER_USER@$SERVER_HOST:$REPO_PATH/

# Подключаемся к серверу и выполняем команды
echo "Перезапуск контейнеров на сервере..."
ssh $SERVER_USER@$SERVER_HOST "cd $REPO_PATH && \
    docker-compose down && \
    docker-compose pull && \
    docker-compose up -d"

echo "Развертывание завершено!" 