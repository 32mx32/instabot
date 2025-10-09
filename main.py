import os
import requests
import re
import uuid
import json
import time
from urllib.parse import urlparse
from apify_client import ApifyClient
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN, APIFY_API_KEY, DELETE_AFTER_SEND
import logging
from collections import defaultdict
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Регулярные выражения для Instagram контента
INSTAGRAM_REEL_REGEX = re.compile(
    r'^\s*@?(https?://)?(www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?(\?.*?)?(\s|$)',
    re.IGNORECASE
)

# Regex для обычных постов и TV
INSTAGRAM_POST_REGEX = re.compile(
    r'^\s*@?(https?://)?(www\.)?instagram\.com/(p|tv)/[A-Za-z0-9_-]+/?(\?.*?)?(\s|$)',
    re.IGNORECASE
)

# Регулярное выражение для обнаружения ключа комментария
COMMENT_KEY_REGEX = re.compile(r'(/w|/W)\b', re.IGNORECASE)

# Словарь для хранения комментариев по ID сообщения с ограничением размера
COMMENTS_CACHE = {}
MAX_CACHE_SIZE = 1000  # Максимальное количество комментариев в кэше

# Словарь для хранения URL для повторной попытки скачивания
RETRY_URL_CACHE = {}

# Rate limiting
user_requests = defaultdict(list)
MAX_REQUESTS_PER_MINUTE = 5

# Статистика
stats = {
    'total_downloads': 0,
    'successful_downloads': 0,
    'failed_downloads': 0,
    'users': set()
}

# Префикс для callback данных
SHOW_COMMENT_PREFIX = "show_comment:"
HIDE_COMMENT_PREFIX = "hide_comment:"
RETRY_DOWNLOAD_PREFIX = "retry:"


def clean_comments_cache():
    """Очищает кэш комментариев, если он превышает максимальный размер"""
    global COMMENTS_CACHE
    if len(COMMENTS_CACHE) > MAX_CACHE_SIZE:
        # Удаляем половину самых старых записей
        items_to_remove = len(COMMENTS_CACHE) - MAX_CACHE_SIZE // 2
        keys_to_remove = list(COMMENTS_CACHE.keys())[:items_to_remove]
        for key in keys_to_remove:
            del COMMENTS_CACHE[key]
        logger.info(f"Очищен кэш комментариев: удалено {items_to_remove} записей")


def clean_retry_url_cache():
    """Очищает кэш URL для повторных попыток, если он превышает максимальный размер"""
    global RETRY_URL_CACHE
    if len(RETRY_URL_CACHE) > MAX_CACHE_SIZE:
        # Удаляем половину самых старых записей
        items_to_remove = len(RETRY_URL_CACHE) - MAX_CACHE_SIZE // 2
        keys_to_remove = list(RETRY_URL_CACHE.keys())[:items_to_remove]
        for key in keys_to_remove:
            del RETRY_URL_CACHE[key]
        logger.info(f"Очищен кэш URL: удалено {items_to_remove} записей")


def check_rate_limit(user_id):
    """Проверяет rate limit для пользователя"""
    now = datetime.now()
    # Удаляем запросы старше 1 минуты
    user_requests[user_id] = [
        req_time for req_time in user_requests[user_id]
        if now - req_time < timedelta(minutes=1)
    ]
    
    if len(user_requests[user_id]) >= MAX_REQUESTS_PER_MINUTE:
        return False
    
    user_requests[user_id].append(now)
    return True


def is_exact_reel_url(text):
    """Проверяет, является ли текст точной ссылкой на Reels."""
    return bool(INSTAGRAM_REEL_REGEX.match(text))


def should_include_comment(text):
    """Проверяет, содержит ли текст ключ для включения комментария."""
    if text is None:
        return False
    return bool(COMMENT_KEY_REGEX.search(text))


