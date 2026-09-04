from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config as cfg

# Valid states
VALID_STATUSES = {"pending", "active", "merging", "paused", "done", "canceled", "error"}
VALID_KINDS = {"direct", "hls", "ytdlp", "recorder", "browser_proxy"}

# Transitions: (from -> set of allowed to)
TRANSITIONS: dict[str, set[str]] = {
    "pending": {"active", "canceled", "error", "paused"},
    "active": {"merging", "paused", "canceled", "error", "done"},
    "merging": {"done", "canceled", "error"},
    "paused": {"active", "pending", "canceled", "error"},
    "done": set(),
    "canceled": set(),
    "error": {"pending", "active"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,
  source_url   TEXT NOT NULL,
  page_url     TEXT,
  title        TEXT,
  headers_json TEXT NOT NULL DEFAULT '{}',
  status       TEXT NOT NULL DEFAULT 'pending',
  target_path  TEXT,
  mime         TEXT,
  size_total   INTEGER,
  size_done    INTEGER NOT NULL DEFAULT 0,
  error        TEXT,
  extra_json   TEXT NOT NULL DEFAULT '{}',
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_file: Path | None = None):
        if db_file is None:
            db_file = cfg.db_path()
        self.db_file = Path(db_file)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_file), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        # recover tasks that were active at crash
        self._recover()

    def _recover(self):
        # tasks active/paused at crash -> paused if possible else pending
        # For MVP: active -> paused, merging -> error (needs retry)
        cur = self.conn.execute("SELECT id, status FROM tasks WHERE status IN ('active','merging')")
        for row in cur.fetchall():
            # we set to paused, tasks.py will handle resume logic
            try:
                self.update_status(row["id"], "paused" if row["status"] == "active" else "error", error="err_crash" if row["status"] == "merging" else None)
            except Exception:
                pass

    def create_task(
        self,
        kind: str,
        source_url: str,
        page_url: str | None = None,
        title: str | None = None,
        headers: dict | None = None,
        extra: dict | None = None,
        mime: str | None = None,
        target_path: str | None = None,
    ) -> dict:
        if kind not in VALID_KINDS:
            raise ValueError(f"kind invalide: {kind}")
        tid = uuid.uuid4().hex
        now = _now()
        headers_json = json.dumps(headers or {}, ensure_ascii=False)
        extra_json = json.dumps(extra or {}, ensure_ascii=False)
        self.conn.execute(
            "INSERT INTO tasks (id, kind, source_url, page_url, title, headers_json, status, target_path, mime, size_total, size_done, error, extra_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, kind, source_url, page_url, title, headers_json, "pending", target_path, mime, None, 0, None, extra_json, now, now),
        )
        self.conn.commit()
        return self.get(tid)  # type: ignore

    def get(self, tid: str) -> dict | None:
        cur = self.conn.execute("SELECT * FROM tasks WHERE id=?", (tid,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM tasks ORDER BY created_at DESC")
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        # parse jsons
        try:
            d["headers"] = json.loads(d.pop("headers_json") or "{}")
        except Exception:
            d["headers"] = {}
        try:
            d["extra"] = json.loads(d.pop("extra_json") or "{}")
        except Exception:
            d["extra"] = {}
        return d

    def update_status(self, tid: str, new_status: str, error: str | None = None):
        if new_status not in VALID_STATUSES:
            raise ValueError(f"status invalide: {new_status}")
        cur = self.conn.execute("SELECT status FROM tasks WHERE id=?", (tid,))
        row = cur.fetchone()
        if not row:
            raise KeyError(tid)
        old = row["status"]
        if old == new_status:
            return
        allowed = TRANSITIONS.get(old, set())
        # error can come from any active state, also allow pending->error etc. Already in TRANSITIONS
        # Special case: allow paused->pending via reset? we already have paused->pending
        # Also allow error->pending (retry)
        if new_status not in allowed:
            # Allow direct transition to error from any non-terminal?
            if new_status == "error" and old not in ("done", "canceled"):
                pass
            # Allow canceled from any non-terminal
            elif new_status == "canceled" and old not in ("done", "canceled", "error"):
                pass
            else:
                raise ValueError(f"transition {old} -> {new_status} non autorisée")
        now = _now()
        if new_status == "error":
            self.conn.execute("UPDATE tasks SET status=?, error=?, updated_at=? WHERE id=?", (new_status, error, now, tid))
        else:
            # clear error when leaving error
            if old == "error":
                self.conn.execute("UPDATE tasks SET status=?, error=NULL, updated_at=? WHERE id=?", (new_status, now, tid))
            else:
                self.conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (new_status, now, tid))
        self.conn.commit()

    def update_progress(self, tid: str, size_done: int, size_total: int | None = None, target_path: str | None = None, mime: str | None = None):
        now = _now()
        fields = ["size_done=?", "updated_at=?"]
        vals: list[Any] = [size_done, now]
        if size_total is not None:
            fields.insert(1, "size_total=?")
            vals.insert(1, size_total)
        if target_path is not None:
            fields.append("target_path=?")
            vals.append(target_path)
        if mime is not None:
            fields.append("mime=?")
            vals.append(mime)
        # build query
        set_clause = ", ".join(fields)
        vals.append(tid)
        self.conn.execute(f"UPDATE tasks SET {set_clause} WHERE id=?", vals)
        self.conn.commit()

    def update_target(self, tid: str, target_path: str):
        now = _now()
        self.conn.execute("UPDATE tasks SET target_path=?, updated_at=? WHERE id=?", (target_path, now, tid))
        self.conn.commit()

    def set_error(self, tid: str, error: str):
        self.update_status(tid, "error", error=error)

    def delete(self, tid: str):
        self.conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
