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

from app.core.antispam import (
    check_rate, get_user_lock, get_inflight_task, set_inflight_task,
    enqueue_or_fail, dequeue, RateLimitError, QueueOverflowError
)

from app.core.telemetry import log_event
from app.core.config import settings
from app.core.db import Session
from app.core.models import Download, User
from app.core.cache import get_cached_tg_file_id, upsert_cached_tg_file_id

from sqlalchemy import select
import os
import asyncio
import httpx
import re

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
    text = (msg.text or "").strip()

    # Проверка: если обычное YouTube-видео, разрешаем только администраторам
    if is_youtube_regular(text):
        if msg.from_user.id not in settings.admin_ids:
            return await msg.reply(
                "❌ Поддерживаю только **YouTube Shorts**, а не обычные видео.\n"
                "Попробуйте ссылку на Shorts, TikTok, Instagram Reels или Spotify.",
                parse_mode="Markdown",
            )
    elif not is_supported_url(text):
        if any(d in text.lower() for d in [
            "youtube.com", "youtu.be", "tiktok.com", "instagram.com", "instagr.am", "spotify.com"
        ]):
            return await msg.reply("❌ Не могу обработать эту ссылку. Поддерживаю только TikTok, YouTube Shorts, Instagram Reels и Spotify.")
        else:
            return

    url = text
    if "vm.tiktok.com" in url:
        url = await resolve_redirect(url)

    try:
        check_rate(msg.from_user.id)             # бросит RateLimitError при нарушении
        await enqueue_or_fail(msg.from_user.id)  # ограничим количество параллельных задач в очереди
    except RateLimitError as e:
        return await msg.reply(f"🚦 {e}")
    except QueueOverflowError as e:
        return await msg.reply(f"⏳ {e}")

    inflight = get_inflight_task(msg.from_user.id, url)
    if inflight:
        dequeue(msg.from_user.id)
        return await msg.reply("♻️ Эта ссылка уже обрабатывается, дождитесь результата.")

    user_lock = get_user_lock(msg.from_user.id)
    async with user_lock:
        set_inflight_task(msg.from_user.id, url, asyncio.current_task())

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
            dequeue(msg.from_user.id)

async def send_spotify_track(msg: Message, url: str):
    m = re.search(r"spotify\.com/track/([A-Za-z0-9]+)", url)
    track_id = m.group(1) if m else url
    extractor, source = "spotify", "spotify"

    try:
        async with Session() as s:
            cached = await get_cached_tg_file_id(s, extractor, track_id, "audio")
        if cached:
            mention = await bot_mention(msg.bot)
            await msg.answer_audio(audio=cached,
                                   caption=f"🎵 <b>Спасибо что пользуетесь нашим ботом!</b> \n\n🤖 <b>{mention}</b>",
                                   parse_mode="HTML")
            return

        mention = await bot_mention(msg.bot)
        loop = asyncio.get_running_loop()
        track_path = await loop.run_in_executor(None, lambda: download_spotify_track(url))

        sent = await msg.answer_audio(
            audio=FSInputFile(track_path),
            caption=f"🎵 <b>Спасибо что пользуетесь нашим ботом!</b> \n\n🤖 <b>{mention}</b>",
            parse_mode="HTML",
        )

        await save_download_stats(msg.from_user.id, url, track_path, "audio")
        async with Session() as s:
            await upsert_cached_tg_file_id(
                s, source=source, extractor=extractor, media_id=track_id, kind="audio",
                tg_file_id=sent.audio.file_id, tg_file_unique_id=sent.audio.file_unique_id
            )
        try: os.remove(track_path)
        except OSError: pass

        await log_event(msg.from_user.id, "download", f"spotify:{url}")

    except Exception as e:
        await msg.reply(f"❌ Не удалось скачать трек из Spotify: {e}")
        await log_event(msg.from_user.id, "error", f"spotify_download: {e}")

def _tiktok_post_id(url: str) -> str:
    m = re.search(r"/(?:photo|video)/(\d+)", url)
    return m.group(1) if m else url

