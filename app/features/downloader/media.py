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
        "force_ipv4": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
            "Referer": "https://www.instagram.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Accept-Encoding": "gzip,deflate",
            "Accept-Charset": "ISO-8859-1,utf-8;q=0.7,*;q=0.7",
        },
        "writeinfojson": False,
        "writethumbnail": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
    }
    if settings.ffmpeg_path:
        opts["ffmpeg_location"] = settings.ffmpeg_path
    return opts

def _get_instagram_opts(url: str):
    base_opts = _base_ytdlp_opts()
    if "instagram.com" in url or "instagr.am" in url:
        if not settings.instagram_cookies or not os.path.exists(settings.instagram_cookies):
            raise RuntimeError("Instagram cookies file is not configured or not found")
        base_opts["cookiefile"] = settings.instagram_cookies
        base_opts.update({
            "no_check_certificate": True,
            "ignoreerrors": False,
        })
    return base_opts

async def extract_info(url: str) -> MediaMeta:
    try:
        loop = asyncio.get_running_loop()
        def _run():
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
    kind: Literal["video", "audio", "image"] = "video",
    max_mb: int = settings.max_mb,
    prefer_height: int = 1080,
) -> str:
    try:
        loop = asyncio.get_running_loop()
        max_bytes = max_mb * 1024 * 1024

        if kind == "video":
            if "youtube.com/shorts" in url or "youtu.be" in url:
                format_candidates = [
                    "bv*+ba/b[ext=mp4]/b",
                    "bv[height<=1080]+ba/b[height<=1080]",
                    "bv[height<=720]+ba/b[height<=720]",
                    "best[height<=1080]/best[height<=720]",
                    "best[ext=mp4]/best",
                    "worst[height>=360]",
                    "best"
                ]
            else:
                if "instagram.com" in url or "instagr.am" in url:
                    format_candidates = [
                        "best[ext=mp4]/best",
                        "best[height<=1080]/best[height<=720]",
                        f"b[height<={prefer_height}]",
                        "worst[height>=360]",
                        "best"
                    ]
                else:
                    format_candidates = [
                        f"bv*[ext=mp4][vcodec^=avc1][height<={prefer_height}]+ba[ext=m4a]",
                        f"b[ext=mp4][vcodec^=avc1][height<={prefer_height}]",
                        f"b[height<={prefer_height}]",
                        "best[ext=mp4]/best",
                        "best"
                    ]
            postprocessors = []
        elif kind == "audio":
            format_candidates = [
                "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best",
                "bestaudio/best"
            ]
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:  # image
            format_candidates = [
                "b/best",
                "best"
            ]
            postprocessors = []

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
                        "merge_output_format": "mp4",
                        "prefer_ffmpeg": True,
                        "ignoreerrors": False,
                    }
                    try:
                        with YoutubeDL(opts) as ydl:
                            ydl.extract_info(url, download=True)
                    except Exception as e:
                        last_err = e
                        continue

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
                            pass

                    if os.path.getsize(latest) > max_bytes:
                        raise RuntimeError("Produced file is larger than size limit.")

                    new_tmpdir = tempfile.mkdtemp(prefix="telegram-bot-final-")
                    final_path = os.path.join(new_tmpdir, os.path.basename(latest))
                    shutil.copy2(latest, final_path)
                    return final_path

                raise last_err or RuntimeError("All formats failed")
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        return await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=settings.ytdlp_timeout)
    except Exception as e:
        raise RuntimeError(f"Download failed: {e}")
