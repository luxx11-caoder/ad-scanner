from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8765,
    "filename_template": "{title}.{ext}",
    "concurrency": 3,
}


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))


def config_dir() -> Path:
    return _xdg_config_home() / "fluxcatch"


def data_dir() -> Path:
    return _xdg_data_home() / "fluxcatch"


def state_dir() -> Path:
    return _xdg_state_home() / "fluxcatch"


def config_path() -> Path:
    return config_dir() / "config.json"


def db_path() -> Path:
    return data_dir() / "fluxcatch.db"


def log_path() -> Path:
    return state_dir() / "fluxcatch.log"


def secret_path() -> Path:
    return config_dir() / "secret"


def allowed_origins_path() -> Path:
    return config_dir() / "allowed_origins.json"


def _resolve_download_dir() -> Path:
    # Try xdg-user-dir DOWNLOAD
    try:
        out = subprocess.check_output(["xdg-user-dir", "DOWNLOAD"], text=True).strip()
        if out and Path(out).is_dir():
            return Path(out)
        if out and out != str(Path.home()):
            # xdg-user-dir may return $HOME when not found, we check anyway
            p = Path(out)
            if p.exists():
                return p
    except Exception:
        pass
    # Fallback Téléchargements then Downloads then home
    for name in ["Téléchargements", "Downloads"]:
        p = Path.home() / name
        if p.is_dir():
            return p
    # last fallback: try to see if those dirs exist or create Downloads
    for name in ["Téléchargements", "Downloads"]:
        p = Path.home() / name
        if not p.exists():
            continue
        return p
    return Path.home() / "Downloads"


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg["download_dir"] = str(_resolve_download_dir())
    p = config_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS or k == "download_dir"})
        except Exception:
            pass
    # env override for port/host if needed?
    return cfg


def save_config(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # only persist known keys
    to_save = {k: cfg[k] for k in ("host", "port", "download_dir", "filename_template", "concurrency") if k in cfg}
    p.write_text(json.dumps(to_save, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_dirs() -> None:
    for d in (config_dir(), data_dir(), state_dir()):
        d.mkdir(parents=True, exist_ok=True)
