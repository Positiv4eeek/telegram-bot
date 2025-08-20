from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, BigInteger, DateTime, ForeignKey, Text, Index
from datetime import datetime, timedelta, timezone
from app.core.db import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    lang: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    downloads: Mapped[list["Download"]] = relationship(back_populates="user", cascade="all,delete-orphan")
    events: Mapped[list["Event"]] = relationship(back_populates="user", cascade="all,delete-orphan")

class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="events")

class Download(Base):
    __tablename__ = "downloads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    source: Mapped[str] = mapped_column(String(16))  # tiktok|shorts|reels
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    file_size: Mapped[int | None] = mapped_column(Integer)
    ext: Mapped[str | None] = mapped_column(String(8))

    user: Mapped["User"] = relationship(back_populates="downloads")

class Token(Base):
    __tablename__ = "tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ns: Mapped[str] = mapped_column(String(32), index=True)       # namespace (e.g. "dl")
    token: Mapped[str] = mapped_column(String(64), unique=True)   # короткий идентификатор
    value: Mapped[str] = mapped_column(Text)                      # храним URL/данные
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

Index("ix_tokens_ns_token", Token.ns, Token.token, unique=True)
