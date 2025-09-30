from aiogram import Bot, Dispatcher
from app.core.config import settings
from app.core.telemetry import UserMiddleware

bot = Bot(token=settings.bot_token)
dp = Dispatcher()

dp.message.middleware(UserMiddleware())
dp.callback_query.middleware(UserMiddleware())
