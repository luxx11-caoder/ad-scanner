import asyncio
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from pathlib import Path

async def make_file_server(files):
    app = web.Application()
    async def handler(request):
        p = request.path.lstrip("/")
        if p not in files:
            return web.Response(status=404)
        data = files[p]
        range_hdr = request.headers.get("Range")
        if range_hdr and range_hdr.startswith("bytes="):
            try:
                start = int(range_hdr.split("=")[1].split("-")[0])
                sliced = data[start:]
                headers = {"Content-Range": f"bytes {start}-{len(data)-1}/{len(data)}", "Content-Length": str(len(sliced)), "Content-Type":"video/mp4", "Accept-Ranges":"bytes"}
                if p=="with_cd.mp4":
                    headers["Content-Disposition"] = 'attachment; filename="custom.mp4"'
                return web.Response(body=sliced, status=206, headers=headers)
            except Exception:
                pass
        headers = {"Content-Length": str(len(data)), "Content-Type":"video/mp4", "Accept-Ranges":"bytes"}
        if p=="with_cd.mp4":
            headers["Content-Disposition"] = 'attachment; filename="custom.mp4"'
        return web.Response(body=data, headers=headers)
    app.router.add_get("/{tail:.*}", handler)
    server = TestServer(app)
    await server.start_server()
    client = TestClient(server)
    await client.start_server()
    return server, client, str(server.make_url("/"))

@pytest.mark.asyncio
async def test_direct_download_simple(tmp_dirs, store):
    from fluxcatch.server import create_app
    import fluxcatch.pairing as pairing
    tmp_files = {"video.mp4": b"x"*1024*10}
    fserver, fclient, base_url = await make_file_server(tmp_files)
    video_url = base_url + "video.mp4"
    app = create_app(store)
    server = TestServer(app)
    await server.start_server()
    c = TestClient(server)
    await c.start_server()
    origin="chrome-extension://directtest"
    pairing.add_origin(origin)
    headers={"Origin":origin}
    resp = await c.request("POST","/api/tasks", json={"kind":"direct","url":video_url,"title":"testvid"}, headers=headers)
    assert resp.status==201
    tid = (await resp.json())["id"]
    for _ in range(30):
        await asyncio.sleep(0.2)
        resp = await c.request("GET", f"/api/tasks/{tid}", headers=headers)
        data = await resp.json()
        if data["status"]=="done":
            break
    else:
        pytest.fail(f"task not done, status {data['status']} error {data.get('error')}")
    assert data["target_path"]
    p = Path(data["target_path"])
    assert p.exists()
    assert p.stat().st_size==1024*10
    await c.close()
    await server.close()
    await fclient.close()
    await fserver.close()

@pytest.mark.asyncio
async def test_direct_resume(tmp_dirs, store):
    """Test reprise Range en créant un .part partiel puis en relançant le moteur direct."""
    from fluxcatch.engines import direct as direct_engine
    import fluxcatch.config as cfg
    # File server
    content = b"a"*5000
    fserver, fclient, base_url = await make_file_server({"resumable.mp4": content})
    video_url = base_url + "resumable.mp4"
    # Crée tâche via store directement
    task = store.create_task(kind="direct", source_url=video_url, title="resume-test")
    tid = task["id"]
    # Détermine target path manuellement via store + download_dir
    download_dir = Path(cfg.load_config()["download_dir"])
    download_dir.mkdir(parents=True, exist_ok=True)
    # Simule ce que direct fait: dérive filename et crée part avec moitié
    # On laisse direct créer le fichier la première fois partiellement en simulant interruption
    # Approach: crée part file avec 2500 bytes manuellement, puis lance direct.run -> doit reprendre
    # D'abord, on doit connaître le target_path que direct va choisir. On peut le pré-créer via store update_target
    from fluxcatch.engines.base import unique_path, derive_filename, mime_to_ext
    fname = derive_filename(task, final_url=video_url, mime="video/mp4")
    if not Path(fname).suffix:
        fname = fname + ".mp4"
    target = unique_path(download_dir, fname)
    store.update_target(tid, str(target))
    part = target.with_suffix(target.suffix + ".part")
    part.write_bytes(content[:2500])
    store.update_progress(tid, 2500, size_total=5000, target_path=str(target))
    # Passe en paused pour autoriser reprise (direct accepte reprise depuis paused/active)
    store.update_status(tid, "paused")
    # Lance moteur (doit détecter part 2500 et faire Range)
    async def report(done, total, speed):
        pass
    await direct_engine.run(store.get(tid), store, report)
    # Vérifie
    final = store.get(tid)
    assert final["status"]=="done"
    assert target.exists()
    assert target.read_bytes()==content
    await fclient.close()
    await fserver.close()

@pytest.mark.asyncio
async def test_content_disposition(tmp_dirs, store):
    from fluxcatch.server import create_app
    tmp_files = {"with_cd.mp4": b"hello world"}
    fserver, fclient, base_url = await make_file_server(tmp_files)
    video_url = base_url + "with_cd.mp4"
    import fluxcatch.pairing as pairing
    app = create_app(store)
    server = TestServer(app); await server.start_server()
    c = TestClient(server); await c.start_server()
    origin="chrome-extension://cdtest"
    pairing.add_origin(origin)
    headers={"Origin":origin}
    resp = await c.request("POST","/api/tasks", json={"kind":"direct","url":video_url,"title":"ignored"}, headers=headers)
    tid = (await resp.json())["id"]
    for _ in range(30):
        await asyncio.sleep(0.2)
        resp = await c.request("GET", f"/api/tasks/{tid}", headers=headers)
        data = await resp.json()
        if data["status"]=="done":
            break
    assert data["status"]=="done"
    assert Path(data["target_path"]).name=="custom.mp4"
    await c.close(); await server.close()
    await fclient.close(); await fserver.close()

@pytest.mark.asyncio
async def test_403_handling(tmp_dirs, store):
    from aiohttp import web
    async def handler(request):
        return web.Response(status=403)
    app = web.Application()
    app.router.add_get("/{tail:.*}", handler)
    fserver = TestServer(app); await fserver.start_server()
    fclient = TestClient(fserver); await fclient.start_server()
    url = str(fserver.make_url("/forbidden.mp4"))
    from fluxcatch.server import create_app
    import fluxcatch.pairing as pairing
    daemon_app = create_app(store)
    server = TestServer(daemon_app); await server.start_server()
    c = TestClient(server); await c.start_server()
    origin="chrome-extension://403test"
    pairing.add_origin(origin)
    headers={"Origin":origin}
    resp = await c.request("POST","/api/tasks", json={"kind":"direct","url":url,"title":"forbidden"}, headers=headers)
    tid=(await resp.json())["id"]
    for _ in range(30):
        await asyncio.sleep(0.2)
        resp = await c.request("GET", f"/api/tasks/{tid}", headers=headers)
        data = await resp.json()
        if data["status"]=="error":
            break
    assert data["status"]=="error"
    assert "err_forbidden" in data["error"]
    await c.close(); await server.close()
    await fclient.close(); await fserver.close()
