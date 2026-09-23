"""Website and recommendation API; catalogue is fetched over HTTP."""
import argparse
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit
from ai_model import MiniLMEncoder, ModelError
from catalog import ROOT, Query, fingerprint
from http_common import Handler
from recommender import Recommender

class Application:
    def __init__(self, catalog_url):
        self.catalog_url = catalog_url.rstrip("/")
        self.lock = threading.Lock()
        self.engine = None
        self.encoder = None

    def profiles(self):
        with urllib.request.urlopen(self.catalog_url + "/contractors", timeout=10) as response:
            return json.load(response)["profiles"]

    def get_encoder(self):
        if self.encoder is None:
            self.encoder = MiniLMEncoder(offline=True)
        return self.encoder

    def recommend(self, query):
        with self.lock:
            profiles = self.profiles()
            if self.engine is None or self.engine.dataset_hash != fingerprint(profiles):
                self.engine = Recommender(profiles, self.get_encoder)
            return self.engine.recommend(query)

class WebHandler(Handler):
    def do_GET(self):
        route = urlsplit(self.path).path
        if route == "/":
            body = (ROOT / "web/index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if route not in ("/api/options", "/api/catalog", "/health"):
            return self.json_response({"error": "Не найдено"}, 404)
        try:
            profiles = self.server.app.profiles()
            if route == "/health":
                return self.json_response({"service": "hackalem-web", "count": len(profiles)})
            if route == "/api/catalog":
                return self.json_response({"profiles": profiles})
            self.json_response({
                "count": len(profiles),
                "cities": sorted({p["city"] for p in profiles}),
                "categories": sorted({v for p in profiles for v in p["categories"]}),
                "formats": sorted({v for p in profiles for v in p["event_formats"]}),
                "languages": sorted({v for p in profiles for v in p["languages"]}),
            })
        except (OSError, ValueError, KeyError):
            self.json_response({"error": "Сервер каталога недоступен. Запустите python run_web.py."}, 503)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/recommend":
            return self.json_response({"error": "Не найдено"}, 404)
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return self.json_response({"error": "Недопустимый источник запроса."}, 403)
        try:
            query = Query(**self.read_json())
        except (ValueError, TypeError):
            return self.json_response({"error": "Проверьте поля: город, категория, формат, дата в периоде 23.09–31.12.2026, бюджет и длительность."}, 400)
        try:
            self.json_response(self.server.app.recommend(query))
        except ModelError as exc:
            self.json_response({"error": str(exc)}, 503)
        except (OSError, ValueError, KeyError):
            self.json_response({"error": "Не удалось выполнить подбор. Проверьте сервер каталога и файлы модели."}, 503)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--catalog-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), WebHandler)
    server.app = Application(args.catalog_url)
    print(f"Website: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
