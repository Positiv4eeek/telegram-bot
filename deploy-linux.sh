#!/bin/bash

# Telegram Bot Deploy Script for Linux
# Скрипт для развертывания бота на Linux сервере

echo "🚀 Развертывание Telegram бота..."

# Проверка Python 3.11+
echo "📋 Проверка Python..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
    echo "✅ Python найден: $PYTHON_VERSION"
else
    echo "❌ Python 3 не найден. Установите Python 3.11 или выше"
    exit 1
fi

# Проверка FFmpeg
echo "📋 Проверка FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo "✅ FFmpeg найден"
else
    echo "⚠️  FFmpeg не найден. Установка..."
    sudo apt update
    sudo apt install -y ffmpeg
fi

# Создание виртуальной среды
echo "📦 Создание виртуальной среды..."
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
echo "📦 Установка зависимостей..."
pip install --upgrade pip
pip install -r requirements.txt

# Создание .env файла если не существует
if [ ! -f .env ]; then
    echo "📝 Создание .env файла..."
    cat > .env << EOF
# Токен бота (получите у @BotFather)
BOT_TOKEN=your_bot_token_here

# База данных
DATABASE_URL=sqlite+aiosqlite:///./bot.db

# Максимальный размер файла в MB
MAX_MB=48

# Таймаут для yt-dlp в секундах
YTDLP_TIMEOUT=180

# Путь к ffmpeg (оставьте пустым для автоопределения)
FFMPEG_PATH=

# Время жизни токенов в минутах
TRIM_MINUTES=2
EOF
    echo "⚠️  Отредактируйте .env файл и установите ваш BOT_TOKEN!"
    echo "📝 nano .env"
else
    echo "✅ .env файл уже существует"
fi

# Создание systemd service
echo "🔧 Создание systemd service..."
SERVICE_NAME="telegram-bot"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
CURRENT_DIR=$(pwd)
USER=$(whoami)

sudo tee $SERVICE_PATH > /dev/null << EOF
[Unit]
Description=Telegram Video Downloader Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$CURRENT_DIR
Environment=PATH=$CURRENT_DIR/venv/bin
ExecStart=$CURRENT_DIR/venv/bin/python main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Systemd service создан: $SERVICE_PATH"

# Инструкции
echo ""
echo "🎉 Развертывание завершено!"
echo ""
echo "📝 Следующие шаги:"
echo "1. Отредактируйте .env файл: nano .env"
echo "2. Установите ваш BOT_TOKEN от @BotFather"
echo "3. Запустите бота:"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable $SERVICE_NAME"
echo "   sudo systemctl start $SERVICE_NAME"
echo ""
echo "📊 Управление ботом:"
echo "   sudo systemctl status $SERVICE_NAME    # Статус"
echo "   sudo systemctl restart $SERVICE_NAME   # Перезапуск"
echo "   sudo systemctl stop $SERVICE_NAME      # Остановка"
echo "   sudo journalctl -u $SERVICE_NAME -f    # Логи"
echo ""
echo "🔄 Обновление бота:"
echo "   git pull"
echo "   source venv/bin/activate"
echo "   pip install -r requirements.txt"
echo "   sudo systemctl restart $SERVICE_NAME"
