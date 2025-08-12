from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")

    max_mb: int = int(os.getenv("MAX_MB", "48"))
    trim_minutes: int = int(os.getenv("TRIM_MINUTES", "2"))
    ytdlp_timeout: int = int(os.getenv("YTDLP_TIMEOUT", "180"))

    ffmpeg_path: str | None = (os.getenv("FFMPEG_PATH") or "").strip() or None
    instagram_cookies: str | None = (os.getenv("INSTAGRAM_COOKIES") or "").strip() or None

    def __post_init__(self):
        if not self.bot_token:
            raise ValueError("BOT_TOKEN не установлен! Создайте файл .env с вашим токеном бота.")

settings = Settings()
