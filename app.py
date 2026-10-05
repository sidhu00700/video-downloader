import glob
import os
import random
import re
import shutil
import tempfile
from urllib.parse import quote, urlparse

from flask import Flask, jsonify, render_template, request, send_file
import yt_dlp
from yt_dlp.utils import DownloadError


app = Flask(__name__)


# ============================================================
# CONFIG
# ============================================================

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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36",

    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36",
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


# ============================================================
# FFMPEG
# ============================================================

def find_ffmpeg():
    system_ffmpeg = shutil.which("ffmpeg")

    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


FFMPEG = find_ffmpeg()


# ============================================================
# HEADERS
# ============================================================

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


# ============================================================
# URL VALIDATION
# ============================================================

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


# ============================================================
# DOWNLOAD OPTIONS
# ============================================================

def build_opts(tmpdir, fmt, height):

    opts = {
        "outtmpl": os.path.join(
            tmpdir,
            "%(title).80B [%(id)s].%(ext)s"
        ),

        "http_headers": browser_headers(),

        "noplaylist": True,

        "retries": 8,
        "fragment_retries": 8,
        "file_access_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,

        "max_filesize": MAX_BYTES,

        "restrictfilenames": False,
        "windowsfilenames": True,

        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG

    if os.getenv("PROXY_URL"):
        opts["proxy"] = os.getenv("PROXY_URL")

    if os.getenv("COOKIES_TXT"):
        cookies_path = os.path.join(
            tmpdir,
            "cookies.txt"
        )

        with open(
            cookies_path,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(os.environ["COOKIES_TXT"])

        opts["cookiefile"] = cookies_path


    # ========================================================
    # MP3
    # ========================================================

    if fmt == "mp3":

        if FFMPEG:

            opts["format"] = (
                "ba[ext=m4a]/"
                "ba[ext=webm]/"
                "ba/b"
            )

            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        else:

            opts["format"] = (
                "ba[ext=m4a]/"
                "ba[ext=webm]/"
                "ba/b"
            )

        return opts


    # ========================================================
    # MP4 VIDEO
    # ========================================================

    if FFMPEG:

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # First preference = H264 / AVC1
        #
        # If unavailable, automatically fallback to ANY
        # compatible video stream.
        #
        # This fixes TikTok videos where AVC1 is unavailable.
        # ----------------------------------------------------

        opts["format"] = (

            # 1. H264 MP4 + M4A
            f"bv*[height<={height}]"
            "[vcodec^=avc1]"
            "[ext=mp4]"
            "+ba[ext=m4a]/"

            # 2. H264 + any compatible audio
            f"bv*[height<={height}]"
            "[vcodec^=avc1]"
            "+ba/"

            # 3. Any MP4 video + M4A
            f"bv*[height<={height}]"
            "[ext=mp4]"
            "+ba[ext=m4a]/"

            # 4. Any compatible video + audio
            f"bv*[height<={height}]"
            "+ba/"

            # 5. Single-file MP4
            f"b[height<={height}]"
            "[ext=mp4]/"

            # 6. Any single-file compatible format
            f"b[height<={height}]/"

            # 7. Final best available fallback
            "b"
        )

        opts["merge_output_format"] = "mp4"

    else:

        # Without FFmpeg we can only safely request
        # an already merged video.

        opts["format"] = (
            f"b[height<={height}]"
            "[ext=mp4]/"

            f"b[height<={height}]/"

            "b"
        )

    return opts


# ============================================================
# ERROR CLEANER
# ============================================================

def clean_error(error):

    message = str(error)

    message = re.sub(
        r"\x1b\[[0-9;]*m",
        "",
        message
    )

    message = message.replace(
        "ERROR: ",
        ""
    ).strip()

    lower = message.lower()

    if (
        "requested format is not available" in lower
        or "requested format not available" in lower
    ):
        return (
            "This video does not provide the selected quality. "
            "Please try the other quality option."
        )

    if (
        "sign in" in lower
        or "login" in lower
        or "cookies" in lower
    ):
        return (
            "This video requires login and cannot be accessed "
            "as a public video."
        )

    if (
        "403" in lower
        or "429" in lower
        or "forbidden" in lower
    ):
        return (
            "The platform temporarily blocked this request. "
            "Please try again later."
        )

    if (
        "private" in lower
        or "unavailable" in lower
    ):
        return "This video is private or unavailable."

    if "max-filesize" in lower:
        return (
            f"File is larger than the {MAX_MB} MB limit."
        )

    if (
        "could not find codec parameters" in lower
        or "invalid data found" in lower
    ):
        return (
            "The selected media stream could not be processed "
            "by FFmpeg. Please try the other quality."
        )

    if not message:
        return "Download failed."

    lines = message.splitlines()

    return lines[-1][:400]


# ============================================================
# HOME
# ============================================================

@app.get("/")
def index():

    return render_template(
        "index.html",
        has_ffmpeg=bool(FFMPEG)
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return jsonify({
        "status": "ok",
        "ffmpeg": bool(FFMPEG),
        "max_mb": MAX_MB,
        "formats": [
            "mp4",
            "mp3"
        ],
        "video_quality": [
            "720p",
            "1080p"
        ]
    })


# ============================================================
# DOWNLOAD
# ============================================================

@app.post("/api/download")
def download():

    data = request.get_json(
        silent=True
    ) or {}

    url = (
        data.get("url")
        or ""
    ).strip()

    fmt = (
        data.get("format")
        or "mp4"
    ).lower()

    quality = data.get(
        "quality",
        720
    )

    try:
        height = int(quality)
    except Exception:
        height = 720

    # --------------------------------------------------------
    # ONLY 720 / 1080
    # --------------------------------------------------------

    if fmt not in (
        "mp4",
        "mp3"
    ):
        return jsonify(
            error="Invalid format."
        ), 400

    if height not in (
        720,
        1080
    ):
        height = 720

    # MP3 doesn't use resolution
    if fmt == "mp3":
        height = 720

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    if not valid_url(url):

        return jsonify(
            error=(
                "Paste a valid YouTube, TikTok, "
                "Instagram, Facebook or Twitter/X link."
            )
        ), 400

    # --------------------------------------------------------
    # TEMP DIRECTORY
    # --------------------------------------------------------

    tmpdir = tempfile.mkdtemp(
        prefix="dl_"
    )

    def cleanup():
        shutil.rmtree(
            tmpdir,
            ignore_errors=True
        )

    try:

        options = build_opts(
            tmpdir,
            fmt,
            height
        )

        # ====================================================
        # DOWNLOAD
        # ====================================================

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            ydl.extract_info(
                url,
                download=True
            )

        # ====================================================
        # FIND FILES
        # ====================================================

        files = [
            file
            for file in glob.glob(
                os.path.join(
                    tmpdir,
                    "*"
                )
            )
            if (
                os.path.isfile(file)
                and not file.endswith(
                    (
                        ".part",
                        ".ytdl",
                        ".txt",
                        ".json"
                    )
                )
            )
        ]

        if not files:
            raise RuntimeError(
                "No media file was produced."
            )

        # Ignore tiny files
        valid_files = [
            file
            for file in files
            if os.path.getsize(file) >= 1024
        ]

        if not valid_files:
            raise RuntimeError(
                "Downloaded file is empty or invalid."
            )

        # ====================================================
        # MP3
        # ====================================================

        if fmt == "mp3":

            mp3_files = [
                file
                for file in valid_files
                if file.lower().endswith(".mp3")
            ]

            if mp3_files:
                path = max(
                    mp3_files,
                    key=os.path.getsize
                )
            else:
                path = max(
                    valid_files,
                    key=os.path.getsize
                )

        else:

            # Prefer MP4 output
            mp4_files = [
                file
                for file in valid_files
                if file.lower().endswith(".mp4")
            ]

            if mp4_files:
                path = max(
                    mp4_files,
                    key=os.path.getsize
                )
            else:
                path = max(
                    valid_files,
                    key=os.path.getsize
                )

        # ====================================================
        # EXTENSION
        # ====================================================

        ext = (
            path.rsplit(
                ".",
                1
            )[-1]
            .lower()
        )

        if ext not in MIME:
            raise RuntimeError(
                "Unsupported media format returned."
            )

        if os.path.getsize(path) < 1024:
            raise RuntimeError(
                "Downloaded file is invalid."
            )

        # ====================================================
        # SEND FILE
        # ====================================================

        filename = os.path.basename(
            path
        )

        response = send_file(
            path,
            mimetype=MIME[ext],
            as_attachment=True,
            download_name=filename
        )

        response.headers[
            "Content-Disposition"
        ] = (
            "attachment; "
            "filename*=UTF-8''"
            + quote(filename)
        )

        response.headers[
            "Cache-Control"
        ] = "no-store"

        response.call_on_close(
            cleanup
        )

        return response

    except DownloadError as error:

        cleanup()

        return jsonify(
            error=clean_error(error)
        ), 502

    except Exception as error:

        cleanup()

        return jsonify(
            error=clean_error(error)
        ), 500


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 55)
    print("MASTER VIDEO DOWNLOADER")
    print("=" * 55)
    print(
        "FFmpeg:",
        FFMPEG or "NOT FOUND"
    )
    print("Formats: MP4 / MP3")
    print("Video Quality: 720p / 1080p")
    print("=" * 55)
    print()

    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                5000
            )
        ),
        debug=False
    )
