from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.db import Session
from app.core.models import MediaCache

async def get_cached_tg_file_id(session: Session, extractor: str, media_id: str, kind: str) -> str | None:
    q = await session.execute(
        select(MediaCache.tg_file_id).where(
            MediaCache.extractor == extractor,
            MediaCache.media_id == media_id,
            MediaCache.kind == kind,
        )
    )
    return q.scalar()

async def upsert_cached_tg_file_id(
    session: Session,
    *,
    source: str,
    extractor: str,
    media_id: str,
    kind: str,
    tg_file_id: str,
    tg_file_unique_id: str
) -> None:
    existing_q = await session.execute(
        select(MediaCache).where(
            MediaCache.extractor == extractor,
            MediaCache.media_id == media_id,
            MediaCache.kind == kind,
        )
    )
    row = existing_q.scalar_one_or_none()
    if row:
        row.tg_file_id = tg_file_id
        row.tg_file_unique_id = tg_file_unique_id
        await session.commit()
        return

    mc = MediaCache(
        source=source,
        extractor=extractor,
        media_id=media_id,
        kind=kind,
        tg_file_id=tg_file_id,
        tg_file_unique_id=tg_file_unique_id,
    )
    session.add(mc)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
