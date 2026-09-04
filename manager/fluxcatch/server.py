from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from pathlib import Path

from aiohttp import web, WSMsgType

from . import config as cfg
from . import pairing as pairing_mod
from .__init__ import __version__
from .store import Store
from . import tasks as tasks_mgr
from .engines.upload import init_upload_task

log = logging.getLogger("fluxcatch")

# For WS broadcast
_ws_clients: set[web.WebSocketResponse] = set()


async def broadcast(event: dict):
    dead = set()
    for ws in list(_ws_clients):
        try:
            await ws.send_str(json.dumps(event, ensure_ascii=False))
        except Exception:
            dead.add(ws)
    for ws in dead:
        _ws_clients.discard(ws)


def _is_allowed_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    # Allow requests without Origin (curl, webui via same origin) ? WebUI is served from same daemon, Origin may be None or same host. Spec says pages web malveillantes can't pilot, but webui same origin should be allowed.
    # We treat no Origin or Origin == http://127.0.0.1:8765 as allowed.
    # But after pairing, only allowed_origins for extension. For webui, we allow same-origin without pairing.
    if origin is None:
        # Check that request is from localhost directly (no Origin header)
        # Allow for webui and direct curl
        return True
    # Same origin (webui)
    cfg_data = cfg.load_config()
    host = cfg_data.get("host", "127.0.0.1")
    port = cfg_data.get("port", 8765)
    local_origins = {f"http://{host}:{port}", f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    if origin in local_origins:
        return True
    # Extension origins
    if pairing_mod.is_origin_allowed(origin):
        return True
    return False


@web.middleware
async def pairing_middleware(request: web.Request, handler):
    # Paths that are always allowed (even without pairing)
    allowed_without_pair = {"/api/hello", "/api/pair"}
    # Also allow CORS preflight for these
    path = request.path
    # Normalize path: /api/pair includes POST and DELETE but spec says only hello and pair are accessible without pairing
    if path in allowed_without_pair or path.startswith("/api/hello") or path.startswith("/api/pair"):
        # Add CORS header for these
        resp = await handler(request)
        # Ensure ACAO *
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        return resp

    # For OPTIONS preflight, handle CORS
    if request.method == "OPTIONS":
        origin = request.headers.get("Origin")
        # If allowed, return 204 with CORS
        if _is_allowed_origin(request):
            resp = web.Response(status=204)
            if origin:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Vary"] = "Origin"
            else:
                resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Origin"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            return resp
        else:
            # still allow hello/pair preflight? already handled above
            return web.Response(status=403, text="Origine non autorisée")

    if not _is_allowed_origin(request):
        # Return 403, but still add CORS to allow browser to read error
        origin = request.headers.get("Origin")
        headers = {}
        if origin:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
        else:
            headers["Access-Control-Allow-Origin"] = "*"
        return web.json_response({"error": "Origine non autorisée, veuillez lier l'extension"}, status=403, headers=headers)

    # Add CORS echo for allowed origins
    resp = await handler(request)
    origin = request.headers.get("Origin")
    if origin and pairing_mod.is_origin_allowed(origin):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    elif origin and origin in {f"http://{cfg.load_config().get('host','127.0.0.1')}:{cfg.load_config().get('port',8765)}", f"http://127.0.0.1:{cfg.load_config().get('port',8765)}", f"http://localhost:{cfg.load_config().get('port',8765)}"}:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    return resp


def create_app(store: Store | None = None) -> web.Application:
    if store is None:
        store = Store()
    app = web.Application(middlewares=[pairing_middleware])
    app["store"] = store

    # init tasks manager broadcast
    tasks_mgr.init_tasks(store, broadcast)

    # Routes
    app.router.add_get("/api/hello", hello_handler)
    app.router.add_post("/api/pair", pair_handler)
    app.router.add_delete("/api/pair", unpair_handler)
    app.router.add_options("/api/pair", options_handler)
    app.router.add_options("/api/hello", options_handler)
    app.router.add_get("/api/capabilities", capabilities_handler)
    app.router.add_get("/api/settings", get_settings_handler)
    app.router.add_put("/api/settings", put_settings_handler)
    app.router.add_options("/api/settings", options_handler)
    app.router.add_get("/api/tasks", list_tasks_handler)
    app.router.add_post("/api/tasks", create_task_handler)
    app.router.add_options("/api/tasks", options_handler)
    app.router.add_get("/api/tasks/{id}", get_task_handler)
    app.router.add_post("/api/tasks/{id}/cancel", cancel_handler)
    app.router.add_post("/api/tasks/{id}/retry", retry_handler)
    app.router.add_post("/api/tasks/{id}/pause", pause_handler)
    app.router.add_post("/api/tasks/{id}/resume", resume_handler)
    app.router.add_post("/api/tasks/{id}/open_folder", open_folder_handler)
    app.router.add_post("/api/tasks/{id}/chunks", chunks_handler)
    app.router.add_post("/api/tasks/{id}/finish", finish_handler)
    app.router.add_options("/api/tasks/{id}/chunks", options_handler)
    app.router.add_options("/api/tasks/{id}/finish", options_handler)
    app.router.add_get("/api/ws", ws_handler)

    # CORS preflight for tasks subpaths
    app.router.add_route("OPTIONS", "/api/tasks/{id}/{tail:.*}", options_handler)

    # Static webui
    webui_path = Path(__file__).parent.parent / "webui"
    if webui_path.is_dir():
        async def index_handler(request):
            return web.FileResponse(str(webui_path / "index.html"))
        # exact "/" must be before static catch-all
        app.router.add_get("/", index_handler)
        app.router.add_static("/", path=str(webui_path), name="webui", show_index=True)

    return app


async def options_handler(request):
    origin = request.headers.get("Origin")
    headers = {}
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    else:
        headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Headers"] = "Content-Type, Origin"
    headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return web.Response(status=204, headers=headers)


async def hello_handler(request):
    store: Store = request.app["store"]  # noqa: unused
    return web.json_response({"app": "fluxcatch", "version": __version__, "paired": pairing_mod.is_paired()})


async def pair_handler(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "JSON invalide"}, status=400)
    code = data.get("code")
    if not code or not isinstance(code, str):
        return web.json_response({"error": "code requis"}, status=400)
    if not pairing_mod.verify_code(code):
        return web.json_response({"error": "code invalide"}, status=403)
    origin = request.headers.get("Origin")
    if not origin:
        return web.json_response({"error": "Origin requis"}, status=400)
    pairing_mod.add_origin(origin)
    # broadcast pairing changed
    await broadcast({"type": "pairing_changed"})
    return web.json_response({"ok": True, "origin": origin})


