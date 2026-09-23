"""Atomic JSON cache with bounded storage and expiry."""
from __future__ import annotations
import json
import os
import tempfile
import time
import threading
from pathlib import Path
from typing import Any
from hackalem.catalog import canonical_json, fingerprint

class JsonCache:
    _lock = threading.Lock()
    def __init__(self, folder: Path | None, max_entries=2048, max_bytes=64*1024*1024, ttl=7*86400):
        self.folder = folder
        self.max_entries, self.max_bytes, self.ttl = max_entries, max_bytes, ttl
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
            with self._lock:
                self._prune()

    def _prune(self):
        files = []
        now = time.time()
        for path in self.folder.glob("*.json"):
            try:
                stat = path.stat()
                if now - stat.st_mtime > self.ttl:
                    path.unlink(missing_ok=True)
                else:
                    files.append((stat.st_mtime_ns, path.name, path, stat.st_size))
            except FileNotFoundError:
                pass
        files.sort()
        total = sum(item[3] for item in files)
        count = len(files)
        for _, _, path, size in files:
            if count <= self.max_entries and total <= self.max_bytes:
                break
            path.unlink(missing_ok=True)
            count -= 1
            total -= size

    def get(self, key: str) -> Any | None:
        if self.folder is None:
            return None
        try:
            path = self.folder / f'{key}.json'
            if time.time() - path.stat().st_mtime > self.ttl:
                return None
            payload = json.loads(path.read_text(encoding='utf-8'))
            if payload['key'] == key and fingerprint(payload['value']) == payload['checksum']:
                return payload['value']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def put(self, key: str, value: Any) -> None:
        if self.folder is None:
            return
        payload = canonical_json({'key': key, 'value': value, 'checksum': fingerprint(value)})
        if len(payload.encode("utf-8")) > self.max_bytes:
            return
        with self._lock:
            fd, temp = tempfile.mkstemp(dir=self.folder, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(payload)
                os.replace(temp, self.folder / f'{key}.json')
                self._prune()
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
