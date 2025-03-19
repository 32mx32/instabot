#!/bin/bash

# Скрипт для развертывания бота на сервере
set -e

# Цвета для красивого вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Начинаю развертывание Instagram Telegram бота...${NC}"

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

# Обновление репозитория, если он уже существует
if [ -d "instabot" ]; then
    echo -e "${YELLOW}Репозиторий найден, обновляем...${NC}"
    cd instabot
    git pull https://$GITHUB_TOKEN@github.com/32mx32/instabot.git
else
    echo -e "${YELLOW}Клонируем репозиторий...${NC}"
    # Используем приватный репозиторий с токеном для авторизации
    git clone https://$GITHUB_TOKEN@github.com/32mx32/instabot.git instabot
    cd instabot
fi

# Проверка наличия .env файла и его настройка
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Файл .env не найден. Создаем из примера...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}Пожалуйста, отредактируйте .env с вашими настройками${NC}"
    
    # Спрашиваем пользователя о настройках
    read -p "Введите токен Telegram бота: " TELEGRAM_BOT_TOKEN
    read -p "Введите API ключ Apify: " APIFY_API_KEY
    read -p "Удалять файлы после отправки? (true/false): " DELETE_AFTER_SEND
    
    # Обновляем .env файл
    sed -i "s|TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN|g" .env
    sed -i "s|APIFY_API_KEY=.*|APIFY_API_KEY=$APIFY_API_KEY|g" .env
    sed -i "s|DELETE_AFTER_SEND=.*|DELETE_AFTER_SEND=$DELETE_AFTER_SEND|g" .env
    
    echo -e "${GREEN}Файл .env настроен${NC}"
fi

# Запуск Docker контейнера
echo -e "${YELLOW}Собираем и запускаем Docker контейнер...${NC}"
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Проверка статуса
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Бот успешно запущен!${NC}"
    echo -e "${YELLOW}Просмотр логов: ${NC}docker-compose logs -f"
else
    echo -e "${RED}Произошла ошибка при запуске бота.${NC}"
    exit 1
fi 