async def send_tiktok_album(msg: Message, url: str, is_photo: bool = False):
    loop = asyncio.get_running_loop()
    post_id = _tiktok_post_id(url)
    source, extractor = "tiktok", "tiktok"

    sound_task = loop.run_in_executor(None, lambda: download_tiktok_sound(url, is_photo=is_photo))

    try:
        result = await loop.run_in_executor(None, lambda: download_tiktok_images(url, max_items=None))
        preview = result.get("preview", [])
        originals = result.get("originals", [])
    except Exception:
        return await msg.reply("❌ Не удалось скачать TikTok-альбом.")

    async with Session() as s:
        for grp in [preview[i:i+10] for i in range(0, len(preview), 10)]:
            send_items = []
            for p in grp:
                media_id = f"{post_id}:img:{os.path.basename(p)}"
                fid = await get_cached_tg_file_id(s, extractor, media_id, "image")
                if fid:
                    send_items.append(("cached", fid, p, media_id))
                else:
                    send_items.append(("file", p, p, media_id))

            media_group = []
            for kind, ref, _, _ in send_items:
                if kind == "cached":
                    media_group.append(InputMediaPhoto(media=ref))
                else:
                    media_group.append(InputMediaPhoto(media=FSInputFile(ref)))

            msgs = await msg.answer_media_group(media_group)

            for sent, (kind, _ref, orig_path, media_id) in zip(msgs, send_items):
                if kind == "file" and sent.photo:
                    fid = sent.photo[-1].file_id
                    fuid = sent.photo[-1].file_unique_id
                    await upsert_cached_tg_file_id(
                        s, source=source, extractor=extractor,
                        media_id=media_id, kind="image",
                        tg_file_id=fid, tg_file_unique_id=fuid
                    )
                    try: os.remove(orig_path)
                    except OSError: pass

    if originals:
        await msg.answer("📦 Оригиналы в максимальном качестве, если вы любите чёткость!")
        async with Session() as s:
            for grp in [originals[i:i+10] for i in range(0, len(originals), 10)]:
                send_items = []
                for p in grp:
                    media_id = f"{post_id}:orig:{os.path.basename(p)}"
                    fid = await get_cached_tg_file_id(s, extractor, media_id, "document")
                    if fid:
                        send_items.append(("cached", fid, p, media_id))
                    else:
                        send_items.append(("file", p, p, media_id))

                media_group = []
                for kind, ref, _, _ in send_items:
                    if kind == "cached":
                        media_group.append(InputMediaDocument(media=ref))
                    else:
                        media_group.append(InputMediaDocument(media=FSInputFile(ref)))

                msgs = await msg.answer_media_group(media_group)

                for sent, (kind, _ref, orig_path, media_id) in zip(msgs, send_items):
                    if kind == "file" and sent.document:
                        fid = sent.document.file_id
                        fuid = sent.document.file_unique_id
                        await upsert_cached_tg_file_id(
                            s, source=source, extractor=extractor,
                            media_id=media_id, kind="document",
                            tg_file_id=fid, tg_file_unique_id=fuid
                        )
                        try: os.remove(orig_path)
                        except OSError: pass

    try:
        sound_key = f"{post_id}:sound"
        async with Session() as s:
            cached = await get_cached_tg_file_id(s, extractor, sound_key, "audio")

        if cached:
            await msg.answer_audio(audio=cached)
        else:
            mention = await bot_mention(msg.bot)
            sound_path = await asyncio.wait_for(sound_task, timeout=20)
            sent = await msg.answer_audio(
                audio=FSInputFile(sound_path),
                caption=f"🎵 <b>Спасибо что пользуетесь нашим ботом!</b> \n\n🤖 <b>{mention}</b>",
                parse_mode="HTML",
            )
            async with Session() as s:
                await upsert_cached_tg_file_id(
                    s, source=source, extractor=extractor,
                    media_id=sound_key, kind="audio",
                    tg_file_id=sent.audio.file_id, tg_file_unique_id=sent.audio.file_unique_id
                )
            try: os.remove(sound_path)
            except OSError: pass
    except Exception as e:
        await msg.answer(f"⚠️ Не удалось получить оригинальный звук: {e}")

    for p in preview + originals:
        await save_download_stats(msg.from_user.id, url, p, "image")
    await log_event(msg.from_user.id, "download", f"tiktok_images:{url}")

def _instagram_post_id(url: str) -> str:
    m = re.search(r"/p/([^/?#]+)/?", url)
    return m.group(1) if m else url

