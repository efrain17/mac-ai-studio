#!/usr/bin/env python3
"""Checks the Get Models window (runtime/models_page.py) without the internet or ComfyUI.

Uses the same small template library and stand-in Hugging Face as check_get_models.py, starts
the window's page server, and drives it the way the page does: search, plan, download with
progress, cancel. Standard library only. Exits non-zero on failure.
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
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "tests"))
import check_get_models as fixtures  # noqa: E402

failed = False


def check(label, ok, detail):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}", flush=True)
    failed = failed or not ok


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Page:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=30) as response:
            body = response.read().decode()
        return json.loads(body) if path.startswith("/api/") else body

    def post(self, path, payload, header=True):
        headers = {"Content-Type": "application/json", **({"X-Studio": "1"} if header else {})}
        request = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, {}

    def wait(self, states, seconds=30):
        deadline = time.time() + seconds
        job = {}
        while time.time() < deadline:
            job = self.get("/api/job")
            if job.get("state") in states:
                return job
            time.sleep(0.2)
        return job


def main():
    hub_server = HTTPServer(("127.0.0.1", 0), fixtures.FakeHub)
    threading.Thread(target=hub_server.serve_forever, daemon=True).start()
    hub = f"127.0.0.1:{hub_server.server_address[1]}"
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        templates = fixtures.build(root, hub)
        studio = root / "studio"
        port = free_port()
        env = {**os.environ, "STUDIO_HOME": str(studio), "GET_MODELS_HOSTS": hub}
        server = subprocess.Popen([sys.executable, str(REPO_DIR / "runtime" / "models_page.py"), "--port", str(port),
                                   "--templates", str(templates)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        page = Page(port)
        try:
            for _ in range(100):
                try:
                    page.get("/api/job")
                    break
                except OSError:
                    time.sleep(0.1)
            html = page.get("/")
            check("Page", "Get models" in html and 'id="search"' in html, "search box and title")

            found = page.get("/api/search?q=" + urllib.parse.quote("test model"))["results"]
            check("Search", [r["title"] for r in found] == ["Test Model: Image to Video"] and found[0]["files"] == 3,
                  json.dumps(found)[:120])
            found = page.get("/api/search?q=cloud")["results"]
            check("Online templates marked", found and found[0]["online"] is True, json.dumps(found)[:100])

            plan = page.get("/api/plan?key=" + urllib.parse.quote("template:video_test_model"))
            states = [(r["name"], r["state"], r["size"], r["folder"]) for r in plan.get("rows", [])]
            check("Plan", plan.get("total") == 6000 and len(states) == 3 and all(s[1] == "to download" for s in states)
                  and ("unet.safetensors", "to download", 3000, "models/DiffusionModels") in states, json.dumps(states)[:140])

            status, _ = page.post("/api/download", {"key": "template:video_test_model"}, header=False)
            check("Other web pages cannot start downloads", status == 403, f"HTTP {status}")

            fixtures.FakeHub.slow.add("unet.safetensors")
            status, _ = page.post("/api/download", {"key": "template:video_test_model"})
            job = page.wait(("downloading",))
            time.sleep(1.0)
            job = page.get("/api/job")
            current = next((f for f in job.get("files", []) if f["state"] == "downloading"), {})
            check("Progress reported", status == 200 and 0 < job.get("done_bytes", 0) < 6000 and current.get("done", 0) > 0,
                  f"{job.get('done_bytes')} of {job.get('total')} bytes, {current.get('name')} at {current.get('done')}")
            status, _ = page.post("/api/download", {"key": "template:video_test_model"})
            check("One download at a time", status == 409, f"HTTP {status}")
            page.post("/api/cancel", {})
            job = page.wait(("cancelled",))
            unet = studio / "models" / "DiffusionModels" / "unet.safetensors"
            check("Cancel", job.get("state") == "cancelled" and not unet.exists(), job.get("message", "")[:80])

            fixtures.FakeHub.slow.clear()
            page.post("/api/download", {"key": "template:video_test_model"})
            job = page.wait(("done", "failed"))
            targets = [unet, studio / "models" / "TextEncoders" / "encoder.safetensors",
                       studio / "ComfyUI" / "models" / "clip_vision" / "vision.safetensors"]
            check("Download after a cancel", job.get("state") == "done" and all(t.exists() for t in targets)
                  and job.get("done_bytes") == 6000 and all(f["state"] == "done" for f in job["files"]),
                  job.get("message", "")[:90])
            check("Checksums checked", all(f.get("verified") for f in job["files"]), "3 files verified")

            plan = page.get("/api/plan?key=" + urllib.parse.quote("saved:My dog test"))
            check("Saved workflow, already there", [r["state"] for r in plan["rows"]] == ["already there"]
                  and plan["total"] == 0, json.dumps(plan["rows"])[:100])

            (studio / "models" / "TextEncoders" / "encoder.safetensors").unlink()
            fixtures.FakeHub.corrupt.add("encoder.safetensors")
            page.post("/api/download", {"key": "saved:My dog test"})
            job = page.wait(("done", "failed"))
            check("Damaged download reported", job.get("state") == "failed" and "does not match" in json.dumps(job),
                  job.get("message", "")[:90])
            fixtures.FakeHub.corrupt.clear()
        finally:
            server.terminate()
            stderr = server.communicate(timeout=10)[1].decode()
        check("No errors on the server", "Traceback" not in stderr, stderr.strip()[-200:] or "none")
    hub_server.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