async def unpair_handler(request):
    origin = request.headers.get("Origin")
    if not origin:
        return web.json_response({"error": "Origin requis"}, status=400)
    pairing_mod.remove_origin(origin)
    await broadcast({"type": "pairing_changed"})
    return web.json_response({"ok": True})


async def capabilities_handler(request):
    ffmpeg = shutil.which("ffmpeg") is not None
    yt = shutil.which("yt-dlp") or shutil.which("yt_dlp")
    resp = {"ffmpeg": ffmpeg, "yt_dlp": bool(yt)}
    if yt:
        resp["yt_dlp_path"] = yt
    return web.json_response(resp)


async def get_settings_handler(request):
    cfg_data = cfg.load_config()
    return web.json_response(cfg_data)


async def put_settings_handler(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "JSON invalide"}, status=400)
    cfg_data = cfg.load_config()
    # only allow download_dir and filename_template
    if "download_dir" in data:
        dd = str(data["download_dir"])
        # ensure path exists or can be created?
        p = Path(dd)
        try:
            p.mkdir(parents=True, exist_ok=True)
            if not p.is_dir():
                return web.json_response({"error": "download_dir invalide"}, status=400)
            cfg_data["download_dir"] = str(p)
        except Exception as e:
            return web.json_response({"error": f"download_dir invalide: {e}"}, status=400)
    if "filename_template" in data:
        ft = str(data["filename_template"])
        if "{title}" not in ft or "{ext}" not in ft:
            return web.json_response({"error": "filename_template doit contenir {title} et {ext}"}, status=400)
        cfg_data["filename_template"] = ft
    if "concurrency" in data:
        try:
            conc = int(data["concurrency"])
            if not (1 <= conc <= 10):
                raise ValueError()
            cfg_data["concurrency"] = conc
        except Exception:
            return web.json_response({"error": "concurrency invalide (1-10)"}, status=400)
    cfg.save_config(cfg_data)
    await broadcast({"type": "settings_changed", "settings": cfg_data})
    return web.json_response(cfg_data)


