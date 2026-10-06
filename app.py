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

        host = (
            parsed.hostname
            or ""
        ).lower()

        if parsed.scheme not in (
            "http",
            "https"
        ):
            return False

        return any(
            host == allowed
            or host.endswith(
                "." + allowed
            )
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


    # ========================================================
    # FFMPEG
    # ========================================================

    if FFMPEG:

        opts["ffmpeg_location"] = FFMPEG


    # ========================================================
    # OPTIONAL PROXY
    # ========================================================

    if os.getenv("PROXY_URL"):

        opts["proxy"] = os.getenv(
            "PROXY_URL"
        )


    # ========================================================
    # OPTIONAL COOKIES
    # ========================================================

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


    # ========================================================
    # MP3
    #
    # IMPORTANT:
    # Instead of directly requesting an audio-only stream,
    # first download a normal compatible media stream.
    # Then FFmpeg extracts the audio into MP3.
    # ========================================================

    if fmt == "mp3":

        if not FFMPEG:

            # Without FFmpeg, MP3 conversion cannot be done.
            # We deliberately fail later with a clear message.
            opts["format"] = (
                "b[ext=mp4]/"
                "b"
            )

            return opts


        # Prefer a normal MP4/progressive stream first.
        # This follows the same public-video access path
        # that works for MP4 downloads.
        opts["format"] = (

            "b[ext=mp4]/"

            "b"
        )


        opts["postprocessors"] = [

            {
                "key": "FFmpegExtractAudio",

                "preferredcodec": "mp3",

                "preferredquality": "192",
            }

        ]

        return opts


    # ========================================================
    # MP4 VIDEO
    # ========================================================

    if FFMPEG:

        # ----------------------------------------------------
        # 1. H264 / AVC1 MP4 + M4A
        # ----------------------------------------------------

        opts["format"] = (

            f"bv*[height<={height}]"
            "[vcodec^=avc1]"
            "[ext=mp4]"
            "+ba[ext=m4a]/"

            # ------------------------------------------------
            # 2. H264 + any compatible audio
            # ------------------------------------------------

            f"bv*[height<={height}]"
            "[vcodec^=avc1]"
            "+ba/"

            # ------------------------------------------------
            # 3. Any MP4 video + M4A
            # ------------------------------------------------

            f"bv*[height<={height}]"
            "[ext=mp4]"
            "+ba[ext=m4a]/"

            # ------------------------------------------------
            # 4. Any compatible video + audio
            # ------------------------------------------------

            f"bv*[height<={height}]"
            "+ba/"

            # ------------------------------------------------
            # 5. Single-file MP4
            # ------------------------------------------------

            f"b[height<={height}]"
            "[ext=mp4]/"

            # ------------------------------------------------
            # 6. Any single-file format
            # ------------------------------------------------

            f"b[height<={height}]/"

            # ------------------------------------------------
            # 7. Final fallback
            # ------------------------------------------------

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
        "requested format is not available"
        in lower
        or
        "requested format not available"
        in lower
    ):

        return (
            "This video does not provide the selected quality. "
            "Please try the other quality option."
        )


    if (
        "sign in" in lower
        or
        "login" in lower
        or
        "cookies" in lower
    ):

        return (
            "This video requires login and cannot be accessed "
            "as a public video."
        )


    if (
        "403" in lower
        or
        "429" in lower
        or
        "forbidden" in lower
    ):

        return (
            "The platform temporarily blocked this request. "
            "Please try again later."
        )


    if (
        "private" in lower
        or
        "unavailable" in lower
    ):

        return (
            "This video is private or unavailable."
        )


    if "max-filesize" in lower:

        return (
            f"File is larger than the "
            f"{MAX_MB} MB limit."
        )


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


    if (
        "ffmpeg" in lower
        and
        "not found" in lower
    ):

        return (
            "FFmpeg is required for MP3 conversion "
            "but was not found."
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


    # ========================================================
    # URL
    # ========================================================

    url = (
        data.get("url")
        or ""
    ).strip()


    # ========================================================
    # FORMAT
    # ========================================================

    fmt = (
        data.get("format")
        or "mp4"
    ).lower()


    # ========================================================
    # QUALITY
    # ========================================================

    quality = data.get(
        "quality",
        720
    )


    try:

        height = int(
            quality
        )

    except Exception:

        height = 720


    # ========================================================
    # ONLY MP4 / MP3
    # ========================================================

    if fmt not in (
        "mp4",
        "mp3"
    ):

        return jsonify(
            error="Invalid format."
        ), 400


    # ========================================================
    # ONLY 720 / 1080
    # ========================================================

    if height not in (
        720,
        1080
    ):

        height = 720


    # ========================================================
    # MP3 DOES NOT USE QUALITY
    # ========================================================

    if fmt == "mp3":

        height = 720


    # ========================================================
    # URL VALIDATION
    # ========================================================

    if not valid_url(url):

        return jsonify(

            error=(
                "Paste a valid YouTube, TikTok, "
                "Instagram, Facebook or Twitter/X link."
            )

        ), 400


    # ========================================================
    # FFMPEG REQUIRED FOR MP3
    # ========================================================

    if fmt == "mp3" and not FFMPEG:

        return jsonify(

            error=(
                "MP3 conversion requires FFmpeg. "
                "Please install or enable FFmpeg."
            )

        ), 500


    # ========================================================
    # TEMP DIRECTORY
    # ========================================================

    tmpdir = tempfile.mkdtemp(
        prefix="dl_"
    )


    def cleanup():

        shutil.rmtree(
            tmpdir,
            ignore_errors=True
        )


    try:

        # ====================================================
        # BUILD OPTIONS
        # ====================================================

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
        # FIND DOWNLOADED FILES
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

                and

                not file.endswith(
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


        # ====================================================
        # REMOVE EMPTY FILES
        # ====================================================

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

                if file.lower().endswith(
                    ".mp3"
                )

            ]


            if mp3_files:

                path = max(
                    mp3_files,
                    key=os.path.getsize
                )

            else:

                raise RuntimeError(
                    "MP3 conversion failed."
                )


        # ====================================================
        # MP4
        # ====================================================

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


        # ====================================================
        # MIME VALIDATION
        # ====================================================

        if ext not in MIME:

            raise RuntimeError(
                "Unsupported media format returned."
            )


        # ====================================================
        # FINAL SIZE CHECK
        # ====================================================

        if os.path.getsize(path) < 1024:

            raise RuntimeError(
                "Downloaded file is invalid."
            )


        # ====================================================
        # FILENAME
        # ====================================================

        filename = os.path.basename(
            path
        )


        # ====================================================
        # SEND FILE
        # ====================================================

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


        # ====================================================
        # CLEAN TEMP FILE AFTER DOWNLOAD
        # ====================================================

        response.call_on_close(
            cleanup
        )


        return response


    # ========================================================
    # YT-DLP ERROR
    # ========================================================

    except DownloadError as error:

        cleanup()

        return jsonify(
            error=clean_error(error)
        ), 502


    # ========================================================
    # GENERAL ERROR
    # ========================================================

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

    print(
        "MASTER VIDEO DOWNLOADER"
    )

    print("=" * 55)

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
        "MP3: FFmpeg Audio Extraction"
    )

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
