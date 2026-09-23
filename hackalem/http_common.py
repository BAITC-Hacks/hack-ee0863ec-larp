"""Bounded local HTTP transport."""
import json
from decimal import Decimal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(24)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nRetry-After: 2\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

class Handler(BaseHTTPRequestHandler):
    timeout = 10
    def setup(self):
        self.request.settimeout(self.timeout)
        super().setup()

    def json_response(self, data, status=200, headers=None):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json.")
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise ValueError("One Content-Length is required.")
        size = int(self.headers["Content-Length"])
        if not 0 < size <= 16384:
            raise ValueError("JSON body must be between 1 and 16384 bytes.")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("Incomplete body.")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON field.')
                result[key] = value
            return result
        def invalid(value):
            raise ValueError('Non-finite JSON number.')
        value = json.loads(raw, parse_float=Decimal, parse_constant=invalid, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object.")
        return value