async def list_tasks_handler(request):
    store: Store = request.app["store"]
    tasks = store.list()
    return web.json_response(tasks)


async def create_task_handler(request):
    store: Store = request.app["store"]
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "JSON invalide"}, status=400)
    kind = data.get("kind")
    if not kind or kind not in {"direct", "hls", "ytdlp", "recorder", "browser_proxy"}:
        return web.json_response({"error": "kind invalide (direct|hls|ytdlp|recorder|browser_proxy)"}, status=400)

    # Validate kind-specific fields
    url = data.get("url")
    page_url = data.get("page_url")
    title = data.get("title")
    headers = data.get("headers") or {}
    extra = data.get("extra") or {}
    if not isinstance(headers, dict):
        return web.json_response({"error": "headers doit être un objet"}, status=400)

    source_url = url or page_url or ""
    # For ytdlp, page_url required; for direct/hls, url required; for recorder/browser_proxy, url may be dummy?
    if kind in ("direct", "hls", "browser_proxy") and not url:
        return web.json_response({"error": "url requis pour ce kind"}, status=400)
    if kind == "ytdlp" and not page_url:
        # allow url as page_url fallback
        if url:
            page_url = url
            source_url = url
        else:
            return web.json_response({"error": "page_url requis pour ytdlp"}, status=400)
    if kind in ("recorder", "browser_proxy") and not url:
        # recorder uses page_url as source, but we need source_url; use placeholder
        source_url = page_url or f"upload://{kind}"
        if not source_url or source_url.startswith("upload://") and kind == "recorder":
            source_url = f"recorder://{title or 'video'}"

    # For recorder/browser_proxy, we need to set status pending and target path soon
    task = store.create_task(kind=kind, source_url=source_url, page_url=page_url, title=title, headers=headers, extra=extra)
    # Update mime if provided in extra?
    await broadcast({"type": "task_state", "task_id": task["id"], "status": task["status"]})

    # Schedule download except for upload kinds where we init file and wait
    if kind in ("recorder", "browser_proxy"):
        # init upload file
        try:
            init_upload_task(task, store)
        except Exception as e:
            log.exception("init upload failed: %s", e)
        # Still broadcast state
        cur = store.get(task["id"])
        await broadcast({"type": "task_state", "task_id": task["id"], "status": cur["status"] if cur else "pending"})
    else:
        tasks_mgr.schedule_task(task["id"])

    return web.json_response({"id": task["id"]}, status=201)


async def get_task_handler(request):
    store: Store = request.app["store"]
    tid = request.match_info["id"]
    task = store.get(tid)
    if not task:
        return web.json_response({"error": "tâche non trouvée"}, status=404)
    return web.json_response(task)


async def cancel_handler(request):
    store: Store = request.app["store"]
    tid = request.match_info["id"]
    task = store.get(tid)
    if not task:
        return web.json_response({"error": "tâche non trouvée"}, status=404)
    try:
        await tasks_mgr.cancel_task(tid)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=409)
    return web.json_response({"ok": True})


async def retry_handler(request):
    store: Store = request.app["store"]
    tid = request.match_info["id"]
    task = store.get(tid)
    if not task:
        return web.json_response({"error": "tâche non trouvée"}, status=404)
    try:
        await tasks_mgr.retry_task(tid)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"ok": True})


async def pause_handler(request):
    store: Store = request.app["store"]
    tid = request.match_info["id"]
    task = store.get(tid)
    if not task:
        return web.json_response({"error": "tâche non trouvée"}, status=404)
    try:
        await tasks_mgr.pause_task(tid)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"ok": True})


async def resume_handler(request):
    store: Store = request.app["store"]
    tid = request.match_info["id"]
    task = store.get(tid)
    if not task:
        return web.json_response({"error": "tâche non trouvée"}, status=404)
    try:
        await tasks_mgr.resume_task(tid)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"ok": True})


async def open_folder_handler(request):
    store: Store = request.app["store"]
    tid = request.match_info["id"]
    task = store.get(tid)
    if not task:
        return web.json_response({"error": "tâche non trouvée"}, status=404)
    target = task.get("target_path")
    if not target:
        # open download_dir
        cfg_data = cfg.load_config()
        target = cfg_data.get("download_dir") or str(Path.home() / "Downloads")
    folder = str(Path(target).parent) if Path(target).is_file() or Path(target).suffix else target
    # Try xdg-open, non-blocking
    try:
        subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return web.json_response({"ok": True, "folder": folder})


