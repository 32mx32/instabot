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

# Установка Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}Docker Compose не установлен. Устанавливаем...${NC}"
    
    # Определяем архитектуру системы
    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then
        ARCH="x86_64"
    elif [ "$ARCH" = "aarch64" ]; then
        ARCH="aarch64"
    else
        echo -e "${RED}Неподдерживаемая архитектура: $ARCH${NC}"
        exit 1
    fi
    
    # Устанавливаем Docker Compose
    COMPOSE_VERSION="v2.24.1"
    COMPOSE_URL="https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}"
    
    echo -e "${YELLOW}Скачиваем Docker Compose...${NC}"
    sudo curl -L "$COMPOSE_URL" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    
    # Проверяем установку
    if docker-compose --version &> /dev/null; then
        echo -e "${GREEN}Docker Compose успешно установлен${NC}"
    else
        echo -e "${RED}Ошибка при установке Docker Compose${NC}"
        exit 1
    fi
fi

# Обновление репозитория, если он уже существует
if [ -d "instabot" ]; then
    echo -e "${YELLOW}Репозиторий найден, обновляем...${NC}"
    cd instabot
    git pull
else
    echo -e "${YELLOW}Клонируем репозиторий...${NC}"
    git clone https://github.com/32mx32/instabot.git instabot
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