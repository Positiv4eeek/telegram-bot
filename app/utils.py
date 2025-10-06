import re
import os
from typing import Optional
from aiogram import Bot
from urllib.parse import urlparse

_BOT_MENTION: Optional[str] = None

YOUTUBE_HOST_RE = re.compile(r"(?:^|\.)youtube\.com$", re.I)
YOUTU_BE_HOST_RE = re.compile(r"(?:^|\.)youtu\.be$", re.I)
TIKTOK_HOST_RE = re.compile(r"(?:^|\.)tiktok\.com$", re.I)
INSTAGRAM_HOST_RE = re.compile(r"(?:^|\.)instagram\.com$|(?:^|\.)instagr\.am$", re.I)
SPOTIFY_HOST_RE = re.compile(r"(?:^|\.)spotify\.com$", re.I)

async def bot_mention(bot: Bot) -> str:
    global _BOT_MENTION
    if _BOT_MENTION is not None:
        return _BOT_MENTION

    me = await bot.get_me()
    _BOT_MENTION = f"@{me.username}" if me.username else ""
    return _BOT_MENTION

def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""

def is_youtube_shorts(url: str) -> bool:
    try:
        h = _host(url)
        if not (YOUTUBE_HOST_RE.search(h) or YOUTU_BE_HOST_RE.search(h)):
            return False
        return (urlparse(url).path or "").lower().startswith("/shorts/")
    except Exception:
        return False

def is_youtube_regular(url: str) -> bool:
    try:
        h = _host(url)
        if not (YOUTUBE_HOST_RE.search(h) or YOUTU_BE_HOST_RE.search(h)):
            return False
        return not (urlparse(url).path or "").lower().startswith("/shorts/")
    except Exception:
        return False

def is_tiktok(url: str) -> bool:
    try:
        return bool(TIKTOK_HOST_RE.search(_host(url)))
    except Exception:
        return False

def is_instagram_reel(url: str) -> bool:
    try:
        h = _host(url)
        if not INSTAGRAM_HOST_RE.search(h):
            return False
        p = (urlparse(url).path or "").lower()
        return (p.startswith("/reel/") or 
                p.startswith("/reels/") or 
                p.startswith("/p/") or
                "/reel/" in p or 
                "/reels/" in p)
    except Exception:
        return False

def is_spotify(url: str) -> bool:
    try:
        return bool(SPOTIFY_HOST_RE.search(_host(url)))
    except Exception:
        return False

def is_supported_url(url: str) -> bool:
    try:
        return is_tiktok(url) or is_youtube_shorts(url) or is_instagram_reel(url) or is_spotify(url)
    except Exception:
        return False