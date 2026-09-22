"""Small transactional SQLite repository. All media stays outside the database."""
from __future__ import annotations
import json
from contextlib import contextmanager, closing
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("HELIOS_DATA_DIR", str(ROOT / "data"))).resolve()
DEFAULT_SETTINGS = {
    "offline": True,
    "provider": {"kind": "ollama", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen3:8b"},
    "pause_ms": 1800,
    "ignore_mic_while_speaking": False,
    "speech": {"stt_path": "", "tts_path": "", "diarization_path": ""},
}
COLLECTIONS = {"jobs", "rounds", "sessions", "segments", "preparations", "assessments", "drills", "tasks"}

def now():
    return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self, directory: Path = DATA_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "helios.sqlite3"
        self.lock = threading.RLock()
        for name in ("media", "models", "tmp"):
            (self.directory / name).mkdir(exist_ok=True)
        with self.connect() as con:
            con.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS records (
                collection TEXT NOT NULL, id TEXT NOT NULL,
                data TEXT NOT NULL, PRIMARY KEY(collection,id));
            CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            PRAGMA user_version=1;
            ''')
            con.execute("INSERT OR IGNORE INTO preferences VALUES(1, ?)", (json.dumps(DEFAULT_SETTINGS),))

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def list(self, collection, **filters):
        assert collection in COLLECTIONS
        with self.lock, self.connect() as con:
            rows = con.execute("SELECT data FROM records WHERE collection=? ORDER BY rowid DESC", (collection,)).fetchall()
        records = [json.loads(row[0]) for row in rows]
        return [r for r in records if all(r.get(k) == v for k, v in filters.items())]

    def get(self, collection, record_id):
        with self.lock, self.connect() as con:
            row = con.execute("SELECT data FROM records WHERE collection=? AND id=?", (collection, record_id)).fetchone()
        if row is None:
            raise KeyError(f"{collection.rstrip('s').title()} not found")
        return json.loads(row[0])

    def put(self, collection, fields, record_id=None):
        assert collection in COLLECTIONS
        record_id = record_id or str(uuid.uuid4())
        with self.lock, self.connect() as con:
            old = con.execute("SELECT data FROM records WHERE collection=? AND id=?", (collection, record_id)).fetchone()
            record = json.loads(old[0]) if old else {"id": record_id, "created_at": now()}
            record.update({k: v for k, v in fields.items() if k not in {"id", "created_at", "updated_at"}})
            record["updated_at"] = now()
            con.execute("INSERT OR REPLACE INTO records VALUES(?,?,?)", (collection, record_id, json.dumps(record)))
        return record

    def update(self, collection, record_id, fields):
        self.get(collection, record_id)
        return self.put(collection, fields, record_id)

    def delete(self, collection, record_id):
        with self.lock, self.connect() as con:
            con.execute("DELETE FROM records WHERE collection=? AND id=?", (collection, record_id))

    def settings(self):
        with self.lock, self.connect() as con:
            return json.loads(con.execute("SELECT data FROM preferences WHERE id=1").fetchone()[0])

    def save_settings(self, patch):
        with self.lock, self.connect() as con:
            current = json.loads(con.execute("SELECT data FROM preferences WHERE id=1").fetchone()[0])
            for key, value in patch.items():
                if key in DEFAULT_SETTINGS:
                    if isinstance(value, dict):
                        current[key].update(value)
                    else:
                        current[key] = value
            con.execute("UPDATE preferences SET data=? WHERE id=1", (json.dumps(current),))
        return current

    def snapshot(self, destination):
        with self.lock, self.connect() as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
