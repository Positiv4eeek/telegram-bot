import socket
from aiohttp import TCPConnector
from aiogram import Bot, Dispatcher
from app.core.config import settings
from app.core.telemetry import UserMiddleware

connector = TCPConnector(family=socket.AF_INET)

bot = Bot(token=settings.bot_token, connector=connector)
dp = Dispatcher()

dp.message.middleware(UserMiddleware())
dp.callback_query.middleware(UserMiddleware())
