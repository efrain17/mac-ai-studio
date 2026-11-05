#!/usr/bin/env python3
"""Checks the Chat tab's page without AnythingLLM or LM Studio.

AnythingLLM's desktop app has no web page of its own (its port answers the API only), so the
Chat tab shows a small page that reports whether AnythingLLM and LM Studio's server are up and
brings AnythingLLM's window forward. This starts stand-ins for both, starts the page, and checks
what it reports and that its button opens the app. Exits non-zero on failure.
"""
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
failed = False


def check(label, ok, detail):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}", flush=True)
    failed = failed or not ok


class StandIn(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/ping":
            body = {"online": True}
        elif self.path == "/v1/models":
            body = {"data": [{"id": "mlx-community/gpt-oss-120b-mxfp4-q8"}]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def fetch(url, data=None):
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode()


def start_page(port, apps_port, marker):
    command = [sys.executable, str(REPO_DIR / "runtime" / "chat_launcher.py"), "--port", str(port),
               "--anythingllm-port", str(apps_port), "--lmstudio-port", str(apps_port)]
    # The test replaces "open -a AnythingLLM" with a command that leaves a file behind.
    env = {**os.environ, "CHAT_OPEN_COMMAND": f"touch {marker}"}
    page = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            fetch(f"http://127.0.0.1:{port}/status")
            return page
        except OSError:
            time.sleep(0.1)
    return page


def main():
    stand_in = HTTPServer(("127.0.0.1", 0), StandIn)
    threading.Thread(target=stand_in.serve_forever, daemon=True).start()
    apps_port = stand_in.server_address[1]

    with tempfile.TemporaryDirectory() as temporary:
        marker = pathlib.Path(temporary) / "opened"
        port = free_port()
        page = start_page(port, apps_port, marker)
        try:
            html = fetch(f"http://127.0.0.1:{port}/")
            check("Page", "Open AnythingLLM" in html and "Studio Help" in html, "button and workspace name")
            status = json.loads(fetch(f"http://127.0.0.1:{port}/status"))
            check("AnythingLLM reported", status.get("anythingllm") is True, json.dumps(status))
            check("Chat model reported", status.get("model") == "mlx-community/gpt-oss-120b-mxfp4-q8",
                  str(status.get("model")))
            answer = json.loads(fetch(f"http://127.0.0.1:{port}/open", data=b""))
            time.sleep(0.3)
            check("Button opens AnythingLLM", answer.get("ok") is True and marker.exists(), json.dumps(answer))
            missing = fetch(f"http://127.0.0.1:{port}/status").count("false")
            check("Nothing reported missing", missing == 0, f"{missing} missing")
        finally:
            page.terminate()
            page.wait(timeout=10)

        stand_in.shutdown()
        port = free_port()
        page = start_page(port, free_port(), marker)
        try:
            status = json.loads(fetch(f"http://127.0.0.1:{port}/status"))
            check("Apps not running", status.get("anythingllm") is False and status.get("lmstudio") is False,
                  json.dumps(status))
        finally:
            page.terminate()
            page.wait(timeout=10)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
