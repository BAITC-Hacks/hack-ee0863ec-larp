"""Launch services with unique readiness tokens and reliable process cleanup."""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser
from hackalem.catalog import ROOT

def ensure_ports_free(ports):
    reservations = []
    try:
        for port in ports:
            sock = socket.socket()
            reservations.append(sock)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Port {port} is already in use. Stop the existing server first.") from exc
    finally:
        for sock in reservations:
            sock.close()

def wait_ready(child, port, token, service, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"{service} exited during startup. See the error above.")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                data = json.load(response)
            if data.get("instance") == token and data.get("service") == service:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"{service}: startup timed out.")

def stop_child(child):
    if child.poll() is not None:
        return
    if os.name == "nt":
        # Python venv launchers may spawn another Python process on Windows.
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    children = []
    try:
        ensure_ports_free((8001, 8000))
        token = uuid.uuid4().hex
        env = dict(os.environ, HACKALEM_INSTANCE=token)
        for module, port, service in (("hackalem.catalog_server", 8001, "hackalem-catalog"),
                                      ("hackalem.web_server", 8000, "hackalem-web")):
            child = subprocess.Popen([sys.executable, "-m", module], cwd=ROOT, env=env)
            children.append(child)
            wait_ready(child, port, token, service)
        print("Open http://127.0.0.1:8000 | Ctrl+C to stop", flush=True)
        if not args.no_browser:
            webbrowser.open("http://127.0.0.1:8000")
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError("One of the services stopped.")
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        for child in reversed(children):
            stop_child(child)

if __name__ == "__main__":
    raise SystemExit(main())
