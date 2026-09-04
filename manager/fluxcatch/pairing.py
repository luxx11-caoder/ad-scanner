from __future__ import annotations

import json
import os
import secrets
import string
from pathlib import Path

from . import config as cfg

CODE_LENGTH = 8
CODE_ALPHABET = string.ascii_uppercase + string.digits  # sans confusion? garder simple


def _ensure_config_dir():
    cfg.config_dir().mkdir(parents=True, exist_ok=True)


def _secret_file() -> Path:
    return cfg.secret_path()


def _origins_file() -> Path:
    return cfg.allowed_origins_path()


def get_or_create_secret() -> str:
    _ensure_config_dir()
    p = _secret_file()
    if p.is_file():
        try:
            code = p.read_text(encoding="utf-8").strip()
            if code:
                return code
        except Exception:
            pass
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    # write with 0600
    try:
        p.write_text(code, encoding="utf-8")
        os.chmod(p, 0o600)
    except Exception:
        p.write_text(code, encoding="utf-8")
    return code


def regenerate_secret() -> str:
    _ensure_config_dir()
    p = _secret_file()
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    p.write_text(code, encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return code


def get_code() -> str:
    return get_or_create_secret()


def verify_code(code: str) -> bool:
    expected = get_or_create_secret()
    # constant time? simple for MVP
    return secrets.compare_digest(code.strip(), expected)


def load_allowed_origins() -> set[str]:
    p = _origins_file()
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(x) for x in data)
    except Exception:
        pass
    return set()


def save_allowed_origins(origins: set[str]) -> None:
    _ensure_config_dir()
    p = _origins_file()
    p.write_text(json.dumps(sorted(origins), indent=2), encoding="utf-8")


def add_origin(origin: str) -> None:
    origins = load_allowed_origins()
    origins.add(origin)
    save_allowed_origins(origins)


def remove_origin(origin: str) -> None:
    origins = load_allowed_origins()
    origins.discard(origin)
    save_allowed_origins(origins)


def is_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    return origin in load_allowed_origins()


def is_paired() -> bool:
    return len(load_allowed_origins()) > 0
