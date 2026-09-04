import pytest
import pytest_asyncio

@pytest.mark.asyncio
async def test_upload_recorder(tmp_dirs, store):
    from fluxcatch.server import create_app
    from aiohttp.test_utils import TestServer, TestClient
    import fluxcatch.pairing as pairing

    app = create_app(store)
    server = TestServer(app); await server.start_server()
    c = TestClient(server); await c.start_server()

    origin="chrome-extension://uploadtest"
    pairing.add_origin(origin)
    headers={"Origin":origin}

    # create recorder task
    resp = await c.request("POST","/api/tasks", json={"kind":"recorder","page_url":"http://example.com/page","title":"myrec"}, headers=headers)
    assert resp.status==201
    tid = (await resp.json())["id"]

    # push chunks
    chunk1 = b"hello "
    resp = await c.request("POST", f"/api/tasks/{tid}/chunks", data=chunk1, headers=headers)
    assert resp.status==200
    chunk2 = b"world"
    resp = await c.request("POST", f"/api/tasks/{tid}/chunks", data=chunk2, headers=headers)
    assert resp.status==200

    # finish
    resp = await c.request("POST", f"/api/tasks/{tid}/finish", json={}, headers=headers)
    assert resp.status==200
    data = await resp.json()
    assert data["ok"]==True

    # verify task done and file exists
    resp = await c.request("GET", f"/api/tasks/{tid}", headers=headers)
    task = await resp.json()
    assert task["status"]=="done"
    from pathlib import Path
    assert Path(task["target_path"]).exists()
    assert Path(task["target_path"]).read_bytes()==b"hello world"

    await c.close(); await server.close()

@pytest.mark.asyncio
async def test_upload_empty(tmp_dirs, store):
    from fluxcatch.server import create_app
    from aiohttp.test_utils import TestServer, TestClient
    import fluxcatch.pairing as pairing
    app = create_app(store)
    server = TestServer(app); await server.start_server()
    c = TestClient(server); await c.start_server()
    origin="chrome-extension://emptytest"
    pairing.add_origin(origin)
    headers={"Origin":origin}
    resp = await c.request("POST","/api/tasks", json={"kind":"recorder","page_url":"http://example.com/page","title":"empty"}, headers=headers)
    tid=(await resp.json())["id"]
    # finish without chunks
    resp = await c.request("POST", f"/api/tasks/{tid}/finish", json={}, headers=headers)
    assert resp.status==400
    # should be error
    resp = await c.request("GET", f"/api/tasks/{tid}", headers=headers)
    task = await resp.json()
    assert task["status"]=="error"
    assert "err_empty" in task["error"]
    await c.close(); await server.close()
