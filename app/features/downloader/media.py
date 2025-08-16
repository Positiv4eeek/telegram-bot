import asyncio
import os
import shutil
import tempfile
import subprocess
from dataclasses import dataclass
from typing import Literal, Optional, List
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

@dataclass
class PostMediaItem:
    kind: Literal["image", "video"]
    path: str

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
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.instagram.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
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
            with YoutubeDL({**base, "format": "bestvideo*+bestaudio/best"}) as ydl:
                info = ydl.extract_info(url, download=False)
                if info.get("_type") == "playlist" and info.get("entries"):
                    for e in info["entries"] or []:
                        if e:
                            return e
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

def download_tiktok_images(url: str, max_items: int | None = 10) -> List[str]:
    if not shutil.which("gallery-dl"):
        raise RuntimeError("gallery-dl is not installed")

    tmpdir = tempfile.mkdtemp(prefix="telegram-bot-gdl-tt-")
    try:
        args = ["gallery-dl", "-D", tmpdir, url]
        res = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        if res.returncode != 0:
            raise RuntimeError("gallery-dl failed to download tiktok images")

        images = []
        for root, _, files in os.walk(tmpdir):
            for f in files:
                p = os.path.join(root, f)
                if os.path.splitext(p)[1].lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    images.append(p)

        if not images:
            raise RuntimeError("No images downloaded")

        # images.sort(key=lambda p: os.path.getmtime(p))
        images.sort(key=lambda p: os.path.basename(p))
        if max_items is not None:
            images = images[:max_items]

        final_dir = tempfile.mkdtemp(prefix="telegram-bot-final-tt-")
        out = []
        for p in images:
            dst = os.path.join(final_dir, os.path.basename(p))
            shutil.copy2(p, dst)
            out.append(dst)

        return out
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def download_instagram_post_media(url: str, max_items: int | None = 10) -> List[PostMediaItem]:
    if not shutil.which("gallery-dl"):
        raise RuntimeError("gallery-dl is not installed")
    if not settings.instagram_cookies or not os.path.exists(settings.instagram_cookies):
        raise RuntimeError("Instagram cookies file is not configured or not found")
    tmpdir = tempfile.mkdtemp(prefix="telegram-bot-gdl-album-")
    try:
        final_dir = tempfile.mkdtemp(prefix="telegram-bot-final-album-")

        try:
            ydl_outtmpl = os.path.join(final_dir, "%(id)s.%(ext)s")
            ydl_opts = {
                **_get_instagram_opts(url),
                "outtmpl": ydl_outtmpl,
                "format": "bestvideo*+bestaudio/best",
                "merge_output_format": "mp4",
                "prefer_ffmpeg": True,
                "quiet": True,
                "noprogress": True,
            }
            with YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        except Exception:
            pass

        args = [
            "gallery-dl",
            "--cookies", settings.instagram_cookies,
            "-D", tmpdir,
            url,
        ]
        res = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            raise RuntimeError("gallery-dl failed to download images")

        media_files: List[tuple[str, float]] = []
        for root, _, files in os.walk(tmpdir):
            for f in files:
                p = os.path.join(root, f)
                try:
                    media_files.append((p, os.path.getmtime(p)))
                except OSError:
                    continue

        if not media_files:
            raise RuntimeError("No media downloaded")

        # media_files.sort(key=lambda t: t[1])
        media_files.sort(key=lambda t: os.path.basename(t[0]))
        if max_items is not None:
            media_files = media_files[:max_items]

        items: List[PostMediaItem] = []

        max_bytes = settings.max_mb * 1024 * 1024
        image_exts = {".jpg", ".jpeg", ".png", ".webp"}
        video_exts = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

        def convert_to_mp4_if_needed(src_path: str) -> str:
            root, ext = os.path.splitext(src_path)
            if ext.lower() == ".mp4":
                return src_path
            out_path = os.path.join(final_dir, os.path.basename(root) + ".mp4")
            cmd = [
                "ffmpeg", "-y", "-i", src_path,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                out_path,
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                raise RuntimeError("ffmpeg conversion failed")
            return out_path

        existing_video_names = set()
        for f in os.listdir(final_dir):
            ext = os.path.splitext(f)[1].lower()
            if ext in video_exts:
                existing_video_names.add(os.path.splitext(f)[0])

        for p, _ in media_files:
            ext = os.path.splitext(p)[1].lower()
            if ext in image_exts:
                dst = os.path.join(final_dir, os.path.basename(p))
                shutil.copy2(p, dst)
                if os.path.getsize(dst) > 0 and os.path.getsize(dst) <= max_bytes:
                    items.append(PostMediaItem("image", dst))
            elif ext in video_exts:
                base = os.path.splitext(os.path.basename(p))[0]
                if base in existing_video_names:
                    continue
                try:
                    processed = convert_to_mp4_if_needed(p)
                except Exception:
                    processed = p
                dst = os.path.join(final_dir, os.path.basename(processed))
                if processed != dst:
                    shutil.copy2(processed, dst)
                if os.path.getsize(dst) > 0 and os.path.getsize(dst) <= max_bytes:
                    items.append(PostMediaItem("video", dst))

        if not items:
            raise RuntimeError("No media found after processing")

        return items
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

async def download_media(
    url: str,
    kind: Literal["video", "audio", "image"] = "video",
    max_mb: int = settings.max_mb,
    prefer_height: int = 1080,
) -> str:
    try:
        loop = asyncio.get_running_loop()
        max_bytes = max_mb * 1024 * 1024

        format_candidates = [
            "bv*+ba/b[ext=mp4]/b",
            "bv[height<=1080]+ba/b[height<=1080]",
            "bv[height<=720]+ba/b[height<=720]",
            "best[height<=1080]/best[height<=720]",
            "best[ext=mp4]/best",
            "worst[height>=360]",
            "best"
        ] if kind == "video" else [
            "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best",
            "bestaudio/best"
        ]

        postprocessors = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }] if kind == "audio" else []

        tmpdir = tempfile.mkdtemp(prefix="telegram-bot-")

        def _convert_to_mp4(src_path: str) -> str:
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

        def _run():
            outtmpl = os.path.join(tmpdir, "%(title).80s.%(ext)s")
            last_err = None

            for yformat in format_candidates:
                for root, _, files in os.walk(tmpdir):
                    for f in files:
                        try: os.remove(os.path.join(root, f))
                        except: pass

                opts = {
                    **_get_instagram_opts(url),
                    "outtmpl": outtmpl,
                    "postprocessors": postprocessors,
                    "max_filesize": max_bytes,
                    "ignoreerrors": False,
                }

                if yformat:
                    opts["format"] = yformat
                if kind == "video":
                    opts["merge_output_format"] = "mp4"
                    opts["prefer_ffmpeg"] = True

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

                if not latest or os.path.getsize(latest) == 0:
                    last_err = RuntimeError("No valid media file downloaded")
                    continue

                if kind == "video":
                    try:
                        latest = _convert_to_mp4(latest)
                    except Exception:
                        pass

                if os.path.getsize(latest) > max_bytes:
                    raise RuntimeError("Produced file is larger than size limit.")

                final_path = os.path.join(tempfile.mkdtemp(prefix="telegram-bot-final-"), os.path.basename(latest))
                shutil.copy2(latest, final_path)
                return final_path

            raise last_err or RuntimeError("All formats failed")

        return await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=settings.ytdlp_timeout)
    except Exception as e:
        raise RuntimeError(f"Download failed: {e}")
