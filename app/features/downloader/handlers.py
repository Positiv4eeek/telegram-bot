from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from aiogram.exceptions import TelegramBadRequest

from app.utils import is_supported_url, is_youtube_regular, bot_mention
from app.features.downloader.media import (
    extract_info,
    download_media,
    download_instagram_post_media,
    download_tiktok_images,
    download_tiktok_sound,
    download_spotify_track,
)
from app.core.telemetry import log_event
from app.core.config import settings
from app.core.db import Session
from app.core.models import Download, User

from sqlalchemy import select
import os
import asyncio
import httpx

router = Router()

async def resolve_redirect(url: str) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            r = await client.get(url)
            return str(r.url)
    except Exception:
        return url

@router.message(Command("start"))
async def start(msg: Message):
    await msg.answer(
        "\U0001F3AC Привет! Я бот для скачивания видео и музыки.\n\n"
        "\U0001F4F1 Просто пришли мне ссылку на:\n"
        "• TikTok видео\n"
        "• YouTube Shorts\n"
        "• Instagram Reels\n"
        "• Spotify треки\n"
        "\U0001F3A5 Я автоматически скачаю видео и аудио!\n"
        "\U0001F4CA Статистика: /me\n\n"
        f"\U0001F4E6 Лимит файла: {settings.max_mb} MB"
    )

@router.message(F.text)
async def handle_url(msg: Message):
    text = msg.text.strip()
    if not is_supported_url(text):
        if is_youtube_regular(text):
            return await msg.reply(
                "❌ Поддерживаю только **YouTube Shorts**, а не обычные видео.\n"
                "Попробуйте ссылку на Shorts, TikTok, Instagram Reels или Spotify.",
                parse_mode="Markdown"
            )
        elif any(d in text.lower() for d in ["youtube.com", "youtu.be", "tiktok.com", "instagram.com", "instagr.am", "spotify.com"]):
            return await msg.reply("❌ Не могу обработать эту ссылку. Поддерживаю только TikTok, YouTube Shorts, Instagram Reels и Spotify.")
        else:
            return

    url = text
    if "vm.tiktok.com" in url:
        url = await resolve_redirect(url)

    await log_event(msg.from_user.id, "get", url)
    loading_msg = await msg.reply("🔄 Загружаю медиа, подождите немного...")

    try:
        if "spotify.com" in url:
            await send_spotify_track(msg, url)
        elif "tiktok.com" in url and "/photo/" in url:
            await send_tiktok_album(msg, url, is_photo=True)
        elif ("instagram.com" in url or "instagr.am" in url) and "/p/" in url:
            await send_instagram_post_album(msg, url)
        else:
            meta = await extract_info(url)
            if meta.extractor == "tiktok" and meta.duration is None:
                await send_tiktok_album(msg, url, is_photo=True)
            else:
                await download_and_send_both(msg, url, meta)
    except Exception as e:
        await msg.reply(f"❌ Произошла ошибка: {e}")
    finally:
        try:
            await loading_msg.delete()
        except TelegramBadRequest:
            pass

async def send_spotify_track(msg: Message, url: str):

    try:
        mention = await bot_mention(msg.bot)
        loop = asyncio.get_running_loop()
        track_path = await loop.run_in_executor(None, lambda: download_spotify_track(url))
        
        await msg.answer_audio(
            audio=FSInputFile(track_path), 
            caption=f"🎵 <b>Спасибо что пользуетесь нашим ботом!</b> \n\n🤖 <b>{mention}</b>",
            parse_mode="HTML"
        )
        
        await save_download_stats(msg.from_user.id, url, track_path, "audio")
        await log_event(msg.from_user.id, "download", f"spotify:{url}")
        
    except Exception as e:
        await msg.reply(f"❌ Не удалось скачать трек из Spotify: {e}")
        await log_event(msg.from_user.id, "error", f"spotify_download: {e}")

