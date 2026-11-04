#!/usr/bin/env python3
"""Checks the chat assistant's ComfyUI tools without a real ComfyUI.

Starts a stand-in ComfyUI on 127.0.0.1 that accepts a workflow and reports it finished, then
runs runtime/comfy_mcp.py as LM Studio and AnythingLLM would, and speaks the protocol to it:
initialize, list the tools, list the workflows, render one, read the job and the files.
Standard library only. Exits non-zero on failure.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
failed = False
received = {}


def check(label, ok, detail):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}", flush=True)
    failed = failed or not ok


class FakeComfy(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/system_stats":
            self.reply({"system": {"os": "fake"}})
        elif self.path == "/queue":
            self.reply({"queue_running": [], "queue_pending": []})
        elif self.path.startswith("/history/"):
            prompt_id = self.path.rsplit("/", 1)[1]
            if prompt_id != received.get("prompt_id"):
                self.reply({})
                return
            self.reply({prompt_id: {
                "status": {"status_str": "success", "messages": []},
                "outputs": {"9": {"images": [{"filename": "test_00001_.png", "subfolder": "images", "type": "output"}]}},
            }})
        else:
            self.reply({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/prompt":
            received["workflow"] = body["prompt"]
            received["prompt_id"] = "job-1"
            self.reply({"prompt_id": "job-1", "number": 1})
        elif self.path in ("/interrupt", "/queue"):
            self.reply({})
        else:
            self.reply({"error": "not found"}, 404)


class Client:
    def __init__(self, env):
        self.process = subprocess.Popen(
            [sys.executable, str(REPO_DIR / "runtime" / "comfy_mcp.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        self.next_id = 0

    def request(self, method, params=None):
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        reply = json.loads(self.process.stdout.readline())
        if "error" in reply:
            return reply["error"]
        return reply["result"]

    def notify(self, method):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.process.stdin.flush()

    def call(self, name, **arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        return result["isError"], result["content"][0]["text"]

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)
        return self.process.stderr.read()


def main():
    server = HTTPServer(("127.0.0.1", 0), FakeComfy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    with tempfile.TemporaryDirectory() as temporary:
        studio = pathlib.Path(temporary)
        (studio / "run").mkdir()
        (studio / "run" / "10-images.port").write_text(str(port))
        (studio / "output" / "images").mkdir(parents=True)
        (studio / "output" / "images" / "test_00001_.png").write_bytes(b"png")
        shutil.copytree(REPO_DIR / "workflows" / "images" / "api", studio / "runtime" / "workflows" / "images")
        shutil.copytree(REPO_DIR / "workflows" / "video-pro" / "api", studio / "runtime" / "workflows" / "video-pro")

        env = {**os.environ, "STUDIO_HOME": str(studio)}
        client = Client(env)
        result = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}})
        check("Initialize", result.get("serverInfo", {}).get("name") == "mac-ai-studio-comfyui",
              result.get("protocolVersion"))
        client.notify("notifications/initialized")
        check("Ping", client.request("ping") == {}, "answered")
        tools = [tool["name"] for tool in client.request("tools/list")["tools"]]
        check("Tools", tools == ["studio_status", "list_workflows", "run_workflow", "job_status", "cancel_jobs", "list_outputs"],
              ", ".join(tools))
        error = client.request("nothing/here")
        check("Unknown method", error.get("code") == -32601, error.get("message"))

        is_error, text = client.call("studio_status")
        check("Status", not is_error and "running" in text, text[:80])

        is_error, text = client.call("list_workflows")
        names = [item["name"] for item in json.loads(text)] if not is_error else []
        check("Workflows", "03_claymation" in names and "A_text_to_video_pro" in names, ", ".join(names))
        video = next(item for item in json.loads(text) if item["name"] == "A_text_to_video_pro")
        check("Video marked", video["makes"] == "video" and video["size"].get("length") == 125, json.dumps(video["size"]))

        is_error, text = client.call("run_workflow", workflow="03_claymation", prompt="a clay fox, claymation", seed=7, wait_seconds=30)
        check("Render", not is_error and "Finished" in text and str(studio / "output" / "images" / "test_00001_.png") in text, text[:120])
        sent = received["workflow"]
        prompts = [n["inputs"]["text"] for n in sent.values() if n["_meta"]["title"] == "Prompt"]
        seeds = [n["inputs"]["seed"] for n in sent.values() if "seed" in n["inputs"]]
        check("Prompt and seed sent", prompts == ["a clay fox, claymation"] and seeds == [7], f"{prompts} {seeds}")

        is_error, text = client.call("job_status", prompt_id="job-1")
        check("Job status", not is_error and "Finished" in text, text[:60])
        is_error, text = client.call("job_status", prompt_id="job-9")
        check("Unknown job", not is_error and "Unknown job" in text, text[:60])

        is_error, text = client.call("run_workflow", workflow="A_text_to_video_pro", prompt="x", width=640, height=640)
        check("No size for video", is_error and "fixed" in text, text[:80])
        is_error, text = client.call("run_workflow", workflow="nope", prompt="x")
        check("Unknown workflow", is_error and "No workflow" in text, text[:80])
        is_error, text = client.call("run_workflow", workflow="03_claymation", prompt="   ")
        check("Empty prompt", is_error and "Give a prompt" in text, text[:80])

        is_error, text = client.call("list_outputs", limit=5)
        check("Outputs", not is_error and "test_00001_.png" in text, text.splitlines()[0][-40:])
        is_error, text = client.call("cancel_jobs")
        check("Cancel", not is_error and "Stopped" in text, text)

        stderr = client.close()
        check("Quiet on stderr", stderr == "", stderr[:200] or "nothing")
    server.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
