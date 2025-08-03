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

# Проверка наличия Docker Compose
if ! docker compose version &> /dev/null; then
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
    if docker compose version &> /dev/null; then
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
    
    # Спрашиваем пользователя о настройках с валидацией
    while true; do
        read -p "Введите токен Telegram бота: " TELEGRAM_BOT_TOKEN
        if [[ $TELEGRAM_BOT_TOKEN =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
            break
        else
            echo -e "${RED}Неверный формат токена. Токен должен быть в формате: 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11${NC}"
        fi
    done
    
    while true; do
        read -p "Введите API ключ Apify: " APIFY_API_KEY
        if [[ $APIFY_API_KEY =~ ^apify_api_[A-Za-z0-9]+$ ]]; then
            break
        else
            echo -e "${RED}Неверный формат API ключа. Ключ должен начинаться с 'apify_api_'${NC}"
        fi
    done
    
    read -p "Удалять файлы после отправки? (true/false) [true]: " DELETE_AFTER_SEND
    DELETE_AFTER_SEND=${DELETE_AFTER_SEND:-true}
    
    # Обновляем .env файл
    sed -i "s|TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN|g" .env
    sed -i "s|APIFY_API_KEY=.*|APIFY_API_KEY=$APIFY_API_KEY|g" .env
    sed -i "s|DELETE_AFTER_SEND=.*|DELETE_AFTER_SEND=$DELETE_AFTER_SEND|g" .env
    
    echo -e "${GREEN}Файл .env настроен и проверен${NC}"
else
    echo -e "${GREEN}Файл .env найден, проверяем конфигурацию...${NC}"
    
    # Проверяем, что токены не являются placeholder'ами
    if grep -q "YOUR_TELEGRAM_BOT_TOKEN" .env; then
        echo -e "${RED}Обнаружены placeholder токены в .env файле. Пожалуйста, настройте реальные токены.${NC}"
        exit 1
    fi
    
    if grep -q "YOUR_APIFY_API_KEY" .env; then
        echo -e "${RED}Обнаружены placeholder API ключи в .env файле. Пожалуйста, настройте реальные ключи.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}Конфигурация .env корректна${NC}"
fi

# Запуск Docker контейнера
echo -e "${YELLOW}Собираем и запускаем Docker контейнер...${NC}"
docker compose down
docker compose build --no-cache
docker compose up -d

# Проверка статуса
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Контейнер запущен успешно!${NC}"
    
    # Ждем несколько секунд для инициализации
    echo -e "${YELLOW}Ожидаем инициализацию бота...${NC}"
    sleep 5
    
    # Проверяем статус контейнера
    if docker compose ps | grep -q "Up"; then
        echo -e "${GREEN}✅ Бот успешно запущен и работает!${NC}"
        echo -e "${YELLOW}📋 Полезные команды:${NC}"
        echo -e "  Просмотр логов: ${GREEN}docker compose logs -f${NC}"
        echo -e "  Перезапуск: ${GREEN}docker compose restart${NC}"
        echo -e "  Остановка: ${GREEN}docker compose down${NC}"
        echo -e "  Статус: ${GREEN}docker compose ps${NC}"
        
        # Показываем последние логи для проверки
        echo -e "${YELLOW}📄 Последние логи (для проверки):${NC}"
        docker compose logs --tail=10
        
        echo -e "${GREEN}🎉 Развертывание завершено успешно!${NC}"
    else
        echo -e "${RED}❌ Контейнер запустился, но не работает корректно${NC}"
        echo -e "${YELLOW}Логи для диагностики:${NC}"
        docker compose logs --tail=20
        exit 1
    fi
else
    echo -e "${RED}❌ Произошла ошибка при запуске контейнера${NC}"
    exit 1
fi