FROM python:3.12-slim

# ffmpeg нужен yt-dlp для склейки видео и аудио дорожек
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# --upgrade: при каждой сборке подтягиваем свежий yt-dlp
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . .

RUN mkdir -p /app/instagram_downloads /app/logs

CMD ["python", "main.py"]
