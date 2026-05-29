#!/bin/bash

# Быстрое развертывание бота (без установки Docker)
set -e

# Цвета для красивого вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🔄 Быстрое обновление Instagram Telegram бота...${NC}"

# Проверяем, что мы в правильной директории
if [ ! -f "main.py" ] || [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}❌ Ошибка: Запустите скрипт из директории проекта instabot${NC}"
    exit 1
fi

# Проверяем наличие .env файла
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ Файл .env не найден. Запустите install.sh для первоначальной настройки.${NC}"
    exit 1
fi

# Проверяем, что токены настроены
if grep -q "YOUR_TELEGRAM_BOT_TOKEN" .env || grep -q "YOUR_APIFY_API_KEY" .env || grep -q "YOUR_APIFY_API_KEYS" .env; then
    echo -e "${RED}❌ Обнаружены placeholder токены в .env файле. Настройте реальные токены.${NC}"
    exit 1
fi

if ! grep -Eq "^(APIFY_API_KEY|APIFY_API_KEYS)=apify_api_" .env; then
    echo -e "${RED}❌ В .env не найден ни один реальный Apify API ключ.${NC}"
    exit 1
fi

echo -e "${YELLOW}📥 Обновляем репозиторий...${NC}"
git pull

echo -e "${YELLOW}🔄 Перезапускаем контейнер...${NC}"
docker compose down
docker compose build --no-cache
docker compose up -d

# Ждем инициализацию
echo -e "${YELLOW}⏳ Ожидаем инициализацию...${NC}"
sleep 3

# Проверяем статус
if docker compose ps | grep -q "Up"; then
    echo -e "${GREEN}✅ Бот успешно обновлен и перезапущен!${NC}"
    echo -e "${YELLOW}📄 Последние логи:${NC}"
    docker compose logs --tail=5
    echo -e "${YELLOW}📋 Полезные команды:${NC}"
    echo -e "  Просмотр логов: ${GREEN}docker compose logs -f${NC}"
    echo -e "  Статус: ${GREEN}docker compose ps${NC}"
else
    echo -e "${RED}❌ Контейнер не запустился корректно${NC}"
    echo -e "${YELLOW}Логи для диагностики:${NC}"
    docker compose logs --tail=10
    exit 1
fi
