import glob
import os
import random
import re
import shutil
import tempfile
from urllib.parse import quote, urlparse

from flask import Flask, jsonify, render_template, request, send_file
import requests
import yt_dlp
from yt_dlp.utils import DownloadError


app = Flask(__name__)


# =========================================================
# CONFIG
# =========================================================

MAX_MB = int(os.getenv("MAX_MB", "300"))
MAX_BYTES = MAX_MB * 1024 * 1024

ALLOWED_HOSTS = (
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "fb.com",
    "twitter.com",
    "x.com",
    "t.co",
)

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
]

MIME = {
    "mp4": "video/mp4",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "webm": "video/webm",
    "mkv": "video/x-matroska",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
}


# =========================================================
# FFMPEG
# =========================================================

def find_ffmpeg():
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_path and os.path.exists(ffmpeg_path):
            return ffmpeg_path
    except Exception:
        pass

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    return None

FFMPEG = find_ffmpeg()


# =========================================================
# UTILITIES
# =========================================================

def browser_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Mode": "navigate",
    }


def clean_youtube_url(raw_url):
    """Playlist and Mix parameters cleaning (e.g. &list=RD...)"""
    if "youtube.com" in raw_url or "youtu.be" in raw_url:
        vid_match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', raw_url)
        if vid_match:
            return f"https://www.youtube.com/watch?v={vid_match.group(1)}"
    return raw_url


def valid_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https"):
            return False
        return any(
            host == allowed or host.endswith("." + allowed)
            for allowed in ALLOWED_HOSTS
        )
    except Exception:
        return False


def fallback_download(url, fmt="mp4"):
    """YouTube block hone par Cobalt Backup API se video url fetch karna"""
    api_url = "https://api.cobalt.tools/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    
    payload = {
        "url": url,
        "videoQuality": "720",
        "downloadMode": "audio" if fmt == "mp3" else "auto"
    }
    
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        data = res.json()
        status = data.get("status")
        
        if status in ("redirect", "stream", "tunnel", "success"):
            return data.get("url")
        elif status == "picker":
            picker_items = data.get("picker", [])
            if picker_items and "url" in picker_items[0]:
                return picker_items[0]["url"]
    except Exception as e:
        print("Fallback Error:", e)
        
    return None


# =========================================================
# YT-DLP OPTIONS
# =========================================================

def build_opts(tmpdir, fmt, height):
    opts = {
        "outtmpl": os.path.join(
            tmpdir,
            "%(title).80B [%(id)s].%(ext)s"
        ),
        "http_headers": browser_headers(),
        "noplaylist": True,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "extractor_retries": 5,
        "socket_timeout": 60,
        "max_filesize": MAX_BYTES,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,

        # Android/iOS client to bypass initial bot blocking
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb"]
            }
        }
    }

    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG

    if os.getenv("PROXY_URL"):
        opts["proxy"] = os.getenv("PROXY_URL")

    if os.getenv("COOKIES_TXT"):
        cookies_path = os.path.join(tmpdir, "cookies.txt")
        with open(cookies_path, "w", encoding="utf-8") as f:
            f.write(os.environ["COOKIES_TXT"])
        opts["cookiefile"] = cookies_path

    if fmt == "mp3":
        if not FFMPEG:
            raise RuntimeError("FFmpeg is required for MP3 conversion.")
        opts["format"] = "140/139/251/250/249"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
        return opts

    if FFMPEG:
        opts["format"] = (
            f"bv*[height<={height}][vcodec^=avc1][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={height}][vcodec^=avc1]+ba/"
            f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={height}]+ba/"
            f"b[height<={height}][ext=mp4]/"
            f"b[height<={height}]/b"
        )
        opts["merge_output_format"] = "mp4"
    else:
        opts["format"] = f"b[height<={height}][ext=mp4]/b[height<={height}]/b"

    return opts


# =========================================================
# ERROR CLEANER
# =========================================================

