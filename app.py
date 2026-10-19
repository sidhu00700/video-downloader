import requests

def fallback_download(url):
    """Cobalt API se backup download link fetch karna"""
    api_url = "https://api.cobalt.tools/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    payload = {
        "url": url,
        "vQuality": "720"
    }
    
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        data = res.json()
        
        # Cobalt responses can have 'url', 'picker' (multiple items), or 'stream'
        status = data.get("status")
        
        if status in ("redirect", "stream", "success"):
            return data.get("url")
            
        elif status == "picker":
            # Agar multiple formats hon toh pehla wala utha lo
            picker_items = data.get("picker", [])
            if picker_items and "url" in picker_items[0]:
                return picker_items[0]["url"]
                
    except Exception as e:
        print("Cobalt Fallback Error:", repr(e))
        
    return None
    except DownloadError as error:
        # Pehle yt_dlp fail hone par fallback try karein
        fallback_url = fallback_download(url)
        
        if fallback_url:
            # Agar fallback se direct streaming/download link mil jaye
            return jsonify({"redirect_url": fallback_url})
            
        # Agar fallback bhi fail ho jaye tab error show karein
        cleanup()
        return jsonify(error=clean_error(error)), 502
