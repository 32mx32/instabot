# Instagram Telegram Bot

Это Telegram-бот, который позволяет пользователям скачивать контент из Instagram, отправляя ссылки на посты.

## Установка локально

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/32mx32/instabot.git
   cd instabot
   ```

2. Убедитесь, что у вас установлен Python 3.7 или выше

3. Установите необходимые библиотеки:
    ```bash
    pip install -r requirements.txt
    ```

## Настройка GitHub через SSH

1. Сгенерируйте SSH-ключ (если еще не создан):
```bash
ssh-keygen -t ed25519 -C "ваш_email@example.com"
```

2. Добавьте SSH-ключ в ssh-agent:
```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```

3. Скопируйте публичный ключ:
```bash
# Для Mac
pbcopy < ~/.ssh/id_ed25519.pub
# Для Linux
cat ~/.ssh/id_ed25519.pub | xclip -selection clipboard
```

4. Добавьте ключ в GitHub:
   - Перейдите в Settings -> SSH and GPG keys
   - Нажмите "New SSH key"
   - Вставьте скопированный ключ
   - Сохраните

5. Измените URL репозитория на SSH:
```bash
git remote set-url origin git@github.com:32mx32/instabot.git
```

6. Проверьте подключение:
```bash
ssh -T git@github.com
```

## Конфигурация
Откройте файл config.py и замените значения переменных:

    TELEGRAM_BOT_TOKEN: токен вашего Telegram-бота.
    APIFY_API_KEY: ключ API Apify для скачивания контента Instagram.
    DELETE_AFTER_SEND: установите True, если хотите удалять скачанные файлы после отправки, или False, если хотите оставить их.

## Запуск локально в виртуальном окружении
```bash
python -m venv venv
source venv/bin/activate  # для Linux/Mac
# или
venv\Scripts\activate  # для Windows
pip install -r requirements.txt
python main.py
```

## Развертывание через Docker

### Локальное развертывание с Docker
1. Установите Docker и Docker Compose на вашу машину
2. Запустите бота с помощью Docker Compose:
   ```bash
   docker-compose up -d
   ```
3. Для просмотра логов:
   ```bash
   docker-compose logs -f
   ```

### Развертывание на сервере

#### Первоначальная установка
Для первоначальной установки бота на сервере используйте скрипт `install.sh`:

1. Скачайте скрипт на сервер:
   ```bash
   curl -O https://raw.githubusercontent.com/32mx32/instabot/main/install.sh
   chmod +x install.sh
   ```

2. Запустите скрипт:
   ```bash
   ./install.sh
   ```
   При запуске скрипт:
   - Проверит наличие Docker и Docker Compose и установит их, если необходимо
   - Клонирует репозиторий
   - Создаст и настроит файл .env
   - Запустит бота в Docker-контейнере

#### Обновление бота через SSH
Для обновления уже установленного бота используйте скрипт `update.sh`:

1. Создайте SSH-ключ для сервера (если еще не создан):
   ```bash
   ssh-keygen -t ed25519 -C "server@example.com"
   ```

2. Добавьте публичный ключ на сервер:
   ```bash
   ssh-copy-id -i ~/.ssh/id_ed25519.pub user@your-server
   ```

3. Скачайте скрипт на ваш компьютер:
   ```bash
   curl -O https://raw.githubusercontent.com/32mx32/instabot/main/update.sh
   chmod +x update.sh
   ```

4. Настройте скрипт:
   ```bash
   nano update.sh
   ```
   Измените следующие параметры:
   - SERVER_USER - имя пользователя на сервере
   - SERVER_HOST - адрес вашего сервера
   - REPO_PATH - путь к директории проекта на сервере

5. Запустите скрипт:
   ```bash
   ./update.sh
   ```

Скрипт автоматически:
- Скопирует все файлы проекта на сервер
- Перезапустит Docker-контейнеры с новыми изменениями

### Быстрое обновление бота

Если вы уже настроили бота и хотите обновить его до последней версии:

```bash
./quick-update.sh
```

### Развертывание на сервере через ручную установку

1. Клонируйте репозиторий на сервер:
   ```bash
   git clone https://github.com/32mx32/instabot.git
   cd instabot
   ```

2. Настройте файл config.py с корректными данными:
   ```bash
   cp config.example.py config.py
   nano config.py
   ```

3. Запустите бота через Docker Compose:
   ```bash
   docker-compose up -d
   ```

## CI/CD с GitHub Actions (опционально)

Для автоматического развертывания при пуше в репозиторий, вы можете настроить GitHub Actions:

1. Создайте файл `.github/workflows/deploy.yml` в вашем репозитории
2. Настройте файл для автоматического развертывания через SSH
3. Добавьте необходимые секреты в настройках GitHub репозитория:
   - SSH_PRIVATE_KEY
   - SSH_HOST
   - SSH_USER

## Использование
После запуска бота отправьте команду /start, а затем отправьте ссылку на пост в Instagram, чтобы скачать его контент.

## Лицензия
Этот проект лицензирован под MIT License - смотрите LICENSE файл для подробностей.