async def chunks_handler(request):
    store: Store = request.app["store"]
    tid = request.match_info["id"]
    task = store.get(tid)
    if not task:
        return web.json_response({"error": "tâche non trouvée"}, status=404)
    if task["kind"] not in ("recorder", "browser_proxy"):
        return web.json_response({"error": "chunks réservé à recorder/browser_proxy"}, status=400)
    if task["status"] not in ("pending", "active"):
        return web.json_response({"error": f"statut {task['status']} ne permet pas l'upload"}, status=409)

    # Ensure part file exists
    target = task.get("target_path")
    if not target:
        # init now
        part_path = init_upload_task(task, store)
    else:
        part_path = Path(target).with_suffix(Path(target).suffix + ".part")
        if not part_path.exists():
            # create if missing
            part_path.parent.mkdir(parents=True, exist_ok=True)
            part_path.touch()

    data = await request.read()  # raw binary
    if not data:
        return web.json_response({"error": "chunk vide"}, status=400)
    # Append
    try:
        with open(part_path, "ab") as f:
            f.write(data)
        new_size = part_path.stat().st_size
        store.update_progress(tid, new_size)
        await broadcast({"type": "task_progress", "task_id": tid, "size_done": new_size, "size_total": task.get("size_total"), "speed": 0})
        # ensure status active
        cur = store.get(tid)
        if cur and cur["status"] == "pending":
            try:
                store.update_status(tid, "active")
                await broadcast({"type": "task_state", "task_id": tid, "status": "active"})
            except Exception:
                pass
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"ok": True, "size_done": new_size})


async def finish_handler(request):
    store: Store = request.app["store"]
    tid = request.match_info["id"]
    task = store.get(tid)
    if not task:
        return web.json_response({"error": "tâche non trouvée"}, status=404)
    if task["kind"] not in ("recorder", "browser_proxy"):
        return web.json_response({"error": "finish réservé à recorder/browser_proxy"}, status=400)

    target = task.get("target_path")
    if not target:
        return web.json_response({"error": "pas de cible"}, status=400)
    part_path = Path(target).with_suffix(Path(target).suffix + ".part")
    final_path = Path(target)

    # Optional bytes in body: {"bytes":123} - but we just finalize
    try:
        _ = await request.json()
    except Exception:
        pass

    if not part_path.exists():
        store.set_error(tid, "err_empty")
        await broadcast({"type": "task_state", "task_id": tid, "status": "error", "error": "err_empty"})
        return web.json_response({"error": "fichier vide"}, status=400)
    size = part_path.stat().st_size
    if size == 0:
        # remove empty part
        try:
            part_path.unlink()
        except Exception:
            pass
        store.set_error(tid, "err_empty")
        await broadcast({"type": "task_state", "task_id": tid, "status": "error", "error": "err_empty"})
        return web.json_response({"error": "err_empty"}, status=400)
    # rename
    try:
        if final_path.exists():
            # avoid collision already handled at creation but still
            from .engines.base import unique_path
            final_path = unique_path(final_path.parent, final_path.name)
            store.update_target(tid, str(final_path))
        part_path.rename(final_path)
    except Exception as e:
        store.set_error(tid, f"err_merge:{e}")
        await broadcast({"type": "task_state", "task_id": tid, "status": "error", "error": f"err_merge:{e}"})
        return web.json_response({"error": str(e)}, status=500)

    store.update_progress(tid, size, size_total=size, target_path=str(final_path))
    try:
        store.update_status(tid, "done")
    except Exception:
        # if active -> done allowed
        store.conn.execute("UPDATE tasks SET status='done', updated_at=? WHERE id=?", (store._now() if hasattr(store, '_now') else __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(), tid))
        store.conn.commit()
    await broadcast({"type": "task_state", "task_id": tid, "status": "done"})
    await broadcast({"type": "task_progress", "task_id": tid, "size_done": size, "size_total": size, "speed": 0})
    return web.json_response({"ok": True, "size": size, "path": str(final_path)})


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    _ws_clients.add(ws)
    # Send initial settings? not needed
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # ignore incoming, but could handle ping
                pass
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        _ws_clients.discard(ws)
    return ws
