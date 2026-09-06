from __future__ import annotations

import re
import time
import urllib.parse
from pathlib import Path

MIME_TO_EXT = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/x-msvideo": ".avi",
    "application/vnd.apple.mpegurl": ".mp4",
    "application/x-mpegurl": ".mp4",
    "application/dash+xml": ".mp4",
    "video/x-flv": ".flv",
    "video/mp2t": ".ts",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
}

ALLOWED_HEADERS = {"cookie", "referer", "origin", "user-agent", "x-requested-with", "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "accept"}

def filter_headers(headers: dict) -> dict:
    out = {}
    for k, v in (headers or {}).items():
        lk = k.lower()
        if lk in ALLOWED_HEADERS:
            # normalize: capitalize? keep as-is but filter
            # Never copy Range/If-Range
            if lk in ("range", "if-range"):
                continue
            out[k] = v
        # also allow lowercase versions: we will send as-is
    # ensure we don't have range
    for rk in list(out.keys()):
        if rk.lower() in ("range", "if-range"):
            del out[rk]
    return out

def mime_to_ext(mime: str | None) -> str:
    if not mime:
        return ".bin"
    mime = mime.split(";")[0].strip().lower()
    return MIME_TO_EXT.get(mime, ".bin")

def sanitize_filename(name: str, max_len: int = 200) -> str:
    # replace forbidden chars
    name = re.sub(r'[/\\<>:"|?*\x00-\x1f]', "_", name)
    name = name.strip().strip(".")
    if not name:
        name = f"fluxcatch-{int(time.time())}"
    if len(name) > max_len:
        # preserve extension
        p = Path(name)
        ext = p.suffix
        stem = p.stem[: max_len - len(ext) - 1]
        name = stem + ext
    return name

def derive_filename(task: dict, final_url: str | None = None, mime: str | None = None, content_disposition: str | None = None) -> str:
    # Garde-fou : refuse les URLs page .php/.html sans CD et avec mime html (err_not_media)
    if not content_disposition and final_url:
        low_path = final_url.lower().split("?")[0].split("#")[0]
        if low_path.endswith((".php", ".html", ".htm", ".aspx", ".jsp", ".cgi")):
            if mime and ("text/html" in mime.lower() or "application/xhtml" in mime.lower()):
                raise ValueError("err_not_media")
    # 1. Content-Disposition
    if content_disposition:
        # parse filename* or filename
        # simple parse: filename="..." or filename=...
        m = re.search(r'filename\*\s*=\s*UTF-8\'\'([^;\s]+)', content_disposition, re.I)
        if m:
            try:
                fname = urllib.parse.unquote(m.group(1))
                if fname:
                    return sanitize_filename(fname)
            except Exception:
                pass
        m = re.search(r'filename\s*=\s*"([^"]+)"', content_disposition, re.I)
        if m:
            return sanitize_filename(m.group(1))
        m = re.search(r"filename\s*=\s*([^;\s]+)", content_disposition, re.I)
        if m:
            return sanitize_filename(m.group(1).strip('"').strip("'"))

    # 2. URL basename
    url = final_url or task.get("source_url") or ""
    if url:
        try:
            parsed = urllib.parse.urlparse(url)
            base = Path(parsed.path).name
            if base:
                base = urllib.parse.unquote(base)
                # strip query-like suffix? already without query
                if "." in base or len(base) > 3:
                    return sanitize_filename(base)
        except Exception:
            pass

    # 3. title from task
    title = task.get("title")
    if title:
        ext = mime_to_ext(mime)
        # if title has extension already, don't double
        if Path(title).suffix:
            return sanitize_filename(title)
        # use title + ext
        # apply template if provided? For now simple
        return sanitize_filename(f"{title}{ext}")

    # 4. fallback
    ext = mime_to_ext(mime)
    return sanitize_filename(f"fluxcatch-{int(time.time())}{ext}")


def unique_path(download_dir: Path, filename: str) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    base = sanitize_filename(filename)
    p = download_dir / base
    if not p.exists() and not (p.with_suffix(p.suffix + ".part")).exists():
        return p
    stem = p.stem
    suffix = p.suffix
    i = 2
    while True:
        cand = download_dir / f"{stem}-{i}{suffix}"
        if not cand.exists() and not cand.with_suffix(cand.suffix + ".part"):
            return cand
        i += 1

def parse_headers_for_request(headers_json: dict) -> dict:
    # filter and return dict suitable for aiohttp
    filtered = filter_headers(headers_json)
    # normalize keys? aiohttp is case-insensitive, keep as provided
    return filtered

def detect_hls_kind(url: str) -> bool:
    low = url.lower().split("?")[0].split("#")[0]
    return low.endswith(".m3u8") or low.endswith(".mpd")

def detect_ytdlp_kind(page_url: str | None) -> bool:
    if not page_url:
        return False
    low = page_url.lower()
    return any(d in low for d in ["youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "dai.ly"])
