"""Website and recommendation API; catalogue is fetched over HTTP."""
import argparse
import json
import threading
import queue
import time
import os
from collections import OrderedDict, deque
from hackalem.catalog_client import CatalogClient
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit
from hackalem.ai_model import MiniLMEncoder, ModelError
from hackalem.catalog import ROOT, Query, fingerprint
from hackalem.http_common import Handler, BoundedHTTPServer
from hackalem.recommender import Recommender

class BusyError(RuntimeError):
    pass

class RateLimiter:
    def __init__(self, limit=30, window=60):
        self.limit, self.window = limit, window
        self.clients = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, client):
        now = time.monotonic()
        with self.lock:
            history = self.clients.setdefault(client, deque())
            self.clients.move_to_end(client)
            while history and history[0] <= now - self.window:
                history.popleft()
            if len(history) >= self.limit:
                return False
            history.append(now)
            while len(self.clients) > 1024:
                self.clients.popitem(last=False)
            return True

class Application:
    def __init__(self, catalog_url, workers=2, encoder_factory=None):
        self.client = CatalogClient(catalog_url)
        self.workers = [{"encoder": None, "engine": None} for _ in range(workers)]
        self.available = queue.Queue(maxsize=workers)
        for worker in self.workers:
            self.available.put(worker)
        self.encoder_factory = encoder_factory or (lambda: MiniLMEncoder(offline=True))
        self.limiter = RateLimiter()
        self.ready = False

    def profiles(self):
        return self.client.profiles()

    def warmup(self):
        self.profiles()
        for worker in self.workers:
            if worker["encoder"] is None:
                worker["encoder"] = self.encoder_factory()
            worker["encoder"].embed("Event planning")
        self.ready = True

    def recommend(self, query):
        try:
            worker = self.available.get_nowait()
        except queue.Empty:
            raise BusyError("All search workers are busy. Please retry shortly.")
        try:
            profiles = self.profiles()
            def encoder():
                if worker["encoder"] is None:
                    worker["encoder"] = self.encoder_factory()
                return worker["encoder"]
            if worker["engine"] is None or worker["engine"].dataset_hash != fingerprint(profiles):
                worker["engine"] = Recommender(profiles, encoder)
            return worker["engine"].recommend(query)
        finally:
            self.available.put_nowait(worker)

class WebHandler(Handler):
    def do_GET(self):
        route = urlsplit(self.path).path
        pages = {"/": "home.html", "/search": "index.html", "/search/": "index.html"}
        if route in pages or route == "/site.css":
            if route == "/site.css":
                body = (ROOT / "web/site.css").read_bytes()
                content_type = "text/css; charset=utf-8"
            else:
                html = (ROOT / "web" / pages[route]).read_text(encoding="utf-8")
                for name in ("header", "footer"):
                    partial = (ROOT / "web/partials" / (name + ".html")).read_text(encoding="utf-8")
                    html = html.replace("{{" + name.upper() + "}}", partial)
                html = html.replace("{{HOME_CURRENT}}", 'aria-current="page"' if route == "/" else "")
                html = html.replace("{{SEARCH_CURRENT}}", 'aria-current="page"' if route != "/" else "")
                body = html.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if route not in ("/api/options", "/api/catalog", "/health"):
            return self.json_response({"error": "Не найдено"}, 404)
        try:
            profiles = self.server.app.profiles()
            if route == "/health":
                return self.json_response({"service": "hackalem-web", "count": len(profiles),
                                           "ready": self.server.app.ready,
                                           "instance": os.environ.get("HACKALEM_INSTANCE", "")},
                                          200 if self.server.app.ready else 503)
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
        if not self.server.app.limiter.allow(self.client_address[0]):
            return self.json_response({"error": "Too many searches. Please wait a minute."}, 429,
                                      headers={"Retry-After": "60"})
        try:
            query = Query(**self.read_json())
        except TimeoutError:
            return self.json_response({"error": "Request body timed out."}, 408)
        except (ValueError, TypeError):
            return self.json_response({"error": "Проверьте поля: город, категория, формат, дата в периоде 23.09–31.12.2026, бюджет и длительность."}, 400)
        try:
            self.json_response(self.server.app.recommend(query))
        except BusyError as exc:
            return self.json_response({"error": str(exc)}, 429, headers={"Retry-After": "2"})
        except ModelError as exc:
            self.json_response({"error": str(exc)}, 503)
        except (OSError, ValueError, KeyError):
            self.json_response({"error": "Не удалось выполнить подбор. Проверьте сервер каталога и файлы модели."}, 503)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--catalog-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    server = BoundedHTTPServer(("127.0.0.1", args.port), WebHandler)
    server.app = Application(args.catalog_url)
    try:
        server.app.warmup()
    except (OSError, ValueError, KeyError, ModelError) as exc:
        server.server_close()
        raise SystemExit(f"Startup failed: {exc}. Prepare the model with python main.py --prepare.")
    print(f"Website: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
