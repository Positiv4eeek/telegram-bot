from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from app.utils import is_supported_url, is_youtube_regular, fmt_bytes, fmt_seconds
from app.features.downloader.media import extract_info, download_media
from app.core.telemetry import log_event
from app.core.config import settings
from app.core.db import Session
from app.core.models import Download, User
from sqlalchemy import select
import os
import asyncio

router = Router()

@router.message(Command("start"))
async def start(msg: Message):
    await msg.answer(
        "🎬 Привет! Я бот для скачивания видео.\n\n"
        "📱 Просто пришли мне ссылку на:\n"
        "• TikTok видео\n"
        "• YouTube Shorts\n"
        "• Instagram Reels\n"
        "🎥 Я автоматически скачаю видео и аудио!\n"
        "📊 Статистика: /me\n\n"
        f"📦 Лимит файла: {settings.max_mb} MB"
    )

@router.message(F.text)
async def handle_url(msg: Message):
    """Обрабатывает любое сообщение с URL"""
    try:
        text = msg.text.strip()
        
        # Проверяем, содержит ли сообщение поддерживаемый URL
        if not is_supported_url(text):
            if is_youtube_regular(text):
                return await msg.reply(
                    "❌ Поддерживаю только **YouTube Shorts**, а не обычные видео.\n"
                    "Попробуйте ссылку на Shorts, TikTok или Instagram Reels.",
                    parse_mode="Markdown"
                )
            elif any(domain in text.lower() for domain in ['youtube.com', 'youtu.be', 'tiktok.com', 'instagram.com', 'instagr.am']):
                return await msg.reply("❌ Не могу обработать эту ссылку. Поддерживаю только TikTok, YouTube Shorts и Instagram Reels.")
            else:
                # Если это не похоже на ссылку, игнорируем
                return

        url = text
        await log_event(msg.from_user.id, "get", url)
        
        # Сразу скачиваем и отправляем без промежуточных сообщений
        try:
            meta = await extract_info(url)

            is_instagram_post_image = (
                ("instagram.com" in url or "instagr.am" in url)
                and "/p/" in url
            )

            if is_instagram_post_image:
                image_path = await download_media(url, kind="image")
                await msg.answer_photo(photo=FSInputFile(image_path), caption=f"🖼️ {meta.title}")
                await save_download_stats(msg.from_user.id, url, image_path, "image")
                try:
                    import shutil, os
                    shutil.rmtree(os.path.dirname(image_path), ignore_errors=True)
                except:
                    pass
                await log_event(msg.from_user.id, "download", f"image:{url}")
            else:
                await download_and_send_both(msg, url, meta)
        except Exception as e:
            await log_event(msg.from_user.id, "error", f"extract: {e}")
            await msg.reply(f"❌ Ошибка: {format_error_message(str(e))}")
        
    except Exception as e:
        await msg.reply(f"❌ Произошла ошибка: {e}")

async def download_and_send_both(msg: Message, url: str, meta):
    """Скачивает и отправляет видео и аудио"""
    try:
        # Создаем задачи для параллельного скачивания
        video_task = asyncio.create_task(download_media(url, kind="video"))
        audio_task = asyncio.create_task(download_media(url, kind="audio"))
        
        try:
            # Ждем завершения обеих задач
            video_path, audio_path = await asyncio.gather(video_task, audio_task)
            
            # Сохраняем статистику
            await save_download_stats(msg.from_user.id, url, video_path, "video")
            await save_download_stats(msg.from_user.id, url, audio_path, "audio")
            
            # Отправляем видео и аудио раздельными сообщениями
            await msg.answer_video(
                video=FSInputFile(video_path),
                caption=f"🎥 {meta.title}"
            )
            await msg.answer_audio(
                audio=FSInputFile(audio_path)
            )
            
            # Удаляем временные директории после отправки
            try:
                import shutil
                # Удаляем директории с файлами
                video_dir = os.path.dirname(video_path)
                audio_dir = os.path.dirname(audio_path)
                shutil.rmtree(video_dir, ignore_errors=True)
                if video_dir != audio_dir:  # Если разные директории
                    shutil.rmtree(audio_dir, ignore_errors=True)
            except:
                pass
            
            await log_event(msg.from_user.id, "download", f"both:{url}")
            
        except Exception as e:
            error_msg = format_error_message(str(e))
            await msg.reply(f"❌ {error_msg}")
            await log_event(msg.from_user.id, "error", f"download: {e}")
            
    except Exception as e:
        await msg.reply(f"❌ Ошибка: {e}")

async def save_download_stats(user_id: int, url: str, file_path: str, kind: str):
    """Сохраняет статистику скачивания"""
    try:
        size = os.path.getsize(file_path)
        
        async with Session() as s:
            # Находим пользователя по tg_id
            user_result = await s.execute(select(User).where(User.tg_id == user_id))
            user = user_result.scalar()
            
            # Если пользователь не найден, создаем его
            if not user:
                user = User(
                    tg_id=user_id,
                    first_name="Unknown",
                    last_name=None,
                    username=None,
                    lang=None
                )
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

def format_error_message(error_msg: str) -> str:
    """Форматирует сообщения об ошибках"""
    if "Requested format is not available" in error_msg or "format not available" in error_msg.lower():
        return "Формат видео недоступен. Попробуйте другую ссылку."
    elif "No suitable formats" in error_msg:
        return "Подходящий формат не найден. Возможно, видео недоступно."
    elif "Download failed" in error_msg:
        return "Ошибка загрузки. Проверьте ссылку."
    elif "ffmpeg" in error_msg.lower():
        return "Ошибка конвертации видео."
    elif "Private video" in error_msg or "Video unavailable" in error_msg:
        return "Видео недоступно или приватное."
    elif "age-restricted" in error_msg.lower():
        return "Видео имеет возрастные ограничения."
    elif "login required" in error_msg.lower() or "authentication" in error_msg.lower():
        return "Требуется авторизация в Instagram."
    elif "instagram" in error_msg.lower() and ("unavailable" in error_msg.lower() or "not found" in error_msg.lower()):
        return "Instagram Reel недоступен. Возможно, аккаунт приватный."
    elif "HTTP Error 429" in error_msg or "Too Many Requests" in error_msg:
        return "Слишком много запросов. Попробуйте позже."
    else:
        return error_msg