async def send_tiktok_album(msg: Message, url: str, is_photo: bool = False):
    loop = asyncio.get_running_loop()

    sound_task = loop.run_in_executor(None, lambda: download_tiktok_sound(url, is_photo=is_photo))

    try:
        result = await loop.run_in_executor(None, lambda: download_tiktok_images(url, max_items=None))
        preview = result.get("preview", [])
        originals = result.get("originals", [])

        for grp in [preview[i:i+10] for i in range(0, len(preview), 10)]:
            media_group = [InputMediaPhoto(media=FSInputFile(p)) for p in grp]
            await msg.answer_media_group(media_group)

        if originals:
            await msg.answer("📦 Оригиналы в максимальном качестве, если вы любите чёткость!")
            for i in range(0, len(originals), 10):
                media_group = [InputMediaDocument(media=FSInputFile(p)) for p in originals[i:i+10]]
                await msg.answer_media_group(media_group)

        try:
            mention = await bot_mention(msg.bot)
            sound_path = await asyncio.wait_for(sound_task, timeout=20)
            await save_download_stats(msg.from_user.id, url, sound_path, "audio")
            await msg.answer_audio(audio=FSInputFile(sound_path), caption=f"🎵 <b>Спасибо что пользуетесь нашим ботом!</b> \n\n🤖 <b>{mention}</b>", parse_mode="HTML")
        except Exception as e:
            await msg.answer(f"⚠️ Не удалось получить оригинальный звук: {e}")

        for p in preview + originals:
            await save_download_stats(msg.from_user.id, url, p, "image")
        await log_event(msg.from_user.id, "download", f"tiktok_images:{url}")

    except Exception:
        await msg.reply("❌ Не удалось скачать TikTok-альбом.")

async def send_instagram_post_album(msg: Message, url: str):
    try:
        items = await asyncio.get_running_loop().run_in_executor(None, lambda: download_instagram_post_media(url, max_items=None))
        for grp in [items[i:i+10] for i in range(0, len(items), 10)]:
            media_group = []
            for item in grp:
                media = InputMediaPhoto if item.kind == "image" else InputMediaVideo
                media_group.append(media(media=FSInputFile(item.path)))
            await msg.answer_media_group(media_group)
        for item in items:
            await save_download_stats(msg.from_user.id, url, item.path, item.kind)
        await log_event(msg.from_user.id, "download", f"post_album:{url}")
    except Exception:
        await msg.reply("❌ Не удалось скачать пост Instagram.")

async def download_and_send_both(msg: Message, url: str, meta):
    video_task = asyncio.create_task(download_media(url, kind="video"))
    audio_task = asyncio.create_task(download_media(url, kind="audio"))
    try:
        video_path, audio_path = await asyncio.gather(video_task, audio_task)
        mention = await bot_mention(msg.bot)
        await save_download_stats(msg.from_user.id, url, video_path, "video")
        await save_download_stats(msg.from_user.id, url, audio_path, "audio")
        await msg.answer_video(video=FSInputFile(video_path), caption=f"🎥 <b>Спасибо что пользуетесь нашим ботом!</b> \n\n🤖 <b>{mention}</b>", supports_streaming=True, parse_mode="HTML")
        await msg.answer_audio(audio=FSInputFile(audio_path))
        await log_event(msg.from_user.id, "download", f"both:{url}")
    except Exception as e:
        await msg.reply(f"❌ Ошибка при скачивании: {e}")
        await log_event(msg.from_user.id, "error", f"download: {e}")

async def save_download_stats(user_id: int, url: str, file_path: str, kind: str):
    try:
        size = os.path.getsize(file_path)
        async with Session() as s:
            user_result = await s.execute(select(User).where(User.tg_id == user_id))
            user = user_result.scalar()
            if not user:
                user = User(tg_id=user_id, first_name="Unknown")
                s.add(user)
                await s.commit()
                await s.refresh(user)
            s.add(Download(
                user_id=user.id,
                source=("shorts" if "youtube" in url or "youtu.be" in url else ("reels" if "instagram" in url else "tiktok")),
                url=url,
                title=f"{os.path.basename(file_path)} ({kind})",
                duration_sec=None,
                file_size=size,
                ext=os.path.splitext(file_path)[1].lstrip("."),
            ))
            await s.commit()
    except Exception as e:
        print(f"Ошибка сохранения статистики: {e}")
