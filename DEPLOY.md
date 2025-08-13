# Установка и деплой

## Быстрый старт (локально)

1) Клонировать репозиторий
```bash
git clone https://github.com/Positiv4eeek/telegram-bot.git
cd telegram-bot
```

2) Установить зависимости
```bash
pip install -r requirements.txt
```

3) Создать `.env`
```env
BOT_TOKEN=your_bot_token_here
DATABASE_URL=sqlite+aiosqlite:///./bot.db
MAX_MB=48
YTDLP_TIMEOUT=180
# Для Instagram:
INSTAGRAM_COOKIES=/abs/path/to/instagram_cookies.
# FFmpeg (если не в PATH)
FFMPEG_PATH=
```

4) Запуск
```bash
python main.py
```

## Деплой на Linux-сервер

1) Клонировать
```bash
git clone https://github.com/Positiv4eeek/telegram-bot.git
cd telegram-bot
```

2) Автодеплой
```bash
chmod +x deploy-linux.sh
./deploy-linux.sh
```

3) Настроить переменные
```bash
nano .env
# установите BOT_TOKEN и, при необходимости, INSTAGRAM_COOKIES
```

4) Управление сервисом
```bash
sudo systemctl enable telegram-bot
sudo systemctl restart telegram-bot
sudo systemctl status telegram-bot
sudo journalctl -u telegram-bot -f
```

## Docker
```bash
docker-compose up -d
```

## Обновление кода
```bash
cd ~/telegram-bot
git pull origin main
sudo systemctl restart telegram-bot
```
