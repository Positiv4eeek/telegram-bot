import asyncio
import os
import shutil
import tempfile
import subprocess
from dataclasses import dataclass
from typing import Literal
from yt_dlp import YoutubeDL
from app.core.config import settings

@dataclass
class MediaMeta:
    title: str
    uploader: str | None
    duration: int | None
    filesize_approx: int | None
    webpage_url: str
    extractor: str | None

def _base_ytdlp_opts():
    opts = {
        "noprogress": True,
        "quiet": True,
        "restrictfilenames": True,
        "socket_timeout": 15,
        "nocheckcertificate": True,
        "ignoreconfig": True,
        "config_locations": [],
        "geo_bypass": True,
        "no_color": True,
        "concurrent_fragment_downloads": 10,
        "http_chunk_size": 10 * 1024 * 1024,
        "retries": 3,
        "file_access_retries": 3,
        "skip_unavailable_fragments": True,
        "fragment_retries": 3,
        "force_ipv4": True,   # <— помогает при nsig/сетевых глюках
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
            "Referer": "https://www.instagram.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Accept-Encoding": "gzip,deflate",
            "Accept-Charset": "ISO-8859-1,utf-8;q=0.7,*;q=0.7",
        },
        # Дополнительные опции для YouTube Shorts
        "writeinfojson": False,
        "writethumbnail": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
    }
    if settings.ffmpeg_path:
        opts["ffmpeg_location"] = settings.ffmpeg_path
    return opts

def _get_instagram_opts(url: str):
    """Специальные настройки для Instagram"""
    base_opts = _base_ytdlp_opts()
    
    if "instagram.com" in url or "instagr.am" in url:
        # Улучшенные заголовки для Instagram
        base_opts["http_headers"].update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })
        
        # Добавляем cookies если доступны
        if settings.instagram_cookies and os.path.exists(settings.instagram_cookies):
            base_opts["cookiefile"] = settings.instagram_cookies
        
        # Instagram специфичные настройки
        base_opts.update({
            "extractor_args": {
                "instagram": {
                    "login": None,  # Отключаем логин через yt-dlp
                    "password": None,
                }
            },
            "no_check_certificate": True,
            "extractaudio": False,
            "ignoreerrors": False,
            # Дополнительные настройки для обхода ограничений
            "geo_bypass": True,
            "geo_bypass_country": "US",  # Пробуем обойти геоблокировку
            "extractor_retries": 3,
            "fragment_retries": 5,
            "retries": 5,
        })
        
        # Если cookies нет, пробуем альтернативные методы
        if not settings.instagram_cookies or not os.path.exists(settings.instagram_cookies):
            # Добавляем дополнительные заголовки для имитации мобильного приложения
            base_opts["http_headers"].update({
                "User-Agent": "Instagram 219.0.0.12.117 Android (30/11; 420dpi; 1080x2400; samsung; SM-G991B; o1s; qcom; en_US; 371665917)",
                "Accept": "*/*",
                "Accept-Language": "en-US",
                "Accept-Encoding": "gzip, deflate",
                "X-IG-Capabilities": "3brTvw==",
                "X-IG-App-ID": "936619743392459",
                "X-Requested-With": "XMLHttpRequest",
            })
    
    return base_opts

async def extract_info(url: str) -> MediaMeta:
    try:
        loop = asyncio.get_running_loop()
        def _run():
            # Используем специальные настройки для Instagram
            base = {**_get_instagram_opts(url), "skip_download": True}
            try:
                with YoutubeDL({**base, "format": "bestvideo*+bestaudio/best"}) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception:
                with YoutubeDL(base) as ydl:
                    info = ydl.extract_info(url, download=False)
            if info.get("_type") == "playlist" and info.get("entries"):
                for e in info["entries"] or []:
                    if e:
                        info = e
                        break
            return info
        info = await loop.run_in_executor(None, _run)
        return MediaMeta(
            title=info.get("title") or "untitled",
            uploader=info.get("uploader"),
            duration=info.get("duration"),
            filesize_approx=info.get("filesize_approx") or info.get("filesize"),
            webpage_url=info.get("webpage_url") or url,
            extractor=info.get("extractor"),
        )
    except Exception as e:
        raise RuntimeError(f"Failed to extract info: {e}")

