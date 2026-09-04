import sys
import tempfile
from pathlib import Path
import pytest

# Ensure manager is on path
ROOT = Path(__file__).parent.parent
MANAGER = ROOT / "manager"
if str(MANAGER) not in sys.path:
    sys.path.insert(0, str(MANAGER))

import fluxcatch.config as cfg
import fluxcatch.pairing as pairing
import fluxcatch.store as store_mod
from fluxcatch.server import create_app

from aiohttp.test_utils import TestClient, TestServer
import asyncio

@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    # redirect XDG dirs to tmp
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    download_dir = tmp_path / "downloads"
    download_dir.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_dir))
    # Ensure config returns download_dir from our tmp via mocking _resolve_download_dir? Instead put config.json
    # We'll create config.json manually
    config_dir.mkdir(parents=True, exist_ok=True)
    import json
    (config_dir / "fluxcatch").mkdir(parents=True, exist_ok=True)
    cfg_path = config_dir / "fluxcatch" / "config.json"
    cfg_path.write_text(json.dumps({"host":"127.0.0.1","port":8765,"download_dir":str(download_dir),"filename_template":"{title}.{ext}","concurrency":3}))
    # clear pairing
    return {"config": config_dir, "data": data_dir, "state": state_dir, "downloads": download_dir}

@pytest.fixture
def store(tmp_dirs):
    # ensure clean
    s = store_mod.Store()
    yield s
    try:
        s.close()
    except: pass

@pytest.fixture
async def client(tmp_dirs, store):
    app = create_app(store)
    server = TestServer(app)
    await server.start_server()
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()
    await server.close()

@pytest.fixture
def paired_client_headers(tmp_dirs):
    # Generate pairing origin
    # We need to pair an origin; we simulate by adding allowed origin directly and using Origin header
    code = pairing.get_or_create_secret()
    origin = "chrome-extension://testid123"
    pairing.add_origin(origin)
    return {"Origin": origin, "code": code, "origin": origin}

@pytest.fixture
async def paired_client(client, paired_client_headers):
    # client is already created with tmp_dirs, but pairing is global per XDG; we already added origin
    # Return client and headers
    yield (client, paired_client_headers)
