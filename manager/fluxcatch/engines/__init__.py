from __future__ import annotations

from . import direct, hls, ytdlp, upload

REGISTRY = {
    "direct": direct.run,
    "hls": hls.run,
    "ytdlp": ytdlp.run,
    "recorder": upload.run,
    "browser_proxy": upload.run,
}

def get_engine(kind: str):
    return REGISTRY.get(kind)