# Функция для очистки URL от ключей
def clean_url(text):
    """Извлекает чистый URL Instagram из текста (Reels или обычные посты)."""
    # Сначала проверяем Reels
    match = INSTAGRAM_REEL_REGEX.search(text)
    if not match:
        # Проверяем обычные посты
        match = INSTAGRAM_POST_REGEX.search(text)
    
    if match:
        # Извлекаем только URL часть
        url_part = match.group(0).strip()
        # Убираем возможные пробелы в конце URL
        url_part = url_part.rstrip()
        # Убираем символ @ в начале, если он есть
        if url_part.startswith('@'):
            url_part = url_part[1:]
        return url_part
    return None


# Функция для скачивания файла по URL
def download_file(url, folder="instagram_downloads", timeout=30):
    try:
        # Парсим URL для получения чистого имени файла
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        filename = filename.split('?')[0]  # Убираем параметры запроса
        
        # Если имя файла пустое или не содержит расширения, добавляем случайное имя
        if not filename or '.' not in filename:
            try:
                # Проверяем тип контента с таймаутом
                head_response = requests.head(url, timeout=timeout)
                content_type = head_response.headers.get('Content-Type', '')
                extension = '.mp4' if 'video' in content_type else '.jpg'
            except requests.RequestException as e:
                logger.warning(f"Не удалось определить тип контента: {e}, используем .mp4 по умолчанию")
                extension = '.mp4'
            filename = f"{uuid.uuid4().hex}{extension}"

        # Создаём папку для сохранения медиа, если её нет
        if not os.path.exists(folder):
            os.makedirs(folder)

        file_path = os.path.join(folder, filename)

        # Отправляем GET-запрос к URL с таймаутом
        response = requests.get(url, stream=True, timeout=timeout)

        # Проверка статуса ответа
        if response.status_code == 200:
            # Определяем тип контента
            content_type = response.headers.get('Content-Type', '').lower()
            logger.info(f"Content-Type для {url}: {content_type}")
            if 'video' in content_type:
                file_type = "video"
            elif 'image' in content_type:
                file_type = "photo"
            else:
                logger.warning(f"Неизвестный тип контента: {content_type}, попробуем определить по расширению")
                # Определяем тип по расширению файла
                if filename.lower().endswith(('.mp4', '.mov', '.avi', '.webm')):
                    file_type = "video"
                elif filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    file_type = "photo"
                else:
                    # По умолчанию считаем, что это видео (для Reels это более вероятно)
                    file_type = "video"

            # Сохраняем файл
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            logger.info(f"Файл успешно скачан: {file_path}")
            return file_path, file_type
        else:
            logger.error(f"Ошибка при скачивании файла. Код статуса: {response.status_code}")
            return None, None

    except requests.exceptions.Timeout:
        logger.error(f"Таймаут при скачивании файла: {url}")
        return None, None
    except requests.exceptions.ConnectionError:
        logger.error(f"Ошибка соединения при скачивании файла: {url}")
        return None, None
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка HTTP запроса при скачивании файла: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при скачивании файла: {e}")
        return None, None


