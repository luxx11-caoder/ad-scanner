from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import config as cfg
from .base import derive_filename, filter_headers, unique_path


async def run(task: dict, store, report):
    tid = task["id"]
    source_url = task["source_url"]
    headers = task.get("headers") or {}
    # Check DRM markers quickly before invoking ffmpeg: if extra indicates drm? We'll check manifest via ffmpeg error
    # But we can also pre-check if headers contain drm? Better to rely on HLS content

    # Transition to active
    cur = store.get(tid)
    if cur and cur["status"] in ("pending", "paused"):
        try:
            store.update_status(tid, "active")
        except Exception:
            pass

    download_dir = Path(cfg.load_config().get("download_dir") or str(Path.home() / "Downloads"))
    download_dir.mkdir(parents=True, exist_ok=True)

    # Derive filename
    target = task.get("target_path")
    if not target:
        fname = derive_filename(task, final_url=source_url, mime="video/mp4")
        if not fname.lower().endswith((".mp4", ".mkv", ".ts", ".webm")):
            # HLS output is mp4 by default
            if "." not in fname:
                fname += ".mp4"
        tp = unique_path(download_dir, fname)
        target = str(tp)
        store.update_target(tid, target)
    target_path = Path(target)
    part_path = target_path.with_suffix(target_path.suffix + ".part")
    # ensure .mp4 extension for final? keep as is, but ffmpeg will output to part
    # Check if ffmpeg available
    ffmpeg = shutil.which("ffmpeg")
    yt_dlp = shutil.which("yt-dlp") or shutil.which("yt_dlp")

    # Build headers string for ffmpeg
    req_headers = filter_headers(headers)
    # ffmpeg -headers expects "Key: Value\r\n"
    header_lines = ""
    for k, v in req_headers.items():
        # title case? keep as is but ffmpeg wants canonical
        header_lines += f"{k}: {v}\r\n"

    # If yt-dlp available and ffmpeg not, fallback to yt-dlp
    if not ffmpeg and yt_dlp:
        return await _run_ytdlp_hls(task, store, report, yt_dlp, source_url, req_headers, target_path, part_path)

    if not ffmpeg:
        store.set_error(tid, "err_merge: ffmpeg non trouvé (sudo apt install ffmpeg)")
        return

    # Try Mode A: ffmpeg -c copy
    # Check DRM manifest preflight via simple GET of m3u8/mpd? We'll attempt ffmpeg and parse errors
    # Mark merging status
    try:
        store.update_status(tid, "merging")
    except Exception:
        pass

    # Build ffmpeg command
    # Use -y, -headers, -i url, -c copy output
    # Need to handle that -headers applies to http
    cmd_mp4 = ["ffmpeg", "-y"]
    if header_lines:
        cmd_mp4 += ["-headers", header_lines]
    cmd_mp4 += ["-i", source_url, "-c", "copy", str(part_path)]

    def run_sync(cmd):
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3600)

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: run_sync(cmd_mp4))
        if result.returncode == 0 and part_path.exists() and part_path.stat().st_size > 0:
            # check DRM error strings even on success? no
            part_path.rename(target_path)
            store.update_status(tid, "done")
            store.update_progress(tid, target_path.stat().st_size, size_total=target_path.stat().st_size, target_path=str(target_path))
            return
        stderr = result.stderr or ""
        # check DRM markers
        if any(x in stderr for x in ["#EXT-X-SESSION-KEY", "WIDEVINE", "PLAYREADY", "CENC", "ContentProtection", "967."]):
            # Actually ffmpeg error may contain "Unable to decrypt" etc.
            pass
        if "drm" in stderr.lower() or "decrypt" in stderr.lower() or "encrypted" in stderr.lower():
            store.set_error(tid, "err_drm")
            if part_path.exists():
                try:
                    part_path.unlink()
                except Exception:
                    pass
            return
        # If failed with mp4, retry mkv
        if part_path.exists():
            try:
                part_path.unlink()
            except Exception:
                pass
        # retry mkv
        part_mkv = target_path.with_suffix(".mkv.part")
        final_mkv = target_path.with_suffix(".mkv")
        # use unique? preserve base
        cmd_mkv = ["ffmpeg", "-y"]
        if header_lines:
            cmd_mkv += ["-headers", header_lines]
        cmd_mkv += ["-i", source_url, "-c", "copy", str(part_mkv)]
        result2 = await loop.run_in_executor(None, lambda: run_sync(cmd_mkv))
        if result2.returncode == 0 and part_mkv.exists() and part_mkv.stat().st_size > 0:
            # rename to final mkv (or keep target if .mp4? use mkv)
            # if original target was .mp4, we produce .mkv now
            dest = final_mkv if target_path.suffix.lower() == ".mp4" else target_path
            # need unique check
            if dest.exists():
                dest = unique_path(download_dir, dest.name)
            part_mkv.rename(dest)
            store.update_target(tid, str(dest))
            store.update_status(tid, "done")
            store.update_progress(tid, dest.stat().st_size, size_total=dest.stat().st_size)
            return
        stderr2 = result2.stderr or ""
        if "drm" in stderr2.lower() or "decrypt" in stderr2.lower() or "encrypted" in stderr2.lower():
            store.set_error(tid, "err_drm")
            if part_mkv.exists():
                try:
                    part_mkv.unlink()
                except Exception:
                    pass
            return
        # If both failed, try yt-dlp fallback if available
        if yt_dlp:
            return await _run_ytdlp_hls(task, store, report, yt_dlp, source_url, req_headers, target_path, part_path)
        # else error merge
        err = (stderr2 or stderr)[:500]
        store.set_error(tid, f"err_merge:{err}")
        return
    except subprocess.TimeoutExpired:
        store.set_error(tid, "err_network: timeout ffmpeg")
        return
    except Exception as e:
        # try yt-dlp fallback
        if yt_dlp:
            try:
                return await _run_ytdlp_hls(task, store, report, yt_dlp, source_url, req_headers, target_path, part_path)
            except Exception:
                pass
        store.set_error(tid, f"err_merge:{e}")
        return


