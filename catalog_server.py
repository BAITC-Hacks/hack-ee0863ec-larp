"""Independent SQLite catalogue service. CSV is used only to seed a new database."""
import argparse
from contextlib import closing
import json
import sqlite3
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit
from catalog import ROOT, load_catalog
from http_common import Handler

def initialize_database(path, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS contractors (id TEXT PRIMARY KEY, profile TEXT NOT NULL)")
        if db.execute("SELECT COUNT(*) FROM contractors").fetchone()[0] == 0:
            db.executemany("INSERT INTO contractors VALUES (?, ?)",
                           [(p["id"], json.dumps(p, ensure_ascii=False)) for p in load_catalog(source)])

def read_profiles(path):
    with closing(sqlite3.connect(path)) as db, db:
        return [json.loads(row[0]) for row in db.execute("SELECT profile FROM contractors ORDER BY id")]

class CatalogHandler(Handler):
    def do_GET(self):
        route = urlsplit(self.path).path
        if route not in ("/health", "/contractors"):
            return self.json_response({"error": "Не найдено"}, 404)
        try:
            profiles = read_profiles(self.server.database)
            self.json_response({"service": "hackalem-catalog", "count": len(profiles)}
                               if route == "/health" else {"profiles": profiles})
        except (sqlite3.Error, ValueError):
            self.json_response({"error": "Не удалось прочитать базу каталога."}, 503)

def main():
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--database", type=Path, default=ROOT / "data/catalog.sqlite3")
    args = parser.parse_args()
    initialize_database(args.database, ROOT / "data/catalog.csv")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), CatalogHandler)
    server.database = args.database
    print(f"Catalogue: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
