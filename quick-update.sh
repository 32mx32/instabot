#!/bin/bash

# Скрипт для быстрого обновления бота
set -e

# Цвета для красивого вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Начинаю обновление Instagram Telegram бота...${NC}"

# Проверка наличия Docker и Docker Compose
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker не установлен. Устанавливаем...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    echo -e "${GREEN}Docker установлен${NC}"
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}Docker Compose не установлен. Устанавливаем...${NC}"
    sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.1/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo -e "${GREEN}Docker Compose установлен${NC}"
fi

# Проверка наличия токена доступа для приватного репозитория
if [ -z "$GITHUB_TOKEN" ]; then
    echo -e "${YELLOW}Для доступа к приватному репозиторию требуется токен GitHub.${NC}"
    echo -e "${YELLOW}Создайте Personal Access Token на странице https://github.com/settings/tokens${NC}"
    read -p "Введите ваш GitHub Personal Access Token: " GITHUB_TOKEN
    echo
fi

# Обновление репозитория
echo -e "${YELLOW}Обновляем репозиторий...${NC}"
git pull https://$GITHUB_TOKEN@github.com/32mx32/instabot.git

# Перезапуск Docker контейнера
echo -e "${YELLOW}Перезапускаем Docker контейнер...${NC}"
docker-compose down
docker-compose pull
docker-compose up -d

# Проверка статуса
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Бот успешно обновлен!${NC}"
    echo -e "${YELLOW}Просмотр логов: ${NC}docker-compose logs -f"
else
    echo -e "${RED}Произошла ошибка при обновлении бота.${NC}"
    exit 1
fi 