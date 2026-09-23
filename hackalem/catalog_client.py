"""Conditional catalogue requests: unchanged datasets have no response body."""
import json
import threading
import urllib.request
import urllib.error

class CatalogClient:
    def __init__(self, url):
        self.url = url.rstrip("/")
        self.lock = threading.Lock()
        self.etag = None
        self.cached = None

    def profiles(self):
        with self.lock:
            headers = {"If-None-Match": self.etag} if self.etag else {}
            request = urllib.request.Request(self.url + "/contractors", headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    data = json.load(response)["profiles"]
                    self.etag = response.headers.get("ETag")
                    self.cached = data
            except urllib.error.HTTPError as exc:
                if exc.code != 304 or self.cached is None:
                    raise
            return self.cached