def clean_error(error):
    message = str(error)
    message = re.sub(r"\x1b\[[0-9;]*m", "", message)
    message = message.replace("ERROR: ", "").strip()
    lower = message.lower()

    if "requested format" in lower:
        return "This video does not provide the selected quality."
    if "sign in" in lower or "login" in lower or "cookies" in lower:
        return "This video requires login and cannot be accessed as a public video."
    if "403" in lower or "429" in lower or "forbidden" in lower:
        return "The platform temporarily blocked this request. Please try again."
    if "private" in lower or "unavailable" in lower:
        return "This video is private or unavailable."
    if "max-filesize" in lower:
        return f"File is larger than the {MAX_MB} MB limit."

    lines = message.splitlines()
    return lines[-1][:400] if message else "Download failed."


# =========================================================
# ROUTES
# =========================================================

@app.get("/")
def index():
    return render_template("index.html", has_ffmpeg=bool(FFMPEG))


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "ffmpeg": bool(FFMPEG),
        "ffmpeg_path": FFMPEG or None,
        "max_mb": MAX_MB,
        "formats": ["mp4", "mp3"],
        "video_quality": ["720p", "1080p"]
    })


@app.post("/api/download")
def download():
    data = request.get_json(silent=True) or {}
    raw_url = (data.get("url") or "").strip()
    fmt = (data.get("format") or "mp4").lower()
    quality = data.get("quality", 720)

    try:
        height = int(quality)
    except Exception:
        height = 720

    if fmt not in ("mp4", "mp3"):
        return jsonify(error="Invalid format."), 400

    if height not in (720, 1080):
        height = 720

    # Clean URL (Remove Playlist/Mix params)
    url = clean_youtube_url(raw_url)

    if not valid_url(url):
        return jsonify(
            error="Paste a valid YouTube, TikTok, Instagram, Facebook or Twitter/X link."
        ), 400

    if fmt == "mp3" and not FFMPEG:
        return jsonify(error="MP3 conversion requires FFmpeg."), 500

    tmpdir = tempfile.mkdtemp(prefix="dl_")

    def cleanup():
        shutil.rmtree(tmpdir, ignore_errors=True)

    try:
        options = build_opts(tmpdir, fmt, height)

        print("\n================ NEW DOWNLOAD ================")
        print("URL:", url)
        print("FORMAT:", fmt)
        print("QUALITY:", height)
        print("==============================================\n")

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)

        files = [
            f for f in glob.glob(os.path.join(tmpdir, "*"))
            if os.path.isfile(f) and not f.endswith((".part", ".ytdl", ".txt", ".json"))
        ]

        if not files:
            raise RuntimeError("No media file was produced.")

        valid_files = [f for f in files if os.path.getsize(f) >= 1024]
        if not valid_files:
            raise RuntimeError("Downloaded file is empty or invalid.")

        if fmt == "mp3":
            mp3_files = [f for f in valid_files if f.lower().endswith(".mp3")]
            if not mp3_files:
                raise RuntimeError("MP3 conversion failed.")
            path = max(mp3_files, key=os.path.getsize)
        else:
            mp4_files = [f for f in valid_files if f.lower().endswith(".mp4")]
            path = max(mp4_files, key=os.path.getsize) if mp4_files else max(valid_files, key=os.path.getsize)

        ext = path.rsplit(".", 1)[-1].lower()
        if ext not in MIME or os.path.getsize(path) < 1024:
            raise RuntimeError("Invalid file generated.")

        filename = os.path.basename(path)
        response = send_file(
            path,
            mimetype=MIME[ext],
            as_attachment=True,
            download_name=filename
        )
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        response.headers["Cache-Control"] = "no-store"
        response.call_on_close(cleanup)
        return response

    except DownloadError as error:
        print("\n[yt-dlp error] Switching to Fallback API...")
        
        # Automatic Backup Fallback
        backup_url = fallback_download(url, fmt)
        if backup_url:
            try:
                r = requests.get(backup_url, stream=True, timeout=30)
                file_ext = "mp3" if fmt == "mp3" else "mp4"
                download_filename = f"video_download.{file_ext}"

                res = send_file(
                    r.raw,
                    mimetype=MIME.get(file_ext, "video/mp4"),
                    as_attachment=True,
                    download_name=download_filename
                )
                cleanup()
                return res
            except Exception as stream_err:
                print("Fallback Stream Error:", stream_err)

        cleanup()
        return jsonify(error=clean_error(error)), 502

    except Exception as error:
        print("Backend Error:", repr(error))
        cleanup()
        return jsonify(error=clean_error(error)), 500


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=False
    )
