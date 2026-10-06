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
    """
    IMPORTANT:
    Prefer imageio-ffmpeg first.

    The old system ffmpeg found on this PC is from 2013,
    so using it with modern yt-dlp causes post-processing
    errors such as:

        Error splitting the argument list: Option not found
    """

    try:
        import imageio_ffmpeg

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

        if ffmpeg_path and os.path.exists(ffmpeg_path):
            return ffmpeg_path

    except Exception:
        pass

    # Fallback to system FFmpeg only if imageio-ffmpeg
    # is unavailable.
    system_ffmpeg = shutil.which("ffmpeg")

    if system_ffmpeg:
        return system_ffmpeg

    return None


FFMPEG = find_ffmpeg()


# =========================================================
# HTTP HEADERS
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


# =========================================================
# URL VALIDATION
# =========================================================

def valid_url(url):
    try:
        parsed = urlparse(url)

        host = (parsed.hostname or "").lower()

        if parsed.scheme not in ("http", "https"):
            return False

        return any(
            host == allowed
            or host.endswith("." + allowed)
            for allowed in ALLOWED_HOSTS
        )

    except Exception:
        return False


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

        # Download reliability
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "extractor_retries": 5,

        "socket_timeout": 60,

        # Size limit
        "max_filesize": MAX_BYTES,

        # Filename handling
        "restrictfilenames": False,
        "windowsfilenames": True,

        # Less terminal noise
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }


    # -----------------------------------------------------
    # MODERN FFMPEG
    # -----------------------------------------------------

    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG


    # -----------------------------------------------------
    # OPTIONAL PROXY
    # -----------------------------------------------------

    if os.getenv("PROXY_URL"):
        opts["proxy"] = os.getenv("PROXY_URL")


    # -----------------------------------------------------
    # OPTIONAL COOKIES
    #
    # Only use this for content the user is authorized
    # to access.
    # -----------------------------------------------------

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
            f.write(
                os.environ["COOKIES_TXT"]
            )

        opts["cookiefile"] = cookies_path


    # =====================================================
    # MP3
    # =====================================================

    if fmt == "mp3":

        if not FFMPEG:
            raise RuntimeError(
                "FFmpeg is required for MP3 conversion."
            )

        # Prefer standard YouTube M4A audio.
        # Then fall back to other audio formats.
        opts["format"] = (
            "140/"
            "139/"
            "251/"
            "250/"
            "249"
        )

        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]

        return opts


    # =====================================================
    # MP4
    # =====================================================

    if FFMPEG:

        opts["format"] = (

            # -------------------------------------------------
            # Best H.264 MP4 video + M4A audio
            # -------------------------------------------------

            f"bv*[height<={height}]"
            "[vcodec^=avc1]"
            "[ext=mp4]"
            "+"
            "ba[ext=m4a]/"

            # -------------------------------------------------
            # H.264 video + any compatible audio
            # -------------------------------------------------

            f"bv*[height<={height}]"
            "[vcodec^=avc1]"
            "+"
            "ba/"

            # -------------------------------------------------
            # Any MP4 video + M4A audio
            # -------------------------------------------------

            f"bv*[height<={height}]"
            "[ext=mp4]"
            "+"
            "ba[ext=m4a]/"

            # -------------------------------------------------
            # Any compatible video + audio
            # -------------------------------------------------

            f"bv*[height<={height}]"
            "+"
            "ba/"

            # -------------------------------------------------
            # Progressive MP4 fallback
            # -------------------------------------------------

            f"b[height<={height}]"
            "[ext=mp4]/"

            f"b[height<={height}]/"

            "b"
        )

        opts["merge_output_format"] = "mp4"

    else:

        opts["format"] = (
            f"b[height<={height}]"
            "[ext=mp4]/"
            f"b[height<={height}]/"
            "b"
        )


    return opts


# =========================================================
# ERROR CLEANER
# =========================================================

def clean_error(error):

    message = str(error)

    # Remove ANSI terminal colors
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


    # -----------------------------------------------------
    # Format unavailable
    # -----------------------------------------------------

    if (
        "requested format is not available"
        in lower
        or
        "requested format not available"
        in lower
    ):
        return (
            "This video does not provide the selected "
            "quality. Please try the other quality option."
        )


    # -----------------------------------------------------
    # Login / cookies
    # -----------------------------------------------------

    if (
        "sign in" in lower
        or "login" in lower
        or "cookies" in lower
    ):
        return (
            "This video requires login and cannot be "
            "accessed as a public video."
        )


    # -----------------------------------------------------
    # HTTP 403 / 429
    # -----------------------------------------------------

    if (
        "403" in lower
        or "429" in lower
        or "forbidden" in lower
    ):
        return (
            "The platform temporarily blocked this "
            "request. Please try again."
        )


    # -----------------------------------------------------
    # Private / unavailable
    # -----------------------------------------------------

    if (
        "private" in lower
        or "unavailable" in lower
    ):
        return (
            "This video is private or unavailable."
        )


    # -----------------------------------------------------
    # File too large
    # -----------------------------------------------------

    if "max-filesize" in lower:

        return (
            f"File is larger than the "
            f"{MAX_MB} MB limit."
        )


    # -----------------------------------------------------
    # FFmpeg codec problems
    # -----------------------------------------------------

    if (
        "could not find codec parameters"
        in lower
        or
        "invalid data found"
        in lower
    ):
        return (
            "The selected media stream could not be "
            "processed by FFmpeg. Please try again."
        )


    # -----------------------------------------------------
    # FFmpeg missing
    # -----------------------------------------------------

    if (
        "ffmpeg" in lower
        and
        "not found" in lower
    ):
        return (
            "FFmpeg is required for MP3 conversion "
            "but was not found."
        )


    # -----------------------------------------------------
    # Post-processing errors
    # -----------------------------------------------------

    if "postprocessing" in lower:

        return (
            "Download completed, but FFmpeg could not "
            "finish the media conversion."
        )


    # -----------------------------------------------------
    # Generic
    # -----------------------------------------------------

    if not message:

        return "Download failed."


    lines = message.splitlines()

    return lines[-1][:400]


