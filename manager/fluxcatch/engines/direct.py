from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable

import aiohttp

from .. import config as cfg
from .base import derive_filename, filter_headers, mime_to_ext, unique_path


async def run(task: dict, store, report: Callable, session: aiohttp.ClientSession | None = None):
    """
    task: dict from store.get
    report: callable sync or async (size_done, size_total, speed)
    """
    tid = task["id"]
    source_url = task["source_url"]
    headers = task.get("headers") or {}
    # filter only allowed headers
    req_headers = filter_headers(headers)

    download_dir = Path(cfg.load_config().get("download_dir") or cfg._resolve_download_dir())  # type: ignore
    download_dir.mkdir(parents=True, exist_ok=True)

    # Determine target path: if already has target_path and .part exists, resume
    existing_target = task.get("target_path")
    part_path: Path | None = None
    target_path: Path | None = None

    if existing_target:
        target_path = Path(existing_target)
        part_path = target_path.with_suffix(target_path.suffix + ".part") if not str(target_path).endswith(".part") else target_path
        # if target already done? skip
        if target_path.exists() and task.get("status") == "done":
            return
    else:
        # will determine after HEAD? but we need filename early; use fallback
        # create placeholder unique path with .part
        # we derive filename lazily after response headers, so create temp
        part_path = None
        target_path = None

    # Determine resume offset
    resume_from = 0
    if part_path and part_path.exists():
        resume_from = part_path.stat().st_size
    elif target_path and target_path.exists():
        # if target exists without .part and status not done, treat as resume?
        pass

    own_session = False
    if session is None:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=60)
        session = aiohttp.ClientSession(timeout=timeout)
        own_session = True

    try:
        # Prepare headers for Range
        attempt = 0
        max_attempts = 3
        backoff = [2, 5, 5]
        while True:
            attempt += 1
            try:
                hdrs = dict(req_headers)
                if resume_from > 0:
                    hdrs["Range"] = f"bytes={resume_from}-"

                async with session.get(source_url, headers=hdrs, allow_redirects=True) as resp:
                    # handle errors
                    if resp.status in (401, 403):
                        store.set_error(tid, "err_forbidden")
                        return
                    if resp.status == 404:
                        store.set_error(tid, "err_gone")
                        return
                    if resp.status >= 500:
                        raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status)

                    # Determine filename if not yet
                    mime = resp.headers.get("Content-Type")
                    cd = resp.headers.get("Content-Disposition")
                    final_url = str(resp.url)

                    if target_path is None or part_path is None:
                        filename = derive_filename(task, final_url=final_url, mime=mime, content_disposition=cd)
                        # ensure extension: if filename lacks ext and mime known, add
                        if not Path(filename).suffix and mime:
                            filename = filename + mime_to_ext(mime)
                        target_path = unique_path(download_dir, filename)
                        part_path = target_path.with_suffix(target_path.suffix + ".part")
                        # if resume attempted but we didn't have part_path before, resume_from stays 0
                        store.update_target(tid, str(target_path))
                        store.update_progress(tid, resume_from, target_path=str(target_path), mime=mime)
                    else:
                        # update mime if known
                        if mime:
                            store.update_progress(tid, resume_from, mime=mime)

                    # Check Range support
                    is_partial = resp.status == 206
                    if resume_from > 0 and not is_partial:
                        # server doesn't support range, restart from 0
                        resume_from = 0
                        # truncate part file
                        if part_path.exists():
                            part_path.unlink()
                        # need to re-request without Range
                        if attempt == 1:
                            # retry immediately without Range header
                            hdrs.pop("Range", None)
                            # re-enter loop: we already have response, but we need to restart loop
                            # To avoid duplicating logic, close this resp and retry
                            continue

                    # Determine total size
                    clen = resp.headers.get("Content-Length")
                    content_range = resp.headers.get("Content-Range")
                    size_total = None
                    if content_range and "/" in content_range:
                        try:
                            size_total = int(content_range.split("/")[-1])
                        except Exception:
                            pass
                    elif clen is not None:
                        try:
                            size_total = int(clen) + (resume_from if is_partial else 0)
                        except Exception:
                            size_total = None
                    else:
                        size_total = task.get("size_total")

                    # Check disk space? skip for MVP

                    # Transition to active if needed
                    cur = store.get(tid)
                    if cur and cur["status"] in ("pending", "paused"):
                        try:
                            store.update_status(tid, "active")
                        except Exception:
                            pass

                    # Stream to file
                    mode = "ab" if (is_partial and resume_from > 0) else "wb"
                    # ensure parent
                    part_path.parent.mkdir(parents=True, exist_ok=True)
                    downloaded = resume_from
                    start = time.monotonic()
                    last_report = start
                    last_done = downloaded
                    chunk_size = 256 * 1024

                    # Need to handle pause/cancel during download: check store status periodically
                    with open(part_path, mode) as f:
                        async for chunk in resp.content.iter_chunked(chunk_size):
                            # check pause/cancel
                            cur = store.get(tid)
                            if cur is None:
                                return
                            if cur["status"] == "paused":
                                # graceful pause: stop writing, keep .part
                                store.update_progress(tid, downloaded, size_total=size_total)
                                return
                            if cur["status"] == "canceled":
                                try:
                                    f.close()
                                except Exception:
                                    pass
                                if part_path.exists():
                                    try:
                                        part_path.unlink()
                                    except Exception:
                                        pass
                                return
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                now = time.monotonic()
                                if now - last_report >= 0.5:
                                    elapsed = now - start
                                    # speed bytes/s
                                    speed = (downloaded - last_done) / (now - last_report) if (now - last_report) > 0 else 0
                                    # also average? use instantaneous chunk speed
                                    store.update_progress(tid, downloaded, size_total=size_total)
                                    try:
                                        maybe = report(downloaded, size_total, speed)
                                        if asyncio.iscoroutine(maybe):
                                            await maybe
                                    except Exception:
                                        pass
                                    last_report = now
                                    last_done = downloaded

                    # finalize
                    store.update_progress(tid, downloaded, size_total=size_total or downloaded)
                    try:
                        maybe = report(downloaded, size_total or downloaded, 0)
                        if asyncio.iscoroutine(maybe):
                            await maybe
                    except Exception:
                        pass

                    # fsync and rename
                    try:
                        # fsync file is already closed; reopen to fsync dir? just rename
                        part_path.rename(target_path)
                    except Exception as e:
                        store.set_error(tid, f"err_merge:{e}")
                        return

                    store.update_status(tid, "done")
                    store.update_progress(tid, downloaded, size_total=downloaded, target_path=str(target_path))
                    return

            except asyncio.CancelledError:
                raise
            except Exception as e:
                # network errors retry
                if attempt < max_attempts and not isinstance(e, (ValueError,)):
                    # check if task was paused/canceled -> don't retry
                    cur = store.get(tid)
                    if cur and cur["status"] in ("paused", "canceled"):
                        return
                    await asyncio.sleep(backoff[min(attempt - 1, len(backoff) - 1)])
                    # on retry, keep resume_from as current file size
                    if part_path and part_path.exists():
                        resume_from = part_path.stat().st_size
                    continue
                # final error
                # map to typed error
                msg = str(e)
                if "403" in msg or "401" in msg:
                    store.set_error(tid, "err_forbidden")
                elif "404" in msg:
                    store.set_error(tid, "err_gone")
                elif "No space" in msg or "ENOSPC" in msg:
                    store.set_error(tid, "err_space")
                else:
                    # if already set to paused/canceled, don't overwrite
                    cur2 = store.get(tid)
                    if cur2 and cur2["status"] in ("paused", "canceled", "done"):
                        return
                    store.set_error(tid, "err_network" if "Client" in type(e).__name__ or "Timeout" in type(e).__name__ or "Connection" in msg else f"err_http:{e}")
                return
    finally:
        if own_session and session:
            await session.close()
