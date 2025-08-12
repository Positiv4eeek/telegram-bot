# Telegram Bot для загрузки видео

Простой Telegram бот для автоматического скачивания видео и аудио из TikTok, YouTube Shorts и Instagram Reels.

## Возможности

- 📱 **TikTok** - автоматическое скачивание видео + аудио
- 🎬 **YouTube Shorts** - автоматическое скачивание видео + аудио  
- 📸 **Instagram Reels** - автоматическое скачивание видео + аудио
- ⚡ **Мгновенная отправка** со встроенными плеерами
- 🗑️ **Автоочистка** временных файлов
- 📊 **Статистика** пользователей

## Быстрый старт

### 🏠 Локальная установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/Positiv4eeek/telegram-bot.git
cd telegram-bot
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Создайте файл `.env`:
```env
BOT_TOKEN=your_bot_token_here
DATABASE_URL=sqlite+aiosqlite:///./bot.db
MAX_MB=48
YTDLP_TIMEOUT=180
```

4. Запустите:
```bash
python main.py
```

### 🐧 Деплой на Linux сервер

1. Клонируйте на сервер:
```bash
git clone https://github.com/Positiv4eeek/telegram-bot.git
cd telegram-bot
```

2. Запустите автодеплой:
```bash
chmod +x deploy-linux.sh
./deploy-linux.sh
```

3. Настройте токен:
```bash
nano .env  # Установите BOT_TOKEN
```

4. Запустите сервис:
```bash
sudo systemctl enable telegram-bot
sudo systemctl start telegram-bot
```

### 🐳 Docker

```bash
docker-compose up -d
```

## Использование

1. Найдите бота в Telegram
2. Отправьте команду `/start`
3. Просто отправьте ссылку на TikTok/YouTube Shorts/Instagram Reels
4. Бот автоматически скачает и отправит видео + аудио

## Решение проблем

### 🚫 Instagram требует авторизацию

Если при загрузке Instagram Reels появляется ошибка "Authorization in Instagram is required":

1. **Установите расширение get cookies.txt** в ваш браузер
2. **Войдите в Instagram** в браузере
3. **Экспортируйте cookies** через расширение get cookies.txt
4. **Добавьте путь к cookies в .env:**
```env
INSTAGRAM_COOKIES=/path/to/instagram_cookies.txt
```
5. **Перезапустите бота**

#### Требования для cookies:
- ✅ Войдите в Instagram в браузере
- ✅ Убедитесь, что вы авторизованы
- ✅ Cookies должны быть актуальными

## Требования

- Python 3.11+
- FFmpeg
- Telegram bot token от @BotFather

## Управление на сервере

```bash
sudo systemctl status telegram-bot     # Статус
sudo systemctl restart telegram-bot    # Перезапуск
sudo journalctl -u telegram-bot -f     # Логи
git pull && sudo systemctl restart telegram-bot  # Обновление
```