async def download_media(
    url: str,
    kind: Literal["video", "audio"] = "video",
    max_mb: int = settings.max_mb,
    prefer_height: int = 1080,
) -> str:
    try:
        loop = asyncio.get_running_loop()
        max_bytes = max_mb * 1024 * 1024

        # Лестница форматов: от «желательного MP4» к «любому рабочему»
        if kind == "video":
            # Специальная обработка для YouTube Shorts
            if "youtube.com/shorts" in url or "youtu.be" in url:
                format_candidates = [
                    # Пробуем разные комбинации для Shorts
                    "bv*+ba/b[ext=mp4]/b",
                    "bv[height<=1080]+ba/b[height<=1080]",
                    "bv[height<=720]+ba/b[height<=720]",
                    "best[height<=1080]/best[height<=720]",
                    "best[ext=mp4]/best",
                    "worst[height>=360]",  # Fallback на минимальное качество
                    "best"
                ]
            else:
                # Специальная обработка для Instagram Reels
                if "instagram.com" in url or "instagr.am" in url:
                    format_candidates = [
                        # Instagram специфичные форматы
                        "best[ext=mp4]/best",
                        "best[height<=1080]/best[height<=720]",
                        f"b[height<={prefer_height}]",
                        "worst[height>=360]",  # Fallback на минимальное качество
                        "best"
                    ]
                else:
                    # TikTok и другие платформы
                    format_candidates = [
                        f"bv*[ext=mp4][vcodec^=avc1][height<={prefer_height}]+ba[ext=m4a]",
                        f"b[ext=mp4][vcodec^=avc1][height<={prefer_height}]",
                        f"b[height<={prefer_height}]",
                        "best[ext=mp4]/best",
                        "best"
                    ]
            postprocessors = []
        else:
            format_candidates = [
                "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best",
                "bestaudio/best"
            ]
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]

        # Используем системную временную директорию
        tmpdir = tempfile.mkdtemp(prefix="telegram-bot-")

        def _convert_to_mp4(src_path: str) -> str:
            try:
                root, ext = os.path.splitext(src_path)
                if ext.lower() == ".mp4":
                    return src_path
                out_path = root + ".__mp4__.mp4"
                cmd = [
                    "ffmpeg", "-y", "-i", src_path,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k",
                    out_path
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                    raise RuntimeError("ffmpeg conversion failed")
                return out_path
            except Exception as e:
                raise RuntimeError(f"FFmpeg conversion failed: {e}")

        def _run():
            try:
                outtmpl = os.path.join(tmpdir, "%(title).80s.%(ext)s")
                last_err = None

                for yformat in format_candidates:
                    # чистим хвосты от предыдущей попытки
                    for root, _, files in os.walk(tmpdir):
                        for f in files:
                            try: 
                                os.remove(os.path.join(root, f))
                            except: 
                                pass

                    opts = {
                        **_get_instagram_opts(url),
                        "outtmpl": outtmpl,
                        "format": yformat,
                        "postprocessors": postprocessors,
                        "max_filesize": max_bytes,
                        "merge_output_format": "mp4",  # Принудительно объединяем в MP4
                        "prefer_ffmpeg": True,  # Предпочитаем FFmpeg для обработки
                        "ignoreerrors": False,  # Не игнорируем ошибки, чтобы попробовать следующий формат
                    }
                    try:
                        with YoutubeDL(opts) as ydl:
                            ydl.extract_info(url, download=True)
                    except Exception as e:
                        last_err = e
                        continue

                    # ищем полученный файл
                    latest, latest_mtime = None, -1.0
                    for root, _, files in os.walk(tmpdir):
                        for f in files:
                            p = os.path.join(root, f)
                            try:
                                mt = os.path.getmtime(p)
                                if mt > latest_mtime:
                                    latest_mtime, latest = mt, p
                            except OSError:
                                pass

                    if not latest:
                        last_err = RuntimeError("No files produced by yt-dlp.")
                        continue

                    # Проверяем, что файл не пустой
                    if os.path.getsize(latest) == 0:
                        try: 
                            os.remove(latest)
                        except: 
                            pass
                        last_err = RuntimeError("The downloaded file is empty")
                        continue

                    if kind == "video":
                        try:
                            latest = _convert_to_mp4(latest)
                        except Exception as e:
                            # Если конвертация не удалась, используем оригинальный файл
                            print(f"Warning: FFmpeg conversion failed: {e}")
                            pass

                    if os.path.getsize(latest) > max_bytes:
                        raise RuntimeError("Produced file is larger than size limit.")

                    # Копируем файл в новую временную директорию, которую не удаляем
                    new_tmpdir = tempfile.mkdtemp(prefix="telegram-bot-final-")
                    final_path = os.path.join(new_tmpdir, os.path.basename(latest))
                    shutil.copy2(latest, final_path)
                    return final_path

                # если ни один формат не взлетел
                raise last_err or RuntimeError("All formats failed")
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        return await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=settings.ytdlp_timeout)
    except Exception as e:
        raise RuntimeError(f"Download failed: {e}")
