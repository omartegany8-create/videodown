import re
from urllib.parse import quote

import requests
import yt_dlp
from flask import Flask, Response, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=None)

YDL_OPTS = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
URL_RE = re.compile(r"^https?://", re.I)


def extract(url):
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        return ydl.extract_info(url, download=False)


def usable(f):
    return f.get("url") and f.get("protocol") in ("http", "https")


@app.get("/")
def index():
    return send_from_directory(".", "index.html")


@app.post("/api/info")
def info():
    url = ((request.get_json(silent=True) or {}).get("url") or "").strip()
    if not URL_RE.match(url):
        return jsonify(error="رابط غير صالح"), 400
    try:
        d = extract(url)
    except Exception:
        return jsonify(error="مقدرتش أجيب الفيديو. اتأكد إن الرابط صحيح وعام (مش خاص)."), 422

    formats, seen = [], set()
    # فيديو + صوت مع بعض (جاهز للتحميل مباشرة)
    combined = [f for f in d.get("formats", [])
                if usable(f) and f.get("vcodec") != "none" and f.get("acodec") != "none"]
    for f in sorted(combined, key=lambda x: x.get("height") or 0, reverse=True):
        h = f.get("height")
        key = ("v", h)
        if key in seen:
            continue
        seen.add(key)
        formats.append({
            "id": f["format_id"],
            "label": f"فيديو {h}p" if h else "فيديو",
            "ext": f.get("ext", "mp4"),
            "size": f.get("filesize") or f.get("filesize_approx"),
        })
    # صوت فقط
    audio = [f for f in d.get("formats", [])
             if usable(f) and f.get("vcodec") == "none" and f.get("acodec") != "none"]
    if audio:
        best = max(audio, key=lambda x: x.get("abr") or 0)
        formats.append({
            "id": best["format_id"],
            "label": "صوت فقط",
            "ext": best.get("ext", "m4a"),
            "size": best.get("filesize") or best.get("filesize_approx"),
        })
    if not formats:
        return jsonify(error="مفيش صيغ متاحة للتحميل من الرابط ده."), 422

    return jsonify(
        title=d.get("title") or "فيديو",
        thumbnail=d.get("thumbnail"),
        duration=d.get("duration"),
        uploader=d.get("uploader"),
        formats=formats[:8],
    )


@app.get("/api/dl")
def download():
    url = request.args.get("url", "")
    fid = request.args.get("fid", "")
    if not URL_RE.match(url) or not fid:
        return "bad request", 400
    try:
        d = extract(url)
        f = next(x for x in d["formats"] if x["format_id"] == fid and usable(x))
    except Exception:
        return "not found", 404

    upstream = requests.get(f["url"], headers=f.get("http_headers") or {}, stream=True, timeout=20)
    ext = f.get("ext", "mp4")
    name = quote(f"{(d.get('title') or 'video')[:80]}.{ext}")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{name}"}
    if upstream.headers.get("Content-Length"):
        headers["Content-Length"] = upstream.headers["Content-Length"]
    return Response(
        upstream.iter_content(chunk_size=64 * 1024),
        content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
        headers=headers,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
