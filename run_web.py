"""Start both local services and stop children on Ctrl+C."""
import argparse
import subprocess
import sys
import time
import urllib.request
import webbrowser
from catalog import ROOT

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    children = []
    try:
        for script, port in (("catalog_server.py", 8001), ("web_server.py", 8000)):
            child = subprocess.Popen([sys.executable, str(ROOT / script)], cwd=ROOT)
            children.append(child)
            deadline = time.monotonic() + 30
            while True:
                if child.poll() is not None:
                    raise RuntimeError(f"{script} exited. Check whether port {port} is busy.")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"{script}: startup timeout")
                    time.sleep(0.2)
        print("Open http://127.0.0.1:8000 | Ctrl+C to stop", flush=True)
        if not args.no_browser:
            webbrowser.open("http://127.0.0.1:8000")
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError("One of the services stopped.")
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                child.wait()

if __name__ == "__main__":
    raise SystemExit(main())
