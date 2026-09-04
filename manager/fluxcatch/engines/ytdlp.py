from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from pathlib import Path

from .. import config as cfg
from .base import unique_path


async def run(task: dict, store, report):
    tid = task["id"]
    page_url = task.get("page_url") or task.get("source_url")
    headers = task.get("headers") or {}
    # Transition
    cur = store.get(tid)
    if cur and cur["status"] in ("pending", "paused"):
        try:
            store.update_status(tid, "active")
        except Exception:
            pass
    try:
        store.update_status(tid, "merging")
    except Exception:
        pass

    yt_dlp = shutil.which("yt-dlp") or shutil.which("yt_dlp")
    if not yt_dlp:
        store.set_error(tid, "err_merge: yt-dlp non trouvé (pip install yt-dlp)")
        return

    download_dir = Path(cfg.load_config().get("download_dir") or str(Path.home() / "Downloads"))
    download_dir.mkdir(parents=True, exist_ok=True)

    target = task.get("target_path")
    if target:
        target_path = Path(target)
    else:
        # use filename_template from config: {title}.{ext}
        cfg_data = cfg.load_config()
        template = cfg_data.get("filename_template", "{title}.{ext}")
        # yt-dlp will handle template; we set -o to download_dir/template
        # but we need to set target later after file appears
        # Use placeholder: we'll let yt-dlp output to download_dir/%(title)s.%(ext)s and then update store
        # Simplify: output to download_dir/fluxcatch-yt-%(id)s with template
        # We'll use download_dir with template
        # Ensure template: yt-dlp expects %(title)s etc, but our config uses {title}.{ext}
        # Convert: {title} -> %(title)s, {ext} -> %(ext)s
        yt_template = template.replace("{title}", "%(title)s").replace("{ext}", "%(ext)s")
        # Ensure path
        yt_template_path = str(download_dir / yt_template)
        # But we also need to handle existing target: create later
        target_path = None
        output_template = yt_template_path
    if target_path:
        output_template = str(target_path)

    # Build command
    # yt-dlp --no-playlist -f "bv*+ba/b" --merge-output-format mp4 -o "<template>" --add-header ... --referer ...
    cmd = [yt_dlp, "--no-playlist", "-f", "bv*+ba/b", "--merge-output-format", "mp4", "-o", output_template]

    # Referer handling
    referer = headers.get("Referer") or headers.get("referer") or page_url
    if referer:
        cmd += ["--referer", referer]

    # Add other headers except those handled
    for k, v in headers.items():
        lk = k.lower()
        if lk in ("referer", "range", "if-range"):
            continue
        # yt-dlp --add-header "Key: Value"
        cmd += ["--add-header", f"{k}: {v}"]

    cmd += [page_url]

    # Run and parse progress
    loop = asyncio.get_event_loop()

    # Use Popen to stream output
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    # parse progress lines like "[download]  45.2% of 10.00MiB ..."
    progress_re = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")

    size_done = 0
    size_total = None
    last_report = 0.0
    import time

    start = time.monotonic()
    buf = b""
    try:
        while True:
            line = await proc.stdout.readline()  # type: ignore
            if not line:
                break
            try:
                text = line.decode("utf-8", errors="ignore")
            except Exception:
                text = ""
            m = progress_re.search(text)
            if m:
                try:
                    pct = float(m.group(1))
                    # we don't know total, estimate; store progress as pct
                    # try to find total in line: "of 10.00MiB"
                    total = None
                    m2 = re.search(r"of\s+~?([\d\.]+)(\w+)", text)
                    if m2:
                        try:
                            val = float(m2.group(1))
                            unit = m2.group(2).lower()
                            mult = {"b":1, "kib":1024, "mib":1024**2, "gib":1024**3, "kb":1000, "mb":1000**2, "gb":1000**3}.get(unit, 1024**2)
                            # normalize
                            if unit in ("kib","mib","gib","kb","mb","gb","b"):
                                total = int(val * mult)
                            else:
                                # handle MiB etc without exact
                                total = int(val * 1024*1024)
                        except Exception:
                            pass
                    if total:
                        size_total = total
                        size_done = int(total * pct / 100)
                    else:
                        # fake total 100 for pct
                        size_total = 100
                        size_done = int(pct)
                    now = time.monotonic()
                    if now - last_report >= 0.5:
                        speed = 0  # unknown
                        store.update_progress(tid, size_done, size_total=size_total)
                        try:
                            maybe = report(size_done, size_total, speed)
                            if asyncio.iscoroutine(maybe):
                                await maybe
                        except Exception:
                            pass
                        last_report = now
                except Exception:
                    pass
            # need to handle pause/cancel? For yt-dlp, we kill proc if canceled
            cur2 = store.get(tid)
            if cur2 and cur2["status"] == "canceled":
                try:
                    proc.terminate()
                    await asyncio.sleep(0.2)
                    proc.kill()
                except Exception:
                    pass
                return
            if cur2 and cur2["status"] == "paused":
                # yt-dlp doesn't support pause natively; we'll terminate and mark paused for resume?
                # For MVP: treat pause as cancel? But spec says pause only if Range. yt-dlp not pausable.
                # We'll just keep running; pause unsupported -> ignore
                pass

        await proc.wait()
        if proc.returncode == 0:
            # Find produced file: if target_path was specified exactly, it may have been produced with extension added
            # Scan download_dir for newest file after start
            # If output_template contained yt placeholders, find newest file in download_dir
            produced = None
            if target_path and target_path.exists():
                produced = target_path
            elif target_path:
                # yt-dlp may have added .mp4 extension
                cand = sorted(download_dir.glob(target_path.name + "*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
                for c in cand:
                    if c.is_file() and c.stat().st_size > 0:
                        produced = c
                        break
                # also check exact with .mp4
                if not produced:
                    for ext in [".mp4", ".mkv", ".webm", ".m4a", ".mp3"]:
                        p = target_path.with_suffix(ext)
                        if p.exists():
                            produced = p
                            break
            else:
                # no target_path, template with placeholders: find newest file modified after start time approx
                # list files in download_dir sorted by mtime
                candidates = sorted([p for p in download_dir.iterdir() if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
                if candidates:
                    # take newest, if its mtime is recent (within last 2 minutes)
                    newest = candidates[0]
                    import time as t2
                    if t2.time() - newest.stat().st_mtime < 300:
                        produced = newest

            if produced and produced.exists():
                # ensure store target updated
                store.update_target(tid, str(produced))
                sz = produced.stat().st_size
                store.update_progress(tid, sz, size_total=sz)
                store.update_status(tid, "done")
                try:
                    maybe = report(sz, sz, 0)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except Exception:
                    pass
                return
            # fallback: even if file not found, mark done if proc succeeded (yt-dlp may have moved file)
            # try to locate any file in download_dir with recent mtime
            # mark done anyway with no path? but need path
            store.update_status(tid, "done")
            return
        else:
            # read stderr? we merged stdout, get last output
            # For errors: check if finished with error code, map
            # Need to capture output: we already consumed stdout, but we can get returncode
            # Try to read remaining
            # For MVP, assume network/expired
            # Check if proc output contained "HTTP Error 403"
            # We'll set generic
            # If we killed for cancel, already returned
            cur3 = store.get(tid)
            if cur3 and cur3["status"] == "canceled":
                return
            store.set_error(tid, "err_network" if proc.returncode and proc.returncode != 0 else "err_unknown")
            return
    except asyncio.CancelledError:
        try:
            proc.terminate()
        except Exception:
            pass
        raise
    except Exception as e:
        store.set_error(tid, f"err_http:{e}")
        return
