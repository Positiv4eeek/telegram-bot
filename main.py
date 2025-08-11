import logging
import asyncio
import signal
import sys
from app.bot import bot, dp
from app.routers import build_router
from app.core.db import init_db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Флаг для graceful shutdown
shutdown_event = asyncio.Event()

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown"""
    logger.info(f"Получен сигнал {signum}, начинаю shutdown...")
    shutdown_event.set()

async def _run():
    try:
        # Инициализация базы данных
        logger.info("Инициализация базы данных...")
        await init_db()
        logger.info("База данных инициализирована")
        
        # Запуск бота
        logger.info("Запуск бота...")
        await dp.start_polling(bot, stop_signals=())
        
        # Ожидание сигнала shutdown
        await shutdown_event.wait()
        
        # Graceful shutdown
        logger.info("Остановка бота...")
        await bot.session.close()
        logger.info("Бот остановлен")
        
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")
        sys.exit(1)

def main():
    # Регистрация обработчиков сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Подключение роутеров
        dp.include_router(build_router())
        logger.info("Роутеры подключены")
        
        # Запуск основного цикла
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
