from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, func
from app.core.db import Session
from app.core.models import Download, Event, User

router = Router()

@router.message(Command("me"))
async def me(msg: Message):
    try:
        tg_id = msg.from_user.id
        
        async with Session() as s:
            user_result = await s.execute(select(User).where(User.tg_id == tg_id))
            user = user_result.scalar()
            
            if not user:
                total_dl = 0
                total_events = 0
            else:
                total_dl = (await s.execute(select(func.count()).select_from(Download).where(Download.user_id == user.id))).scalar() or 0
                total_events = (await s.execute(select(func.count()).select_from(Event).where(Event.user_id == user.id))).scalar() or 0
        
        await msg.reply(
            f"👤 Твой профиль\n"
            f"📥 Скачиваний: {total_dl}\n"
            f"📊 Событий: {total_events}\n\n"
            f"💡 Просто отправь ссылку на TikTok/Shorts/Reels!"
        )
    except Exception as e:
        await msg.reply(f"Ошибка при получении профиля: {e}")
