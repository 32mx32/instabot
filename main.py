import os
import requests
import re
from urllib.parse import urlparse
from apify_client import ApifyClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN, APIFY_API_KEY, DELETE_AFTER_SEND
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Регулярное выражение для точного соответствия ссылке на Reels, включая параметры запроса
INSTAGRAM_REEL_REGEX = re.compile(
    r'^\s*(https?://)?(www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?(\?.*)?$',
    re.IGNORECASE
)


def is_exact_reel_url(text):
    """Проверяет, является ли текст точной ссылкой на Reels."""
    return bool(INSTAGRAM_REEL_REGEX.match(text))


# Функция для скачивания файла по URL
def download_file(url, folder="instagram_downloads"):
    try:
        # Парсим URL для получения чистого имени файла
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        filename = filename.split('?')[0]  # Убираем параметры запроса

        # Создаём папку для сохранения медиа, если её нет
        if not os.path.exists(folder):
            os.makedirs(folder)

        file_path = os.path.join(folder, filename)

        # Отправляем GET-запрос к URL
        response = requests.get(url, stream=True)

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
                logger.warning(f"Неизвестный тип контента: {content_type}")
                return None, None

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

    except Exception as e:
        logger.error(f"Произошла ошибка при скачивании файла: {e}")
        return None, None


# Функция для скачивания Reels через Apify
def download_instagram_reel(post_url):
    try:
        # Инициализация клиента Apify
        client = ApifyClient(APIFY_API_KEY)

        # Запуск актора Instagram Reel Downloader
        run_input = {
            "reelLinks": [post_url],  # Использование reelLinks
        }
        run = client.actor("presetshubham/instagram-reel-downloader").call(run_input=run_input)

        # Получаем результаты
        dataset_items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        # Отладочный вывод
        logger.info(f"Полученные данные: {dataset_items}")

        if dataset_items:
            # Обработка данных
            reel_data = dataset_items[0]
            media_url = reel_data.get("video_url") or reel_data.get("url")
            logger.info(f"Media URL: {media_url}")

            if media_url:
                # Скачиваем файл по полученному URL
                file_path, file_type = download_file(media_url)

                if file_path:
                    return file_path, file_type
                else:
                    logger.error("Ошибка при скачивании медиафайла.")
            else:
                logger.error("Медиафайл не найден в данных.")
        else:
            logger.error("Данные не получены.")
    except Exception as e:
        logger.error(f"Ошибка при скачивании Reels: {e}")
    return None, None


# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь мне ссылку на Reels в Instagram, и я скачаю контент.")


# Обработчик текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()

    # Проверяем, является ли сообщение точной ссылкой на Instagram Reels
    if is_exact_reel_url(user_message):
        logger.info(f"Получена ссылка на Reels: {user_message}")
        # Отправляем сообщение о статусе скачивания
        try:
            status_message = await update.message.reply_text("Скачиваю Reels...")
        except Exception as e:
            logger.error(f"Не удалось отправить статусное сообщение: {e}")
            status_message = None

        # Скачиваем Reels через Apify
        file_path, file_type = download_instagram_reel(user_message)

        if file_path:
            try:
                # Формируем подпись с кликабельной ссылкой на Reels в Markdown
                caption = f"[Reels]({user_message})"

                # Извлекаем message_thread_id из входящего сообщения
                message_thread_id = update.message.message_thread_id

                if file_type == "video":
                    with open(file_path, "rb") as video_file:
                        await context.bot.send_video(
                            chat_id=update.effective_chat.id,
                            video=video_file,
                            caption=caption,
                            parse_mode='Markdown',
                            message_thread_id=message_thread_id  # Привязка к теме
                        )
                elif file_type == "photo":
                    with open(file_path, "rb") as photo_file:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo_file,
                            caption=caption,
                            parse_mode='Markdown',
                            message_thread_id=message_thread_id  # Привязка к теме
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
                await update.message.reply_text("Файл не был найден. Возможно, произошла ошибка при скачивании.")
            except Exception as e:
                logger.error(f"Произошла ошибка при отправке файла: {e}")
                await update.message.reply_text(f"Произошла ошибка при отправке файла: {e}")
        else:
            logger.error("Не удалось скачать Reels. Проверьте ссылку.")
            await update.message.reply_text(" удалось скачать Reels. Проверьте ссылку.")
    else:
        # Игнорируем все остальные сообщения
        logger.info(f"Сообщение не соответствует ссылке на Reels и будет проигнорировано: {user_message}")
        pass  # Бот не отвечает на сообщения без точных ссыл на Reels


# Запуск бота
if __name__ == "__main__":
    logger.info("Запуск бота...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Рег обработчиков
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запуск бота
    app.run_polling()
