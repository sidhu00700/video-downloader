import requests

def fallback_download(url):
    """YouTube Block hone par Backup API se URL fetch karna"""
    api_url = "https://api.cobalt.tools/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {"url": url}
    
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        data = res.json()
        if "url" in data:
            return data["url"]
    except Exception:
        pass
    return None
