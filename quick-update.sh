#!/bin/bash

# Быстрое развертывание бота (без установки Docker)
set -e

echo "Обновляем репозиторий..."
git pull

echo "Перезапускаем контейнер..."
docker-compose down
docker-compose up -d

echo "Бот успешно перезапущен!"
echo "Для просмотра логов выполните: docker-compose logs -f" 