# =========================================================
# HOME
# =========================================================

@app.get("/")
def index():

    return render_template(
        "index.html",
        has_ffmpeg=bool(FFMPEG)
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
def health():

    return jsonify({

        "status": "ok",

        "ffmpeg": bool(FFMPEG),

        "ffmpeg_path": FFMPEG or None,

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


# =========================================================
# DOWNLOAD API
# =========================================================

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


    # -----------------------------------------------------
    # Quality
    # -----------------------------------------------------

    try:

        height = int(
            quality
        )

    except Exception:

        height = 720


    # -----------------------------------------------------
    # Validate format
    # -----------------------------------------------------

    if fmt not in (
        "mp4",
        "mp3"
    ):

        return jsonify(
            error="Invalid format."
        ), 400


    # -----------------------------------------------------
    # Validate quality
    # -----------------------------------------------------

    if height not in (
        720,
        1080
    ):

        height = 720


    # MP3 doesn't use video quality
    if fmt == "mp3":
        height = 720


    # -----------------------------------------------------
    # Validate URL
    # -----------------------------------------------------

    if not valid_url(url):

        return jsonify(
            error=(
                "Paste a valid YouTube, TikTok, "
                "Instagram, Facebook or Twitter/X link."
            )
        ), 400


    # -----------------------------------------------------
    # FFmpeg check
    # -----------------------------------------------------

    if fmt == "mp3" and not FFMPEG:

        return jsonify(
            error=(
                "MP3 conversion requires FFmpeg. "
                "Please install or enable FFmpeg."
            )
        ), 500


    # -----------------------------------------------------
    # Temporary directory
    # -----------------------------------------------------

    tmpdir = tempfile.mkdtemp(
        prefix="dl_"
    )


    def cleanup():

        shutil.rmtree(
            tmpdir,
            ignore_errors=True
        )


    # =====================================================
    # DOWNLOAD
    # =====================================================

    try:

        options = build_opts(
            tmpdir,
            fmt,
            height
        )


        print()
        print(
            "=============================================="
        )
        print(
            "NEW DOWNLOAD"
        )
        print(
            "=============================================="
        )
        print(
            "URL:",
            url
        )
        print(
            "FORMAT:",
            fmt
        )
        print(
            "QUALITY:",
            height
        )
        print(
            "FFMPEG:",
            FFMPEG
        )
        print(
            "=============================================="
        )


        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            ydl.extract_info(
                url,
                download=True
            )


        # =================================================
        # FIND OUTPUT FILES
        # =================================================

        files = [

            file

            for file in glob.glob(
                os.path.join(
                    tmpdir,
                    "*"
                )
            )

            if os.path.isfile(file)

            and not file.endswith(
                (
                    ".part",
                    ".ytdl",
                    ".txt",
                    ".json"
                )
            )
        ]


        if not files:

            raise RuntimeError(
                "No media file was produced."
            )


        # =================================================
        # REMOVE EMPTY FILES
        # =================================================

        valid_files = [

            file

            for file in files

            if os.path.getsize(
                file
            ) >= 1024
        ]


        if not valid_files:

            raise RuntimeError(
                "Downloaded file is empty or invalid."
            )


        # =================================================
        # MP3 OUTPUT
        # =================================================

        if fmt == "mp3":

            mp3_files = [

                file

                for file in valid_files

                if file.lower().endswith(
                    ".mp3"
                )
            ]


            if not mp3_files:

                raise RuntimeError(
                    "MP3 conversion failed."
                )


            path = max(
                mp3_files,
                key=os.path.getsize
            )


        # =================================================
        # MP4 OUTPUT
        # =================================================

        else:

            mp4_files = [

                file

                for file in valid_files

                if file.lower().endswith(
                    ".mp4"
                )
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


        # =================================================
        # FINAL VALIDATION
        # =================================================

        ext = path.rsplit(
            ".",
            1
        )[-1].lower()


        if ext not in MIME:

            raise RuntimeError(
                "Unsupported media format returned."
            )


        if os.path.getsize(path) < 1024:

            raise RuntimeError(
                "Downloaded file is invalid."
            )


        # =================================================
        # SEND FILE
        # =================================================

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


        # Cleanup after response finishes
        response.call_on_close(
            cleanup
        )


        return response


    # =====================================================
    # YT-DLP ERROR
    # =====================================================

    except DownloadError as error:

        print()
        print(
            "================ YT-DLP ERROR ================"
        )
        print(
            str(error)
        )
        print(
            "==============================================="
        )
        print()

        cleanup()

        return jsonify(
            error=clean_error(error)
        ), 502


    # =====================================================
    # GENERAL ERROR
    # =====================================================

    except Exception as error:

        print()
        print(
            "=============== BACKEND ERROR ================"
        )
        print(
            repr(error)
        )
        print(
            "=============================================="
        )
        print()

        cleanup()

        return jsonify(
            error=clean_error(error)
        ), 500


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    print()

    print(
        "=" * 55
    )

    print(
        "MASTER VIDEO DOWNLOADER"
    )

    print(
        "=" * 55
    )

    print(
        "FFmpeg:",
        FFMPEG or "NOT FOUND"
    )

    print(
        "Formats: MP4 / MP3"
    )

    print(
        "Video Quality: 720p / 1080p"
    )

    print(
        "MP3: YouTube Audio → FFmpeg → MP3"
    )

    print(
        "=" * 55
    )

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
