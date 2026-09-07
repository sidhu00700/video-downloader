from flask import Flask, render_template, request, Response, jsonify
import yt_dlp
import requests
import os

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-info', methods=['POST'])
def get_info():
    data = request.get_json()
    video_url = data.get('url', '')

    if not video_url:
        return jsonify({'error': 'URL provide nahi kiya gaya'}), 400

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        }
    }

    # Agar cookies.txt repository mein mojood ho toh use karein
    if os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            if 'entries' in info:
                info = info['entries'][0]

            download_url = info.get('url')
            title = info.get('title', 'video')

            if not download_url:
                return jsonify({'error': 'Video stream extract nahi ho saki'}), 400

            return jsonify({
                'title': title,
                'download_url': download_url
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/stream')
def stream_video():
    target_url = request.args.get('url')
    title = request.args.get('title', 'video')

    if not target_url:
        return "Missing URL", 400

    try:
        req = requests.get(target_url, stream=True, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        headers = {
            'Content-Type': req.headers.get('Content-Type', 'video/mp4'),
            'Content-Disposition': f'attachment; filename="{title}.mp4"'
        }

        return Response(req.iter_content(chunk_size=1024 * 1024), headers=headers)

    except Exception as e:
        return f"Streaming Error: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True)