def retry_apify_request(func, max_retries=3, delay=2):
    """Retry механизм для Apify запросов"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            logger.warning(f"Попытка {attempt + 1} не удалась: {e}. Повторяем через {delay} секунд...")
            time.sleep(delay)
            delay *= 2  # Экспоненциальная задержка


async def download_reel_with_retry(post_url, max_attempts=3, status_message=None):
    """Скачивание Reels с несколькими попытками и индикатором прогресса"""
    for attempt in range(1, max_attempts + 1):
        logger.info(f"Попытка скачивания {attempt}/{max_attempts}: {post_url}")
        
        # Обновляем индикатор прогресса
        if status_message:
            try:
                progress_text = f"⏳ Скачиваю контент... (попытка {attempt}/{max_attempts})"
                await status_message.edit_text(progress_text)
            except Exception as e:
                logger.warning(f"Не удалось обновить статус: {e}")
        
        file_path, file_type, caption = download_instagram_reel(post_url)
        if file_path:
            return file_path, file_type, caption
        if attempt < max_attempts:
            logger.warning(f"Попытка {attempt} не удалась, ожидаем 3 секунды перед повтором...")
            time.sleep(3)
    return None, None, None

# Функция для скачивания Reels через Apify
def download_instagram_reel(post_url, timeout=60):
    try:
        # Инициализация клиента Apify
        client = ApifyClient(APIFY_API_KEY)
        
        # Переменные для хранения результатов
        file_path = None
        file_type = None
        caption = None
        
        # Попытка 1: Используем easyapi/instagram-reels-downloader
        try:
            logger.info(f"Пытаемся скачать с помощью easyapi/instagram-reels-downloader: {post_url}")
            
            def run_easyapi():
                run_input = {
                    "reelUrls": [post_url],
                }
                return client.actor("easyapi/instagram-reels-downloader").call(run_input=run_input)
            
            run = retry_apify_request(run_easyapi)
            
            # Получаем результаты
            dataset_items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            # Отладочный вывод
            logger.info(f"Полученные данные (easyapi): {dataset_items}")
            
            if dataset_items:
                # Обработка данных
                reel_data = dataset_items[0]
                media_url = reel_data.get("videoUrl") or reel_data.get("mediaUrl") or reel_data.get("downloadUrl")
                logger.info(f"Media URL (easyapi): {media_url}")
                
                # Пытаемся получить описание/комментарий
                caption = reel_data.get("caption") or reel_data.get("description") or reel_data.get("text")
                logger.info(f"Caption (easyapi): {caption}")
                
                if media_url:
                    # Скачиваем файл по полученному URL
                    file_path, file_type = download_file(media_url)
                    
                    if file_path:
                        return file_path, file_type, caption
        except Exception as e1:
            logger.warning(f"Ошибка при скачивании через easyapi/instagram-reels-downloader: {e1}")
        
        # Попытка 2: Используем apify/instagram-reel-scraper
        try:
            logger.info(f"Пытаемся скачать с помощью apify/instagram-reel-scraper: {post_url}")
            
            def run_apify_scraper():
                run_input = {
                    "usernames": [],
                    "urls": [post_url],
                    "resultsLimit": 1
                }
                return client.actor("apify/instagram-reel-scraper").call(run_input=run_input)
            
            run = retry_apify_request(run_apify_scraper)
            
            # Получаем результаты
            dataset_items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            # Отладочный вывод
            logger.info(f"Полученные данные (apify): {dataset_items}")
            
            if dataset_items:
                # Обработка данных
                reel_data = dataset_items[0]
                media_url = None
                
                # Пытаемся найти URL видео среди медиа
                if "media" in reel_data and isinstance(reel_data["media"], list):
                    for media_item in reel_data["media"]:
                        if "videoUrl" in media_item:
                            media_url = media_item["videoUrl"]
                            break
                        elif "url" in media_item:
                            media_url = media_item["url"]
                            break
                
                # Резервные варианты для получения URL
                if not media_url:
                    media_url = reel_data.get("videoUrl") or reel_data.get("mediaUrl") or reel_data.get("downloadUrl")
                
                # Получаем подпись/комментарий если еще не получили
                if not caption:
                    caption = reel_data.get("caption") or reel_data.get("text") or reel_data.get("description")
                
                logger.info(f"Media URL (apify): {media_url}")
                logger.info(f"Caption (apify): {caption}")
                
                if media_url:
                    # Скачиваем файл по полученному URL
                    file_path, file_type = download_file(media_url)
                    
                    if file_path:
                        return file_path, file_type, caption
        except Exception as e2:
            logger.warning(f"Ошибка при скачивании через apify/instagram-reel-scraper: {e2}")
            
        # Попытка 3: Используем старый метод (presetshubham/instagram-reel-downloader)
        try:
            logger.info(f"Пытаемся скачать с помощью оригинального метода: {post_url}")
            
            def run_original_method():
                run_input = {
                    "reelLinks": [post_url],
                }
                return client.actor("presetshubham/instagram-reel-downloader").call(run_input=run_input)
            
            run = retry_apify_request(run_original_method)
            
            # Получаем результаты
            dataset_items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            # Отладочный вывод
            logger.info(f"Полученные данные (оригинальный): {dataset_items}")
            
            if dataset_items:
                # Обработка данных
                reel_data = dataset_items[0]
                media_url = reel_data.get("video_url") or reel_data.get("url")
                
                # Получаем подпись/комментарий если еще не получили
                if not caption:
                    caption = reel_data.get("caption") or reel_data.get("description")
                
                logger.info(f"Media URL (оригинальный): {media_url}")
                logger.info(f"Caption (оригинальный): {caption}")
                
                if media_url:
                    # Скачиваем файл по полученному URL
                    file_path, file_type = download_file(media_url)
                    
                    if file_path:
                        return file_path, file_type, caption
        except Exception as e3:
            logger.warning(f"Ошибка при скачивании через оригинальный метод: {e3}")
        
        logger.error("Все методы скачивания Reels не удались.")
        return None, None, None
    except Exception as e:
        logger.error(f"Общая ошибка при скачивании Reels: {e}")
        return None, None, None


# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
👋 Привет! Я бот для скачивания контента из Instagram.

📝 **Что я умею:**
• Скачивать Reels
• Скачивать обычные посты (фото/видео)
• Показывать комментарии к постам

🔧 **Команды:**
/start - Начать работу
/help - Справка
/stats - Статистика бота

📌 **Как пользоваться:**
Просто отправьте мне ссылку на пост или Reels из Instagram!
    """
    await update.message.reply_text(welcome_text)


# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📖 **Подробная справка**

**Поддерживаемые ссылки:**
• instagram.com/reel/... (Reels)
• instagram.com/p/... (обычные посты)
• instagram.com/tv/... (IGTV)

**Как скачать:**
1. Откройте Instagram
2. Найдите пост или Reels
3. Нажмите "Поделиться" → "Копировать ссылку"
4. Отправьте ссылку мне

**Комментарии:**
Если к посту есть комментарий, появится кнопка "Показать комментарий"

**Ограничения:**
• Максимум 5 запросов в минуту
• Приватные аккаунты недоступны
• Stories не поддерживаются

**Команды:**
/start - Главное меню
/help - Эта справка
/stats - Статистика использования

❓ Возникли проблемы? Попробуйте нажать кнопку "🔄 Повторить" если скачивание не удалось.
    """
    await update.message.reply_text(help_text)


# Обработчик команды /stats
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats_text = f"""
📊 **Статистика бота**

📥 Всего запросов: {stats['total_downloads']}
✅ Успешно скачано: {stats['successful_downloads']}
❌ Ошибок: {stats['failed_downloads']}
👥 Уникальных пользователей: {len(stats['users'])}

🎯 Процент успеха: {(stats['successful_downloads'] / stats['total_downloads'] * 100) if stats['total_downloads'] > 0 else 0:.1f}%
    """
    await update.message.reply_text(stats_text)


# Обработчик для inline-кнопок
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # Получаем данные из callback query
    callback_data = query.data
    logger.info(f"Получен callback: {callback_data}")
    
    # Проверяем, является ли это callback для отображения комментария
    if callback_data.startswith(SHOW_COMMENT_PREFIX):
        comment_id = callback_data[len(SHOW_COMMENT_PREFIX):]
        
        # Получаем комментарий из кэша
        if comment_id in COMMENTS_CACHE:
            comment_text = COMMENTS_CACHE[comment_id]
            
            # Показываем комментарий как временное всплывающее сообщение
            # Оно будет видно 10 секунд, что достаточно для прочтения
            await query.answer(
                f"💬 {comment_text[:195] + '...' if len(comment_text) > 195 else comment_text}",
                show_alert=True
            )
            
    # Проверяем, является ли это callback для скрытия комментария
    elif callback_data.startswith(HIDE_COMMENT_PREFIX):
        message_uuid = callback_data[len(HIDE_COMMENT_PREFIX):]
        
        # Получаем информацию о конкретном сообщении по его уникальному идентификатору
        if context.user_data.get('comment_messages') and message_uuid in context.user_data['comment_messages']:
            message_info = context.user_data['comment_messages'][message_uuid]
            
            try:
                # Удаляем сообщение
                await context.bot.delete_message(
                    chat_id=message_info['chat_id'],
                    message_id=message_info['message_id']
                )
                # Удаляем информацию о сообщении из контекста
                del context.user_data['comment_messages'][message_uuid]
                await query.answer("Комментарий скрыт")
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение с комментарием: {e}")
                await query.answer("Не удалось скрыть комментарий")
        else:
            logger.warning(f"Информация о сообщении не найдена для UUID: {message_uuid}")
            await query.answer("Сообщение не найдено")
    
    # Проверяем, является ли это callback для повторной попытки скачивания
    elif callback_data.startswith(RETRY_DOWNLOAD_PREFIX):
        retry_id = callback_data[len(RETRY_DOWNLOAD_PREFIX):]
        
        # Получаем URL из кэша
        if retry_id not in RETRY_URL_CACHE:
            logger.error(f"URL не найден в кэше для retry_id: {retry_id}")
            await query.answer("⚠️ Ссылка устарела. Отправьте URL снова.")
            return
        
        reel_url = RETRY_URL_CACHE[retry_id]
        logger.info(f"Повторная попытка скачивания: {reel_url}")
        
        # Обновляем сообщение
        status_msg = await query.edit_message_text("⏳ Скачиваю контент...")
        await query.answer()
        
        # Скачиваем Reels с 3 попытками и индикатором прогресса
        file_path, file_type, caption_text = await download_reel_with_retry(reel_url, status_message=status_msg)
        
        if file_path:
            try:
                # Базовая подпись с кликабельной ссылкой на Reels
                caption = f"[Reels]({reel_url})"
                
                # Создаем inline-клавиатуру если есть комментарий
                keyboard = None
                if caption_text:
                    # Очищаем кэш при необходимости
                    clean_comments_cache()
                    
                    # Генерируем уникальный ID для комментария
                    comment_id = str(uuid.uuid4())
                    # Сохраняем комментарий в кэш
                    COMMENTS_CACHE[comment_id] = caption_text
                    # Создаем кнопку для отображения комментария
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("Показать комментарий", callback_data=f"{SHOW_COMMENT_PREFIX}{comment_id}")]
                    ])
                    logger.info(f"Сохранен комментарий с ID {comment_id}: {caption_text[:50]}...")

                # Извлекаем message_thread_id из сообщения
                message_thread_id = query.message.message_thread_id if hasattr(query.message, 'message_thread_id') else None

                kwargs = {
                    "chat_id": query.message.chat_id,
                    "caption": caption,
                    "parse_mode": 'Markdown',
                    "reply_markup": keyboard
                }
                
                # Добавляем message_thread_id только если он не None
                if message_thread_id is not None:
                    kwargs["message_thread_id"] = message_thread_id

                if file_type == "video":
                    with open(file_path, "rb") as video_file:
                        await context.bot.send_video(
                            video=video_file,
                            **kwargs
                        )
                elif file_type == "photo":
                    with open(file_path, "rb") as photo_file:
                        await context.bot.send_photo(
                            photo=photo_file,
                            **kwargs
                        )
                else:
                    await query.edit_message_text("Неизвестный тип медиа.")

                # Удаляем сообщение об ошибке
                try:
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=query.message.message_id
                    )
                except Exception as e:
                    logger.warning(f"Не удалось удалить сообщение: {e}")

                # Удаление скачанного файла после отправки, если включено
                if DELETE_AFTER_SEND:
                    try:
                        os.remove(file_path)
                        logger.info(f"Файл {file_path} удален.")
                    except Exception as e:
                        logger.warning(f"Не удалось удалить файл {file_path}: {e}")
            except FileNotFoundError:
                logger.error("Файл не был найден. Возможно, произошла ошибка при скачивании.")
                await query.edit_message_text("⚠️ Файл не был найден. Возможно, пост недоступен или был удален.")
            except Exception as e:
                logger.error(f"Произошла ошибка при отправке файла: {e}")
                await query.edit_message_text(f"⚠️ Произошла ошибка при отправке файла: {e}")
        else:
            # Если снова не удалось скачать - обновляем сообщение с кнопкой
            logger.error("Не удалось скачать Reels после повторной попытки.")
            # Очищаем кэш при необходимости
            clean_retry_url_cache()
            # Генерируем уникальный ID для URL
            retry_id = str(uuid.uuid4())[:8]  # Используем короткий ID
            # Сохраняем URL в кэш
            RETRY_URL_CACHE[retry_id] = reel_url
            retry_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Повторить", callback_data=f"{RETRY_DOWNLOAD_PREFIX}{retry_id}")]
            ])
            await query.edit_message_text(
                f"⚠️ Не удалось скачать Reels после 3 попыток.\n"
                f"Ссылка: {reel_url}\n\n"
                "Возможные причины:\n"
                "• Пост недоступен или был удален\n"
                "• Аккаунт является приватным\n"
                "• Контент защищен от скачивания\n"
                "• Неверная ссылка\n\n"
                "Вы можете попробовать снова, нажав кнопку ниже.",
                reply_markup=retry_keyboard
            )
    else:
        await query.answer()


# Обработчик текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    caption_text = update.message.caption if hasattr(update.message, 'caption') else ""
    
    # Добавляем пользователя в статистику
    stats['users'].add(user_id)
    
    # Проверяем rate limit
    if not check_rate_limit(user_id):
        await update.message.reply_text(
            "⏰ Слишком много запросов!\n\n"
            f"Пожалуйста, подождите немного. Максимум {MAX_REQUESTS_PER_MINUTE} запросов в минуту.\n"
            "Попробуйте через минуту."
        )
        logger.warning(f"Rate limit exceeded for user {user_id}")
        return
    
    # Проверяем наличие ключа для включения комментария
    include_comment = should_include_comment(user_message) or should_include_comment(caption_text)
    
    # Проверяем, является ли сообщение ссылкой на Instagram Stories
    if 'instagram.com/stories/' in user_message:
        await update.message.reply_text(
            "⚠️ Этот контент недоступен для скачивания, так как это Instagram Stories.\n"
            "Бот может скачивать только Reels и обычные посты."
        )
        return
    
    # Проверяем, содержит ли сообщение ссылку на Instagram
    extracted_url = clean_url(user_message)
    if extracted_url:
        # Увеличиваем счетчик запросов
        stats['total_downloads'] += 1
        logger.info(f"Получена ссылка на Reels: {extracted_url}")
        # Отправляем сообщение о статусе скачивания
        try:
            status_message = await update.message.reply_text("Скачиваю Reels...")
        except Exception as e:
            logger.error(f"Не удалось отправить статусное сообщение: {e}")
            status_message = None

        # Скачиваем Reels через Apify с 3 попытками и индикатором прогресса
        file_path, file_type, caption_text = await download_reel_with_retry(extracted_url, status_message=status_message)

        if file_path:
            # Обновляем статистику - успешно
            stats['successful_downloads'] += 1
            try:
                # Базовая подпись с кликабельной ссылкой на Reels
                caption = f"[Reels]({extracted_url})"
                
                # Создаем inline-клавиатуру если есть комментарий
                keyboard = None
                if caption_text:
                    # Очищаем кэш при необходимости
                    clean_comments_cache()
                    
                    # Генерируем уникальный ID для комментария
                    comment_id = str(uuid.uuid4())
                    # Сохраняем комментарий в кэш
                    COMMENTS_CACHE[comment_id] = caption_text
                    # Создаем кнопку для отображения комментария
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("Показать комментарий", callback_data=f"{SHOW_COMMENT_PREFIX}{comment_id}")]
                    ])
                    logger.info(f"Сохранен комментарий с ID {comment_id}: {caption_text[:50]}...")

                # Извлекаем message_thread_id из входящего сообщения
                message_thread_id = update.message.message_thread_id if hasattr(update.message, 'message_thread_id') else None

                kwargs = {
                    "chat_id": update.effective_chat.id,
                    "caption": caption,
                    "parse_mode": 'Markdown',
                    "reply_markup": keyboard  # Добавляем inline-клавиатуру
                }
                
                # Добавляем message_thread_id только если он не None
                if message_thread_id is not None:
                    kwargs["message_thread_id"] = message_thread_id

                if file_type == "video":
                    with open(file_path, "rb") as video_file:
                        await context.bot.send_video(
                            video=video_file,
                            **kwargs
                        )
                elif file_type == "photo":
                    with open(file_path, "rb") as photo_file:
                        await context.bot.send_photo(
                            photo=photo_file,
                            **kwargs
                        )
                else:
                    await update.message.reply_text("Неизвестный тип медиа.")

                # Удаляем оригинальное сообщение пользователя и статусное сообщение
                try:
                    await context.bot.delete_message(chat_id=update.effective_chat.id,
                                                     message_id=update.message.message_id)
                except Exception as e:
                    logger.warning(f"Не удалось удалить оригинальное сообщение: {e}")

                if status_message:
                    try:
                        await context.bot.delete_message(chat_id=update.effective_chat.id,
                                                         message_id=status_message.message_id)
                    except Exception as e:
                        logger.warning(f"Не удалось удалить статусное сообщение: {e}")

                # Удаление скачанного файла после отправки, если включено
                if DELETE_AFTER_SEND:
                    try:
                        os.remove(file_path)
                        logger.info(f"Файл {file_path} удален.")
                    except Exception as e:
                        logger.warning(f"Не удалось удалить файл {file_path}: {e}")
            except FileNotFoundError:
                logger.error("Файл не был найден. Возможно, произошла ошибка при скачивании.")
                await update.message.reply_text("⚠️ Файл не был найден. Возможно, пост недоступен или был удален.")
            except Exception as e:
                logger.error(f"Произошла ошибка при отправке файла: {e}")
                await update.message.reply_text(f"⚠️ Произошла ошибка при отправке файла: {e}")
        else:
            # Обновляем статистику - неудача
            stats['failed_downloads'] += 1
            logger.error("Не удалось скачать Reels после 3 попыток. Проверьте ссылку.")
            # Очищаем кэш при необходимости
            clean_retry_url_cache()
            # Генерируем уникальный ID для URL
            retry_id = str(uuid.uuid4())[:8]  # Используем короткий ID
            # Сохраняем URL в кэш
            RETRY_URL_CACHE[retry_id] = extracted_url
            # Создаем кнопку "Повторить" с коротким ID в callback_data
            retry_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Повторить", callback_data=f"{RETRY_DOWNLOAD_PREFIX}{retry_id}")]
            ])
            
            # Извлекаем message_thread_id из входящего сообщения
            message_thread_id = update.message.message_thread_id if hasattr(update.message, 'message_thread_id') else None
            
            kwargs = {
                "chat_id": update.effective_chat.id,
                "text": f"⚠️ Не удалось скачать Reels после 3 попыток.\n"
                        f"Ссылка: {extracted_url}\n\n"
                        "Возможные причины:\n"
                        "• Пост недоступен или был удален\n"
                        "• Аккаунт является приватным\n"
                        "• Контент защищен от скачивания\n"
                        "• Неверная ссылка\n\n"
                        "Вы можете попробовать снова, нажав кнопку ниже.",
                "reply_markup": retry_keyboard
            }
            
            # Добавляем message_thread_id только если он не None
            if message_thread_id is not None:
                kwargs["message_thread_id"] = message_thread_id
            
            await context.bot.send_message(**kwargs)
            
            # Удаляем статусное сообщение
            if status_message:
                try:
                    await context.bot.delete_message(chat_id=update.effective_chat.id,
                                                     message_id=status_message.message_id)
                except Exception as e:
                    logger.warning(f"Не удалось удалить статусное сообщение: {e}")
            
            # Удаляем исходное сообщение пользователя со ссылкой
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id,
                                                 message_id=update.message.message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить исходное сообщение: {e}")
    elif 'instagram.com' in user_message:
        # Если это ссылка на Instagram, но не на Reels
        await update.message.reply_text(
            "⚠️ Эта ссылка не является ссылкой на Reels.\n"
            "Бот может скачивать только Reels из Instagram."
        )
    else:
        # Игнорируем все остальные сообщения
        logger.info(f"Сообщение не соответствует ссылке на Reels и будет проигнорировано: {user_message}")
        pass  # Бот не отвечает на сообщения без точных ссылок на Reels


# Запуск бота
if __name__ == "__main__":
    try:
        logger.info("Запуск бота...")
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Регистрация обработчиков
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("stats", stats_command))
        app.add_handler(CallbackQueryHandler(button_callback))  # Обработчик для inline-кнопок
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Запуск бота
        app.run_polling()
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
