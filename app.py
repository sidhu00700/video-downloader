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

        "max_filesize": MAX_BYTES,

        "restrictfilenames": False,
        "windowsfilenames": True,

        "quiet": True,
        "no_warnings": True,
        "noprogress": True,

        # Yahan ye naya addition karna hai 👇
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios"]
            }
        }
    }
