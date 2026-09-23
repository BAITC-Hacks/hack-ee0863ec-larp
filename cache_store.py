"""Atomic, non-pickle JSON cache. Corrupt entries are recomputed."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from catalog import canonical_json, fingerprint


class JsonCache:
    def __init__(self, folder: Path | None):
        self.folder = folder
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Any | None:
        if self.folder is None:
            return None
        try:
            payload = json.loads((self.folder / f'{key}.json').read_text(encoding='utf-8'))
            if payload['key'] == key and fingerprint(payload['value']) == payload['checksum']:
                return payload['value']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def put(self, key: str, value: Any) -> None:
        if self.folder is None:
            return
        payload = {'key': key, 'value': value, 'checksum': fingerprint(value)}
        fd, temp = tempfile.mkstemp(dir=self.folder, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
                f.write(canonical_json(payload))
            os.replace(temp, self.folder / f'{key}.json')
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
