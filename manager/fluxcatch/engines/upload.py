from __future__ import annotations

from pathlib import Path

from .. import config as cfg
from .base import sanitize_filename, unique_path


# This engine is not "run" via tasks.py directly for pushing chunks;
# Instead, API endpoints /chunks and /finish handle writes.
# However, tasks.py will create tasks of kind recorder/browser_proxy and set them active,
# then wait for upload to finish. We provide a helper to initialize file paths.

def init_upload_task(task: dict, store) -> Path:
    tid = task["id"]
    kind = task["kind"]
    title = task.get("title") or f"fluxcatch-{tid[:6]}"
    # Determine extension
    if kind == "recorder":
        ext = ".webm"
    else:  # browser_proxy
        # try to infer from mime or title
        mime = task.get("mime")
        if mime and "mp4" in mime:
            ext = ".mp4"
        elif title and "." in title:
            ext = Path(title).suffix or ".bin"
        else:
            ext = ".bin"
        if mime and not Path(title or "").suffix:
            from .base import mime_to_ext
            ext = mime_to_ext(mime)

    download_dir = Path(cfg.load_config().get("download_dir") or str(Path.home() / "Downloads"))
    download_dir.mkdir(parents=True, exist_ok=True)

    # sanitize title
    if kind == "recorder":
        # title may be page title
        safe = sanitize_filename(title)
        if not safe.lower().endswith(ext):
            safe = safe + ext
    else:
        safe = sanitize_filename(title if "." in (title or "") else f"{title}{ext}" if title else f"fluxcatch-{tid[:6]}{ext}")

    target = store.get(tid).get("target_path") if store.get(tid) else None
    if target:
        target_path = Path(target)
    else:
        target_path = unique_path(download_dir, safe)
        store.update_target(tid, str(target_path))

    part_path = target_path.with_suffix(target_path.suffix + ".part")
    # ensure status active (or pending -> active)
    cur = store.get(tid)
    if cur and cur["status"] == "pending":
        try:
            store.update_status(tid, "active")
        except Exception:
            pass
    # create empty part file if not exists
    if not part_path.exists():
        part_path.touch()
        store.update_progress(tid, 0, size_total=None, target_path=str(target_path))

    return part_path


async def run(task: dict, store, report):
    # For upload engines, tasks.py just waits until finish/error/cancel; no actual download loop.
    # This run is a no-op that ensures file initialized and then idles until store status changes to done/error/canceled.
    # We set active and return immediately, letting API drive progress.
    tid = task["id"]
    init_upload_task(task, store)
    # Keep task active while uploading; the API will update progress and eventually set done via /finish.
    # So this engine does nothing else; just ensures status is active.
    cur = store.get(tid)
    if cur and cur["status"] == "pending":
        try:
            store.update_status(tid, "active")
        except Exception:
            pass
    # Wait loop? Actually we don't need to block; tasks.py will handle waiting via WS status?
    # For consistency, we just return and let uploads happen via HTTP.
    return
