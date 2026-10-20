import os
import tempfile
from flask import Flask, render_template, request, send_file, jsonify
import yt_dlp

app = Flask(__name__)

# Render ke environment variable se cookies read karne ka setup
COOKIES_CONTENT = os.environ.get("COOKIES_TXT")

def get_cookies_file():
    if not COOKIES_CONTENT:
        return None
    # Temporary file banata hai taake yt-dlp cookies ko read kar sake
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(COOKIES_CONTENT)
    return path

@app.route('/')
def index():
    # Check if ffmpeg is available
    has_ffmpeg = os.system("ffmpeg -version") == 0
    return render_template('index.html', has_ffmpeg=has_ffmpeg)

@app.route('/api/download', methods=['POST'])
def download():
    data = request.get_json() or {}
    url = data.get('url')
    file_format = data.get('format', 'mp4')
    quality = data.get('quality', '720')

    if not url:
        return jsonify({'error': 'Please provide a valid video link.'}), 400

    cookies_path = get_cookies_file()

    # yt-dlp configuration options with login cookies and quality fallback
    ydl_opts = {
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(id)s.%(ext)s'),
        'cookiefile': cookies_path if cookies_path else None,
        'noplaylist': True,
    }

    if file_format == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        # Flexible format fallback: Agar exact resolution na mile toh closest available best quality utha lega
        ydl_opts.update({
            'format': f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}]/best',
            'merge_output_format': 'mp4',
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if file_format == 'mp3':
                filename = os.path.splitext(filename)[0] + '.mp3'

        # Cleanup cookies temp file if created
        if cookies_path and os.path.exists(cookies_path):
            os.remove(cookies_path)

        return send_file(filename, as_attachment=True)

    except Exception as e:
        if cookies_path and os.path.exists(cookies_path):
            os.remove(cookies_path)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
