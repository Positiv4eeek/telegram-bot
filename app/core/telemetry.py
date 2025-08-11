# app/core/telemetry.py
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Dict, Any, Awaitable

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.db import Session
from app.core.models import User, Event

class UserMiddleware(BaseMiddleware):
    """
    Middleware: апсертим пользователя по tg_id на каждый апдейт
    и пишем событие 'update'. Избегает гонок UNIQUE(tg_id).
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            message = getattr(event, "message", None) or getattr(event, "callback_query", None)
            from_user = None
            if message:
                from_user = getattr(message, "from_user", None)
            if not from_user:
                return await handler(event, data)

            async with Session() as s:
                try:
                    # UPSERT по tg_id (SQLite)
                    stmt = sqlite_insert(User).values(
                        tg_id=from_user.id,
                        first_name=from_user.first_name,
                        last_name=from_user.last_name,
                        username=from_user.username,
                        lang=from_user.language_code,
                    ).on_conflict_do_update(
                        index_elements=[User.tg_id],
                        set_=dict(
                            first_name=from_user.first_name,
                            last_name=from_user.last_name,
                            username=from_user.username,
                            lang=from_user.language_code,
                        ),
                    )
                    await s.execute(stmt)

                    # Получаем/прикрепляем пользователя к контексту
                    user = (await s.execute(select(User).where(User.tg_id == from_user.id))).scalar_one()
                    
                    # Создаем событие только если пользователь найден
                    if user:
                        s.add(Event(user_id=user.id, type="update"))
                        await s.commit()
                        data["db_user"] = user
                except Exception as e:
                    # Если что-то пошло не так, логируем но не прерываем
                    print(f"Middleware database error: {e}")
                    await s.rollback()

            return await handler(event, data)
        except Exception as e:
            # Логируем ошибку, но не прерываем выполнение
            print(f"Middleware error: {e}")
            return await handler(event, data)


async def log_event(user_id: int, type_: str, payload: str | None = None) -> None:
    """
    Быстрый логгер событий в БД (используется в фичах).
    """
    try:
        async with Session() as s:
            # Находим пользователя по tg_id
            user_result = await s.execute(select(User).where(User.tg_id == user_id))
            user = user_result.scalar()
            
            if user:
                s.add(Event(user_id=user.id, type=type_, payload=payload))
                await s.commit()
            else:
                # Если пользователь не найден, создаем его
                new_user = User(
                    tg_id=user_id,
                    first_name="Unknown",
                    last_name=None,
                    username=None,
                    lang=None
                )
                s.add(new_user)
                await s.commit()
                await s.refresh(new_user)
                
                # Теперь создаем событие
                s.add(Event(user_id=new_user.id, type=type_, payload=payload))
                await s.commit()
    except Exception as e:
        print(f"Log event error: {e}")
