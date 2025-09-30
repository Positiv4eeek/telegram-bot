import socket
from aiohttp import TCPConnector
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from app.core.config import settings
from app.core.telemetry import UserMiddleware

def create_bot_dp() -> tuple[Bot, Dispatcher]:
    connector = TCPConnector(family=socket.AF_INET)
    session = AiohttpSession(connector=connector)

    bot = Bot(token=settings.bot_token, session=session)
    dp = Dispatcher()

    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(UserMiddleware())

    return bot, dp
