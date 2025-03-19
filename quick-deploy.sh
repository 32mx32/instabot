#!/bin/bash

# Быстрое развертывание бота (без установки Docker)
set -e

# Проверка наличия токена доступа для приватного репозитория
if [ -z "$GITHUB_TOKEN" ]; then
    echo "Для доступа к приватному репозиторию требуется токен GitHub."
    echo "Создайте Personal Access Token на странице https://github.com/settings/tokens"
    read -p "Введите ваш GitHub Personal Access Token: " GITHUB_TOKEN
    echo
fi

echo "Обновляем репозиторий..."
git pull https://$GITHUB_TOKEN@github.com/32mx32/instabot.git

echo "Перезапускаем контейнер..."
docker-compose down
docker-compose up -d

echo "Бот успешно перезапущен!"
echo "Для просмотра логов выполните: docker-compose logs -f" 