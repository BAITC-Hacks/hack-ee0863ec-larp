"""Tests for the database boundary and HTTP validation."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from catalog import ROOT
from catalog_server import initialize_database, read_profiles, CatalogHandler
from web_server import Application, WebHandler

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "catalog.sqlite3"
        initialize_database(self.database, ROOT / "data/catalog.csv")
        self.catalog = self.start(CatalogHandler)
        self.catalog.database = self.database
        self.web = self.start(WebHandler)
        self.web.app = Application(self.url(self.catalog))

    def start(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def url(self, server):
        return f"http://127.0.0.1:{server.server_port}"

    def test_database_survives_restart_without_csv(self):
        before = read_profiles(self.database)
        initialize_database(self.database, Path(self.temp.name) / "missing.csv")
        self.assertEqual(before, read_profiles(self.database))
        self.assertEqual(len(before), 66)

    def test_catalog_flows_through_http(self):
        with urllib.request.urlopen(self.url(self.web) + "/api/catalog") as response:
            data = json.load(response)
        self.assertEqual(data["profiles"], read_profiles(self.database))

    def test_bad_query_returns_400(self):
        request = urllib.request.Request(self.url(self.web) + "/api/recommend",
                                        data=b'{"city":"test"}', headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 400)

    def test_catalog_outage_is_reported(self):
        self.catalog.shutdown()
        self.catalog.server_close()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.url(self.web) + "/api/options")
        self.assertEqual(caught.exception.code, 503)

    def test_empty_results_do_not_load_model(self):
        data = json.loads((ROOT / "examples/dense.json").read_text(encoding="utf-8"))
        data["budget_kzt"] = 0
        request = urllib.request.Request(self.url(self.web) + "/api/recommend",
                                        data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            result = json.load(response)
        self.assertEqual(result["cards"], [])
        self.assertFalse(result["ai_used"])
        self.assertIsNone(self.web.app.encoder)

if __name__ == "__main__":
    unittest.main()
