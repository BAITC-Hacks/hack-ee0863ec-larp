"""Regression checks for catalogue consistency, startup, overload, and cache bounds."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from hackalem.catalog import ROOT, Query, load_catalog
from hackalem.catalog_store import import_catalog, read_profiles
from hackalem.cache_store import JsonCache
from hackalem.ai_model import MiniLMEncoder, ModelError
from hackalem.launcher import ensure_ports_free, wait_ready
from hackalem.web_server import Application, BusyError, RateLimiter
from tests import test_web as web_tests

class ReliabilityTests(unittest.TestCase):
    def test_import_is_atomic_and_console_reads_same_database(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source, db = folder/"source.jsonl", folder/"catalog.sqlite3"
            profile = load_catalog()[0]
            source.write_text(json.dumps(profile)+"\n", encoding="utf-8")
            import_catalog(source, db)
            self.assertEqual(len(read_profiles(db)), 1)
            source.write_text('{"bad":true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                import_catalog(source, db)
            self.assertEqual(read_profiles(db)[0]["id"], profile["id"])
            result = subprocess.run([sys.executable, str(ROOT/"main.py"), "--database", str(db),
                                     "--list-options"], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["profiles"], 1)

    def test_disk_cache_count_bytes_and_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            cache = JsonCache(path, max_entries=2, max_bytes=1024, ttl=10)
            for n in range(5):
                cache.put(str(n), {"n":n})
            self.assertLessEqual(len(list(path.glob("*.json"))), 2)
            cache.put("oversized", "x"*2000)
            self.assertIsNone(cache.get("oversized"))
            for file in path.glob("*.json"):
                os.utime(file, (0,0))
            self.assertIsNone(cache.get("4"))
            cache.put("new", 1)
            self.assertEqual(len(list(path.glob("*.json"))), 1)

    def test_embedding_memory_lru_bound(self):
        from collections import OrderedDict
        encoder = MiniLMEncoder.__new__(MiniLMEncoder)
        encoder.memory, encoder.memory_limit = OrderedDict(), 2
        encoder.remember("a", [1])
        encoder.remember("b", [2])
        encoder.remember("a", [3])
        encoder.remember("c", [4])
        self.assertEqual(list(encoder.memory), ["a", "c"])

    def test_two_searches_overlap_and_third_rejected(self):
        app = Application("http://unused", workers=2)
        app.profiles = lambda: []
        barrier = threading.Barrier(3)
        release = threading.Event()
        errors = []
        class Engine:
            def __init__(self, *args):
                pass
            def recommend(self, query):
                barrier.wait(timeout=5)
                release.wait(timeout=5)
                return {}
        def search():
            try:
                app.recommend(None)
            except Exception as exc:
                errors.append(exc)
        with patch("hackalem.web_server.Recommender", Engine):
            threads = [threading.Thread(target=search) for _ in range(2)]
            for t in threads:
                t.start()
            try:
                barrier.wait(timeout=5)
                with self.assertRaises(BusyError):
                    app.recommend(None)
            finally:
                release.set()
                for t in threads:
                    t.join(timeout=5)
        self.assertFalse(errors)
        self.assertEqual(app.available.qsize(), 2)

    def test_worker_returned_after_failure(self):
        app = Application("http://unused")
        app.profiles = lambda: (_ for _ in ()).throw(OSError("offline"))
        with self.assertRaises(OSError):
            app.recommend(None)
        self.assertEqual(app.available.qsize(), 2)

    def test_failed_model_never_ready(self):
        def failed():
            raise ModelError("missing model")
        app = Application("http://unused", encoder_factory=failed)
        app.profiles = lambda: []
        with self.assertRaises(ModelError):
            app.warmup()
        self.assertFalse(app.ready)

    def test_busy_port_rejected(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            with self.assertRaises(RuntimeError):
                ensure_ports_free([sock.getsockname()[1]])

    def test_wrong_instance_not_accepted(self):
        from unittest.mock import Mock
        child = Mock()
        child.poll.return_value = None
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"service":"hackalem-web","instance":"other"}'
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(RuntimeError):
                wait_ready(child, 1, "expected", "hackalem-web", timeout=0.01)

    def test_rate_limit_recovers(self):
        limiter = RateLimiter(limit=2, window=60)
        with patch("hackalem.web_server.time.monotonic", return_value=1):
            self.assertTrue(limiter.allow("a"))
            self.assertTrue(limiter.allow("a"))
            self.assertFalse(limiter.allow("a"))
        with patch("hackalem.web_server.time.monotonic", return_value=62):
            self.assertTrue(limiter.allow("a"))

class CatalogueHTTPTests(unittest.TestCase):
    setUp = web_tests.ServerTests.setUp
    start = web_tests.ServerTests.start
    url = web_tests.ServerTests.url

    def test_unchanged_catalogue_reuses_snapshot_and_updates_on_import(self):
        before = self.web.app.profiles()
        self.assertIs(before, self.web.app.profiles())
        source = Path(self.temp.name)/"update.jsonl"
        changed = dict(before[0], anon_name="Updated contractor")
        source.write_text(json.dumps(changed)+"\n", encoding="utf-8")
        import_catalog(source, self.database)
        after = self.web.app.profiles()
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["anon_name"], "Updated contractor")

    def test_health_reports_unready_model(self):
        import urllib.error
        import urllib.request
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.url(self.web)+"/health")
        self.assertEqual(caught.exception.code, 503)

class TransportTests(unittest.TestCase):
    def start_server(self):
        from hackalem.http_common import BoundedHTTPServer, Handler
        class TestHandler(Handler):
            timeout = 0.15
            def do_POST(self):
                try:
                    self.json_response(self.read_json())
                except TimeoutError:
                    self.json_response({'error':'timeout'}, 408)
        server = BoundedHTTPServer(('127.0.0.1',0), TestHandler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def test_slow_body_times_out(self):
        server = self.start_server()
        with socket.create_connection(server.server_address,timeout=2) as sock:
            sock.sendall(b'POST / HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: 20\r\n\r\n{')
            self.assertIn(b'408', sock.recv(2048))

    def test_connections_rejected_when_capacity_exhausted(self):
        server = self.start_server()
        for _ in range(24):
            self.assertTrue(server.slots.acquire(blocking=False))
        try:
            with socket.create_connection(server.server_address,timeout=2) as sock:
                self.assertIn(b'503', sock.recv(2048))
        finally:
            for _ in range(24):
                server.slots.release()
