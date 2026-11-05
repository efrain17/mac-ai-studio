#!/usr/bin/env python3
"""Checks the chat assistant's ComfyUI tools without a real ComfyUI.

Starts a stand-in ComfyUI on 127.0.0.1 that accepts a workflow and reports it finished, then
runs runtime/comfy_mcp.py as LM Studio and AnythingLLM would, and speaks the protocol to it:
initialize, list the tools, list the workflows, render one, read the job and the files, and
create, update and protect workflows. The stand-in describes its nodes with
tests/fixtures/comfyui_object_info.json, saved from a real ComfyUI v0.43.0 with the Reveal node
and the studio's model file names, so the checks run against ComfyUI's real node definitions.
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
OBJECT_INFO = json.loads((REPO_DIR / "tests" / "fixtures" / "comfyui_object_info.json").read_text())
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
        if self.path == "/object_info":
            self.reply(OBJECT_INFO)
        elif self.path == "/system_stats":
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

    def call(self, tool, **arguments):
        result = self.request("tools/call", {"name": tool, "arguments": arguments})
        return result["isError"], result["content"][0]["text"]

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)
        return self.process.stderr.read()


def panel_widgets(path, title):
    """A node's widget values as ComfyUI's editor will show them."""
    ui = json.loads(path.read_text())
    return next(n["widgets_values"] for n in ui["nodes"] if n.get("title", n["type"]) == title)


def check_workflow_tools(client, studio):
    panel = studio / "ComfyUI" / "user" / "default" / "workflows" / "Mac AI Studio" / "From chat"
    data = studio / "chat-workflows"

    is_error, text = client.call("list_node_types", search="lora loader")
    check("Node search", not is_error and "LoraLoader" in text and "ClayAnimationRedm.safetensors" in text,
          text.splitlines()[0] if text else "")
    is_error, text = client.call("get_workflow", name="03_claymation")
    check("Read a workflow", not is_error and '"class_type": "KSampler"' in text and "never changed" in text, text[:70])

    is_error, text = client.call("create_workflow", name="Clay poster", based_on="03_claymation",
                                 changes={"Render": {"steps": 24, "cfg": 6.5}, "Image size": {"width": 832, "height": 1216}},
                                 prompt="Clay Animation, Clay, a fox in a red scarf", description="Tall clay posters.")
    saved = panel / "Clay poster.json"
    check("Create from a studio workflow", not is_error and saved.exists() and (data / "Clay poster.json").exists(), text[:90])
    ui = json.loads(saved.read_text()) if saved.exists() else {"nodes": [], "extra": {}}
    check("Saved in the editor's format", panel_widgets(saved, "Render") == [4103, "randomize", 24, 6.5, "dpmpp_2m", "karras", 1.0]
          and panel_widgets(saved, "Image size") == [832, 1216, 1] and ui["extra"].get("mac_ai_studio", {}).get("made_by"),
          json.dumps(panel_widgets(saved, "Render")))
    check("Note in the editor", any(n["type"] == "Note" and n["widgets_values"] == ["Tall clay posters."] for n in ui["nodes"]),
          "Read me note")
    studio_file = studio / "runtime" / "workflows" / "images" / "03_claymation.json"
    check("Studio workflow untouched", json.loads(studio_file.read_text())["6"]["inputs"]["steps"] == 30, "03_claymation steps 30")

    is_error, text = client.call("list_workflows")
    chat = [item for item in json.loads(text) if item.get("made_by_chat")] if not is_error else []
    check("Listed as made by the chat", [item["name"] for item in chat] == ["Clay poster"] and chat[0]["group"] == "From chat",
          json.dumps(chat)[:120])

    is_error, text = client.call("run_workflow", workflow="Clay poster", seed=11, wait_seconds=30)
    sent = received["workflow"]
    check("Run without a prompt", not is_error and sent["6"]["inputs"]["steps"] == 24 and sent["6"]["inputs"]["seed"] == 11
          and sent["3"]["inputs"]["text"] == "Clay Animation, Clay, a fox in a red scarf", text[:80])

    is_error, text = client.call("update_workflow", name="Clay poster", changes={"Render": {"sampler_name": "euler"},
                                                                                "Style LoRA": {"strength_model": 0.5}})
    history = sorted((data / "history").glob("Clay poster-*"))
    check("Update", not is_error and panel_widgets(saved, "Render")[4] == "euler" and panel_widgets(saved, "Style LoRA")[1] == 0.5,
          text[:80])
    check("Previous version kept", len(history) == 2, ", ".join(p.name for p in history))

    graph = {"1": {"class_type": "EmptyImage", "inputs": {"width": 256, "height": 256, "batch_size": 1, "color": 0}},
             "2": {"class_type": "ImageInvert", "inputs": {"image": ["1", 0]}},
             "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "images/white"}}}
    is_error, text = client.call("create_workflow", name="White square", graph=graph)
    check("Create from a graph", not is_error and (panel / "White square.json").exists(), text[:80])
    links = json.loads((panel / "White square.json").read_text())["links"] if not is_error else []
    check("Links in the editor's format", links == [[1, 1, 0, 2, 0, "IMAGE"], [2, 2, 0, 3, 0, "IMAGE"]], json.dumps(links))

    bad = {"1": {"class_type": "EmptyImag", "inputs": {}},
           "2": {"class_type": "KSampler", "inputs": {"steps": 0, "sampler_name": "fast"}}}
    is_error, text = client.call("create_workflow", name="Broken", graph=bad)
    check("Bad graph refused with reasons", is_error and "EmptyImage" in text and "at least 1" in text and "dpm_fast" in text
          and "saves a file" in text and not (panel / "Broken.json").exists(), text.splitlines()[1][:90] if is_error else text[:80])

    is_error, text = client.call("update_workflow", name="03_claymation", changes={"Render": {"steps": 5}})
    check("Studio workflows protected", is_error and "does not change" in text, text[:80])
    is_error, text = client.call("create_workflow", name="03_claymation", based_on="03_claymation")
    check("Studio names protected", is_error and "studio's own" in text, text[:80])
    is_error, text = client.call("create_workflow", name="Clay poster", based_on="03_claymation")
    check("No silent overwrite", is_error and "update_workflow" in text, text[:80])
    is_error, text = client.call("create_workflow", name="../escape", based_on="03_claymation")
    check("Safe names only", is_error and "letters, digits" in text, text[:80])

    saved.write_text(saved.read_text().replace('"Tall clay posters."', '"Edited by hand."'))
    is_error, text = client.call("update_workflow", name="Clay poster", changes={"Render": {"steps": 20}})
    check("Hand edits protected", is_error and "changed by hand" in text, text[:80])
    is_error, text = client.call("run_workflow", workflow="Clay poster", wait_seconds=5)
    check("Run notes hand edits", not is_error and "changed by hand" in text, text[:100])
    is_error, text = client.call("update_workflow", name="Clay poster", changes={"Render": {"steps": 20}},
                                 overwrite_hand_edits=True)
    check("Owner can allow it", not is_error and panel_widgets(saved, "Render")[2] == 20, text[:60])

    saved.unlink()
    is_error, text = client.call("list_workflows")
    check("Deleted in ComfyUI, gone from the list", not is_error and "Clay poster" not in text, "removed from the panel")


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
        check("Tools", tools == ["studio_status", "list_workflows", "run_workflow", "list_node_types", "get_workflow",
                                 "create_workflow", "update_workflow", "job_status", "cancel_jobs", "list_outputs"],
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

        check_workflow_tools(client, studio)

        stderr = client.close()
        check("Quiet on stderr", stderr == "", stderr[:200] or "nothing")
    server.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
