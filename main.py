# main.py
import logging
import asyncio
import signal
import sys
import socket

from app.bot import create_bot_dp
from app.routers import build_router
from app.core.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

shutdown_event = asyncio.Event()

def signal_handler(signum, frame):
    logger.info(f"Получен сигнал {signum}, начинаю shutdown...")
    shutdown_event.set()

async def _run():
    try:
        logger.info("Инициализация базы данных...")
        await init_db()
        logger.info("База данных инициализирована")

        # Создаём bot/dp уже внутри event loop
        bot, dp = create_bot_dp()
        dp.include_router(build_router())
        logger.info("Роутеры подключены")

        # (необязательно) лог для проверки IPv4
        ip4 = socket.getaddrinfo("api.telegram.org", 443, socket.AF_INET)
        logger.info(f"Resolved api.telegram.org over IPv4 -> {ip4[0][4]}")

        logger.info("Запуск бота...")
        await dp.start_polling(bot, stop_signals=())
        await shutdown_event.wait()

        logger.info("Остановка бота...")
        await bot.session.close()
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")
        sys.exit(1)

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
