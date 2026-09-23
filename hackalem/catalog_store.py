"""One persistent catalogue shared by the console and HTTP service."""
import json
import sqlite3
from datetime import datetime, timezone
import uuid
from contextlib import closing
from pathlib import Path
from hackalem.catalog import ROOT, load_catalog, _profile

DATABASE = ROOT / "data/catalog.sqlite3"

def initialize_database(path=DATABASE, source=ROOT / "data/catalog.csv"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS contractors (id TEXT PRIMARY KEY, profile TEXT NOT NULL)")
        # SQLite serializes initialization and imports across processes.
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM contractors").fetchone()[0] == 0:
            db.executemany("INSERT INTO contractors VALUES (?, ?)",
                           [(p["id"], json.dumps(p, ensure_ascii=False)) for p in load_catalog(source)])

def read_profiles(path=DATABASE):
    with closing(sqlite3.connect(path, timeout=10)) as db:
        rows = db.execute("SELECT profile FROM contractors ORDER BY id").fetchall()
    return [_profile(json.loads(row[0]), n) for n, row in enumerate(rows, 1)]

def import_catalog(source, path=DATABASE):
    # Validate the complete input BEFORE opening a write transaction.
    profiles = load_catalog(source)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS contractors (id TEXT PRIMARY KEY, profile TEXT NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        # A separate read connection backs up the last committed snapshot while
        # BEGIN IMMEDIATE prevents another writer from changing it.
        if db.execute("SELECT COUNT(*) FROM contractors").fetchone()[0]:
            backups = path.parent / "backups"
            backups.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            target = backups / f"catalog-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3"
            with closing(sqlite3.connect(path)) as source_db, closing(sqlite3.connect(target)) as backup_db:
                source_db.backup(backup_db)
        db.execute("DELETE FROM contractors")
        db.executemany("INSERT INTO contractors VALUES (?, ?)",
                       [(p["id"], json.dumps(p, ensure_ascii=False)) for p in profiles])
    return len(profiles)