async def send_instagram_post_album(msg: Message, url: str):
    post_id = _instagram_post_id(url)
    source, extractor = "reels", "instagram"

    try:
        items = await asyncio.get_running_loop().run_in_executor(None, lambda: download_instagram_post_media(url, max_items=None))
    except Exception:
        return await msg.reply("❌ Не удалось скачать пост Instagram.")

    async with Session() as s:
        for grp in [items[i:i+10] for i in range(0, len(items), 10)]:
            send_items = []
            for item in grp:
                kind = "image" if item.kind == "image" else "video"
                media_id = f"{post_id}:{os.path.basename(item.path)}"
                fid = await get_cached_tg_file_id(s, extractor, media_id, kind)
                if fid:
                    send_items.append(("cached", kind, fid, item.path, media_id))
                else:
                    send_items.append(("file", kind, item.path, item.path, media_id))

            media_group = []
            for kind_src, kind, ref, _orig_path, _mid in send_items:
                if kind == "image":
                    media_group.append(InputMediaPhoto(media=ref if kind_src == "cached" else FSInputFile(ref)))
                else:
                    media_group.append(InputMediaVideo(media=ref if kind_src == "cached" else FSInputFile(ref)))

            msgs = await msg.answer_media_group(media_group)

            for sent, (kind_src, kind, _ref, orig_path, media_id) in zip(msgs, send_items):
                if kind_src != "file":
                    continue
                if kind == "image" and sent.photo:
                    fid, fuid = sent.photo[-1].file_id, sent.photo[-1].file_unique_id
                elif kind == "video" and sent.video:
                    fid, fuid = sent.video.file_id, sent.video.file_unique_id
                else:
                    continue

                await upsert_cached_tg_file_id(
                    s, source=source, extractor=extractor,
                    media_id=media_id, kind=kind,
                    tg_file_id=fid, tg_file_unique_id=fuid
                )
                try: os.remove(orig_path)
                except OSError: pass

    for item in items:
        await save_download_stats(msg.from_user.id, url, item.path, item.kind)
    await log_event(msg.from_user.id, "download", f"post_album:{url}")

async def download_and_send_both(msg: Message, url: str, meta):
    source = ("shorts" if "youtu" in url else ("reels" if "insta" in url else "tiktok"))
    extractor = (meta.extractor or "unknown")
    media_id = (meta.id or meta.webpage_url)

    mention = await bot_mention(msg.bot)
    
    async with Session() as s:
        cached_video_id = await get_cached_tg_file_id(s, extractor, media_id, "video")
        cached_audio_id = await get_cached_tg_file_id(s, extractor, media_id, "audio")

    tasks: dict[str, asyncio.Task] = {}
    if not cached_video_id:
        tasks["video"] = asyncio.create_task(download_media(url, kind="video"))
    if not cached_audio_id:
        tasks["audio"] = asyncio.create_task(download_media(url, kind="audio"))

    sent_v = None
    sent_a = None

    try:
        if cached_video_id:
            sent_v = await msg.answer_video(
                video=cached_video_id,
                caption=f"🎥 <b>Спасибо что пользуетесь нашим ботом!</b> \n\n🤖 <b>{mention}</b>",
                supports_streaming=True,
                parse_mode="HTML",
            )
        else:
            video_path = await tasks["video"]
            try:
                sent_v = await msg.answer_video(
                    video=FSInputFile(video_path),
                    caption=f"🎥 <b>Спасибо что пользуетесь нашим ботом!</b> \n\n🤖 <b>{mention}</b>",
                    supports_streaming=True,
                    parse_mode="HTML",
                )
                await save_download_stats(msg.from_user.id, url, video_path, "video")
                async with Session() as s:
                    await upsert_cached_tg_file_id(
                        s,
                        source=source,
                        extractor=extractor,
                        media_id=media_id,
                        kind="video",
                        tg_file_id=sent_v.video.file_id,
                        tg_file_unique_id=sent_v.video.file_unique_id,
                    )
            finally:
                try:
                    os.remove(video_path)
                except Exception:
                    pass

        if cached_audio_id:
            sent_a = await msg.answer_audio(audio=cached_audio_id)
        else:
            audio_path = await tasks["audio"]
            try:
                sent_a = await msg.answer_audio(audio=FSInputFile(audio_path))
                await save_download_stats(msg.from_user.id, url, audio_path, "audio")
                async with Session() as s:
                    await upsert_cached_tg_file_id(
                        s,
                        source=source,
                        extractor=extractor,
                        media_id=media_id,
                        kind="audio",
                        tg_file_id=sent_a.audio.file_id,
                        tg_file_unique_id=sent_a.audio.file_unique_id,
                    )
            finally:
                try:
                    os.remove(audio_path)
                except Exception:
                    pass

        await log_event(msg.from_user.id, "download", f"both:{url}")

    except Exception as e:
        await msg.reply(f"❌ Ошибка при скачивании: {e}")
        await log_event(msg.from_user.id, "error", f"download: {e}")

async def save_download_stats(user_id: int, url: str, file_path: str, kind: str):
    try:
        size = os.path.getsize(file_path) if os.path.exists(file_path) else None
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
