import os
import requests
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import yt_dlp

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_download_link', methods=['POST'])
def get_download_link():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'Please provide a valid URL'}), 400

    video_url = data.get('url').strip()
    if not video_url:
        return jsonify({'error': 'URL cannot be empty'}), 400

    try:
        ydl_opts = {
            'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            video_title = info.get('title', 'Video')
            
            direct_url = info.get('url')
            if not direct_url and 'formats' in info:
                for f in reversed(info['formats']):
                    if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                        direct_url = f.get('url')
                        break
                if not direct_url and len(info['formats']) > 0:
                    direct_url = info['formats'][-1].get('url')

            if direct_url:
                safe_title = "".join([c for c in video_title if c.isalnum() or c in (' ', '_', '-')]).strip()
                return jsonify({
                    'success': True,
                    'title': safe_title if safe_title else "Video",
                    'download_url': direct_url
                })
            else:
                return jsonify({'error': 'Could not extract direct stream link.'}), 400

    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

# Continuous Direct Stream Route (NO REDIRECT POSSIBLE)
@app.route('/stream')
def stream_video():
    video_url = request.args.get('url')
    title = request.args.get('title', 'video')
    
    if not video_url:
        return "No URL provided", 400

    # Request headers mimic real browser
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    r = requests.get(video_url, headers=req_headers, stream=True)

    def generate():
        for chunk in r.iter_content(chunk_size=1024 * 512): # 512KB Chunks
            if chunk:
                yield chunk

    # Force browser to trigger download prompt directly
    response = Response(stream_with_context(generate()), content_type='application/octet-stream')
    response.headers['Content-Disposition'] = f'attachment; filename="{title}.mp4"'
    if 'Content-Length' in r.headers:
        response.headers['Content-Length'] = r.headers['Content-Length']
        
    return response

if __name__ == '__main__':
    app.run(debug=True, port=5000)