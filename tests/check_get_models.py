#!/usr/bin/env python3
"""Checks get-models.sh's helper (tools/get_models.py) without the internet or ComfyUI.

Builds a small template library like ComfyUI's (an index and two templates, one with its models
inside a subgraph, one that only calls an online service), a saved workflow, and a stand-in
Hugging Face that answers like the real one: a redirect carrying the file's size and sha256,
then the file. Then it lists, searches, plans and downloads, and checks where every file lands.
Standard library only. Exits non-zero on failure.
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
FILES = {"unet.safetensors": b"U" * 3000, "encoder.safetensors": b"E" * 2000, "vision.safetensors": b"V" * 1000}
failed = False


def check(label, ok, detail):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}", flush=True)
    failed = failed or not ok


class FakeHub(BaseHTTPRequestHandler):
    corrupt = set()

    def log_message(self, *_):
        pass

    def answer(self, body):
        name = self.path.rsplit("/", 1)[1]
        if "/resolve/" in self.path:
            data = FILES[name]
            self.send_response(302)
            self.send_header("Location", f"/cdn/{name}")
            self.send_header("X-Linked-Size", str(len(data)))
            self.send_header("X-Linked-ETag", f'"{hashlib.sha256(data).hexdigest()}"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = FILES[name] if name not in self.corrupt else b"X" * len(FILES[name])
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if body:
            self.wfile.write(data)

    def do_HEAD(self):
        self.answer(False)

    def do_GET(self):
        self.answer(True)


def node(kind, models):
    return {"id": 1, "type": kind, "properties": {"models": models}, "widgets_values": []}


def build(root, hub):
    templates = root / "templates"
    templates.mkdir()
    url = f"http://{hub}/Comfy-Org/test/resolve/main/split_files"
    video = {"nodes": [node("SaveVideo", [])], "definitions": {"subgraphs": [{"nodes": [
        node("UNETLoader", [{"name": "unet.safetensors", "url": f"{url}/unet.safetensors", "directory": "diffusion_models"}]),
        node("CLIPLoader", [{"name": "encoder.safetensors", "url": f"{url}/encoder.safetensors", "directory": "text_encoders"}]),
        node("CLIPVisionLoader", [{"name": "vision.safetensors", "url": f"{url}/vision.safetensors", "directory": "clip_vision"}]),
    ]}]}}
    (templates / "video_test_model.json").write_text(json.dumps(video))
    (templates / "api_cloud_image.json").write_text(json.dumps({"nodes": [node("CloudImageNode", [])]}))
    (templates / "index.json").write_text(json.dumps([
        {"category": "Foundation", "title": "Video", "templates": [
            {"name": "video_test_model", "title": "Test Model: Image to Video", "openSource": True, "tags": ["Video"]}]},
        {"category": "Foundation", "title": "Image", "templates": [
            {"name": "api_cloud_image", "title": "Cloud Image: Text to Image", "openSource": False, "tags": ["API"]}]},
    ]))
    saved = root / "studio" / "ComfyUI" / "user" / "default" / "workflows"
    saved.mkdir(parents=True)
    (saved / "My dog test.json").write_text(json.dumps({"nodes": [node("CLIPLoader", [
        {"name": "encoder.safetensors", "url": f"{url}/encoder.safetensors", "directory": "text_encoders"}])]}))
    (saved / "Sneaky.json").write_text(json.dumps({"nodes": [node("CLIPLoader", [
        {"name": "../../evil.safetensors", "url": f"{url}/encoder.safetensors", "directory": "text_encoders"},
        {"name": "other.safetensors", "url": "https://example.com/other.safetensors", "directory": "loras"}])]}))
    return templates


def run(templates, studio, hub, *arguments, stdin=""):
    env = {**os.environ, "STUDIO_HOME": str(studio), "GET_MODELS_HOSTS": hub}
    return subprocess.run([sys.executable, str(REPO_DIR / "tools" / "get_models.py"), "--templates", str(templates),
                           *arguments], capture_output=True, text=True, env=env, input=stdin)


def main():
    server = HTTPServer(("127.0.0.1", 0), FakeHub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    hub = f"127.0.0.1:{server.server_address[1]}"
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        templates = build(root, hub)
        studio = root / "studio"
        models = studio / "models"
        comfy_models = studio / "ComfyUI" / "models"

        result = run(templates, studio, hub)
        check("List", result.returncode == 0 and "Test Model: Image to Video" in result.stdout
              and "My dog test" in result.stdout, result.stdout.strip().splitlines()[0] if result.stdout else result.stderr[-200:])
        check("Online templates marked", "Cloud Image" in result.stdout and "online service" in result.stdout,
              next((l for l in result.stdout.splitlines() if "Cloud Image" in l), "no line"))

        result = run(templates, studio, hub, "--check", "test model")
        check("Find by part of the title", result.returncode == 0 and "unet.safetensors" in result.stdout, "test model")
        check("Sizes and folders shown", "DiffusionModels" in result.stdout and "TextEncoders" in result.stdout
              and "clip_vision" in result.stdout and "3.0 KB" in result.stdout,
              next((l for l in result.stdout.splitlines() if "unet" in l), "no line").strip())
        check("Check downloads nothing", not models.exists() or not any(models.rglob("*.safetensors")), "nothing written")

        result = run(templates, studio, hub, "Test Model: Image to Video", stdin="no\n")
        check("Asks first", "Download 3 files" in result.stdout and not any(studio.rglob("unet.safetensors")),
              "answered no, nothing downloaded")

        result = run(templates, studio, hub, "video_test_model", "--yes")
        targets = [models / "DiffusionModels" / "unet.safetensors", models / "TextEncoders" / "encoder.safetensors",
                   comfy_models / "clip_vision" / "vision.safetensors"]
        check("Downloads into the right folders", result.returncode == 0 and all(t.exists() for t in targets),
              ", ".join(str(t.relative_to(studio)) for t in targets if t.exists()) or result.stdout[-300:])
        check("Checksums checked", result.stdout.count("checksum matches Hugging Face's") == 3, "3 files verified")
        check("No partial files left", not list(studio.rglob("*.part")), "none")

        result = run(templates, studio, hub, "My dog test", "--yes")
        check("Saved workflow, model already there", result.returncode == 0 and "already there" in result.stdout
              and "Nothing to download" in result.stdout, result.stdout.strip().splitlines()[-1])

        (models / "TextEncoders" / "encoder.safetensors").unlink()
        FakeHub.corrupt.add("encoder.safetensors")
        result = run(templates, studio, hub, "My dog test", "--yes")
        check("Damaged download refused", result.returncode != 0 and "does not match" in result.stdout + result.stderr
              and not (models / "TextEncoders" / "encoder.safetensors").exists(), (result.stdout + result.stderr).strip()[-90:])
        FakeHub.corrupt.clear()

        result = run(templates, studio, hub, "Sneaky", "--yes")
        out = result.stdout + result.stderr
        check("Unsafe names and other hosts refused", "../../evil" in out and "not a plain file name" in out
              and "example.com" in out and not (root / "evil.safetensors").exists()
              and not any(studio.rglob("other.safetensors")), "both skipped")

        result = run(templates, studio, hub, "Cloud Image")
        check("Online template explained", "online service" in result.stdout and "no model files" in result.stdout,
              result.stdout.strip().splitlines()[-1])
        result = run(templates, studio, hub, "test")
        check("Several matches listed", result.returncode != 0 and "Test Model" in result.stdout and "My dog test" in result.stdout
              and "more of the name" in result.stdout, "asks for more of the name")
        result = run(templates, studio, hub, "Flux Kontext Pro Max")
        check("Unknown name", result.returncode != 0 and "No template or saved workflow" in result.stdout,
              result.stdout.strip().splitlines()[0] if result.stdout else "")
    server.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
