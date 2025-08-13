from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from app.utils import is_supported_url, is_youtube_regular, fmt_bytes, fmt_seconds
from app.features.downloader.media import extract_info, download_media, download_instagram_post_media, PostMediaItem, download_tiktok_images
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
                return

        url = text
        await log_event(msg.from_user.id, "get", url)

        

        try:
            meta = None
            try:
                meta = await extract_info(url)
            except Exception as e:
                if "tiktok.com" in url:
                    try:
                        pics = await asyncio.get_running_loop().run_in_executor(None, lambda: download_tiktok_images(url, max_items=10))
                        from aiogram.types import InputMediaPhoto
                        media_group = [InputMediaPhoto(media=FSInputFile(p)) for p in pics]
                        batches = [media_group[i:i+10] for i in range(0, len(media_group), 10)]
                        for grp in batches:
                            for attempt in range(2):
                                try:
                                    await msg.answer_media_group(grp)
                                    break
                                except Exception:
                                    if attempt == 0:
                                        await asyncio.sleep(1.0)
                                        continue
                                    raise
                        for p in pics:
                            await save_download_stats(msg.from_user.id, url, p, "image")
                        try:
                            import shutil
                            for p in pics:
                                shutil.rmtree(os.path.dirname(p), ignore_errors=True)
                        except:
                            pass
                        await log_event(msg.from_user.id, "download", f"tiktok_images:{url}")
                        return
                    except Exception:
                        pass
                raise

            is_instagram_post_image = (
                ("instagram.com" in url or "instagr.am" in url)
                and "/p/" in url
            )

            if is_instagram_post_image:
                items = await asyncio.get_running_loop().run_in_executor(None, lambda: download_instagram_post_media(url, max_items=10))
                from aiogram.types import InputMediaPhoto, InputMediaVideo
                media_group = []
                for item in items:
                    if item.kind == "image":
                        media_group.append(InputMediaPhoto(media=FSInputFile(item.path)))
                    else:
                        media_group.append(InputMediaVideo(media=FSInputFile(item.path)))

                batches = [media_group[i:i+10] for i in range(0, len(media_group), 10)]
                for grp in batches:
                    for attempt in range(2):
                        try:
                            await msg.answer_media_group(grp)
                            break
                        except Exception:
                            if attempt == 0:
                                await asyncio.sleep(1.0)
                                continue
                            raise

                for item in items:
                    await save_download_stats(msg.from_user.id, url, item.path, item.kind)

                try:
                    import shutil, os
                    for item in items:
                        shutil.rmtree(os.path.dirname(item.path), ignore_errors=True)
                except:
                    pass

                await log_event(msg.from_user.id, "download", f"post_album:{url}")
            else:
                if "tiktok.com" in url:
                    try:
                        pics = await asyncio.get_running_loop().run_in_executor(None, lambda: download_tiktok_images(url, max_items=10))
                        from aiogram.types import InputMediaPhoto
                        media_group = [InputMediaPhoto(media=FSInputFile(p)) for p in pics]
                        batches = [media_group[i:i+10] for i in range(0, len(media_group), 10)]
                        for grp in batches:
                            for attempt in range(2):
                                try:
                                    await msg.answer_media_group(grp)
                                    break
                                except Exception:
                                    if attempt == 0:
                                        await asyncio.sleep(1.0)
                                        continue
                                    raise
                        for p in pics:
                            await save_download_stats(msg.from_user.id, url, p, "image")
                        try:
                            import shutil
                            for p in pics:
                                shutil.rmtree(os.path.dirname(p), ignore_errors=True)
                        except:
                            pass
                        await log_event(msg.from_user.id, "download", f"tiktok_images:{url}")
                        return
                    except Exception:
                        pass
                await download_and_send_both(msg, url, meta)
        except Exception as e:
            await log_event(msg.from_user.id, "error", f"extract: {e}")
            await msg.reply(f"❌ Ошибка: {format_error_message(str(e))}")
        
    except Exception as e:
        await msg.reply(f"❌ Произошла ошибка: {e}")

async def download_and_send_both(msg: Message, url: str, meta):
    """Скачивает и отправляет видео и аудио"""
    try:
        video_task = asyncio.create_task(download_media(url, kind="video"))
        audio_task = asyncio.create_task(download_media(url, kind="audio"))
        
        try:
            video_path, audio_path = await asyncio.gather(video_task, audio_task)
            
            await save_download_stats(msg.from_user.id, url, video_path, "video")
            await save_download_stats(msg.from_user.id, url, audio_path, "audio")
            
            await msg.answer_video(
                video=FSInputFile(video_path),
                caption=f"🎥 {meta.title}"
            )
            await msg.answer_audio(
                audio=FSInputFile(audio_path)
            )
            
            try:
                import shutil
                video_dir = os.path.dirname(video_path)
                audio_dir = os.path.dirname(audio_path)
                shutil.rmtree(video_dir, ignore_errors=True)
                if video_dir != audio_dir:
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
            user_result = await s.execute(select(User).where(User.tg_id == user_id))
            user = user_result.scalar()
            
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