async def _run_ytdlp_hls(task, store, report, yt_dlp_bin, source_url, req_headers, target_path: Path, part_path: Path):
    tid = task["id"]
    download_dir = target_path.parent
    # yt-dlp needs template: output to part_path without ext? we use exact
    # Use --no-playlist -f bv*+ba/b --merge-output-format mp4 -o <template>
    # For HLS direct url, yt-dlp can also handle: just url
    # Build headers args
    cmd = [yt_dlp_bin, "--no-playlist", "-f", "bv*+ba/b", "--merge-output-format", "mp4", "-o", str(part_path)]
    for k, v in req_headers.items():
        if k.lower() == "referer":
            cmd += ["--referer", v]
        else:
            cmd += ["--add-header", f"{k}: {v}"]
    cmd += [source_url]
    loop = asyncio.get_event_loop()

    def run_sync():
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3600)

    try:
        result = await loop.run_in_executor(None, run_sync)
        if result.returncode == 0:
            # yt-dlp may have created part_path or part_path.mp4? Check
            # we gave exact part_path, but yt-dlp adds ext; try to find file
            candidates = list(download_dir.glob(part_path.name + "*")) + ([part_path] if part_path.exists() else [])
            # also check with ext
            produced = None
            for c in candidates:
                if c.is_file() and c.stat().st_size > 0:
                    produced = c
                    break
            if not produced and part_path.exists():
                produced = part_path
            if produced:
                # rename to final target if needed
                final = target_path
                if produced != final:
                    # if yt-dlp produced with extension, move
                    if produced.suffix != final.suffix:
                        final = final.with_suffix(produced.suffix)
                    if final.exists():
                        final = unique_path(download_dir, final.name)
                    produced.rename(final)
                    store.update_target(tid, str(final))
                    store.update_progress(tid, final.stat().st_size, size_total=final.stat().st_size)
                else:
                    final.rename(target_path) if final != target_path else None
                    store.update_progress(tid, final.stat().st_size, size_total=final.stat().st_size)
                store.update_status(tid, "done")
                return
        stderr = (result.stderr or "")[:500]
        if "drm" in stderr.lower() or "encrypted" in stderr.lower():
            store.set_error(tid, "err_drm")
            return
        store.set_error(tid, f"err_merge:{stderr}")
        return
    except Exception as e:
        store.set_error(tid, f"err_merge:{e}")
        return
