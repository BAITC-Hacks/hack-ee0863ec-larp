"""Read-only HTTP API for the shared catalogue database."""
import argparse
import os
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlsplit
from hackalem.catalog import fingerprint
from hackalem.catalog_store import DATABASE, initialize_database, read_profiles
from hackalem.http_common import Handler, BoundedHTTPServer

class CatalogHandler(Handler):
    def do_GET(self):
        route = urlsplit(self.path).path
        if route not in ("/health", "/contractors"):
            return self.json_response({"error": "Not found"}, 404)
        try:
            # Cache serialization/hash until the database file changes.
            with self.server.snapshot_lock:
                stat = self.server.database.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if signature != self.server.snapshot_signature:
                    profiles = read_profiles(self.server.database)
                    self.server.snapshot = (profiles, '"' + fingerprint(profiles) + '"')
                    self.server.snapshot_signature = signature
                profiles, etag = self.server.snapshot
            if route == "/health":
                return self.json_response({"service": "hackalem-catalog", "count": len(profiles),
                                           "instance": os.environ.get("HACKALEM_INSTANCE", "")})
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return
            self.json_response({"profiles": profiles}, headers={"ETag": etag})
        except (OSError, sqlite3.Error, ValueError):
            self.json_response({"error": "Catalogue database is unavailable."}, 503)

def configure_server(server, database):
    server.database = Path(database)
    server.snapshot_lock = threading.Lock()
    server.snapshot_signature = None
    server.snapshot = None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--database", type=Path, default=DATABASE)
    args = parser.parse_args()
    initialize_database(args.database)
    server = BoundedHTTPServer(("127.0.0.1", args.port), CatalogHandler)
    configure_server(server, args.database)
    print(f"Catalogue: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
