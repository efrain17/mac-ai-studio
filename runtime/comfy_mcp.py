#!/usr/bin/env python3
"""Lets the local chat model work the studio's ComfyUI: list the workflows, render one with a new
prompt, follow the job, and find the files it made.

Standard library only. It speaks the Model Context Protocol over stdin and stdout, one JSON
message per line, which is how LM Studio and AnythingLLM start it. It talks only to the studio's
own ComfyUI on 127.0.0.1, starts it through services.sh when needed, and writes only into the
studio's output folder. Read it in full before trusting it; it is about 300 lines.
"""
import json
import os
import pathlib
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

STUDIO_HOME = pathlib.Path(os.environ.get("STUDIO_HOME", pathlib.Path.home() / "MacAIStudio"))
RUNTIME_DIR = STUDIO_HOME / "runtime"
WORKFLOWS_DIR = RUNTIME_DIR / "workflows"
OUTPUT_DIR = STUDIO_HOME / "output"
PORT_FILE = STUDIO_HOME / "run" / "10-images.port"
SERVICE = "10-images"
PROMPT_TITLES = ("Prompt", "Picture prompt")
AVOID_TITLE = "Avoid"
MAX_WAIT = 3600


def log(message):
    print(message, file=sys.stderr, flush=True)


# ---- ComfyUI --------------------------------------------------------------------------------


def server_url():
    """The running ComfyUI, or None. The port can differ from the usual one (see services.sh)."""
    if not PORT_FILE.exists():
        return None
    url = f"http://127.0.0.1:{PORT_FILE.read_text().strip()}"
    try:
        call(url, "/system_stats", timeout=5)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return url


def ensure_server():
    """Starts ComfyUI the same way the desktop app does, and returns its address."""
    url = server_url()
    if url:
        return url
    result = subprocess.run(
        ["/bin/bash", str(RUNTIME_DIR / "services.sh"), "start", SERVICE],
        capture_output=True, text=True, timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError("ComfyUI did not start: " + (result.stderr or result.stdout).strip())
    url = server_url()
    if not url:
        raise RuntimeError("ComfyUI started but does not answer.")
    return url


def call(url, path, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def output_paths(entry):
    """The files a finished job saved, as paths inside the studio's output folder."""
    paths = []
    for output in entry.get("outputs", {}).values():
        for items in output.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and "filename" in item and item.get("type", "output") == "output":
                    paths.append(str(OUTPUT_DIR / item.get("subfolder", "") / item["filename"]))
    return paths


def describe_job(url, prompt_id):
    history = json.loads(call(url, f"/history/{prompt_id}"))
    if prompt_id in history:
        entry = history[prompt_id]
        if entry.get("status", {}).get("status_str") == "success":
            files = output_paths(entry)
            return True, "Finished. Files:\n" + "\n".join(files) if files else "Finished, but it saved no file."
        messages = json.dumps(entry.get("status", {}).get("messages", []))[-1500:]
        return True, "The job failed: " + messages
    queue = json.loads(call(url, "/queue"))
    running = [job[1] for job in queue.get("queue_running", [])]
    pending = [job[1] for job in queue.get("queue_pending", [])]
    if prompt_id in running:
        return False, "Rendering now."
    if prompt_id in pending:
        return False, f"Waiting in line, position {pending.index(prompt_id) + 1} of {len(pending)}."
    return True, "Unknown job. It may have been cancelled, or ComfyUI was restarted."


# ---- Workflows ------------------------------------------------------------------------------


def workflow_files():
    return sorted(WORKFLOWS_DIR.glob("*/*.json"))


def find_workflow(name):
    wanted = name.strip().removesuffix(".json")
    for path in workflow_files():
        if path.stem == wanted or f"{path.parent.name}/{path.stem}" == wanted:
            return path
    raise RuntimeError(f"No workflow named {name!r}. Use list_workflows to see the names.")


def summarize(path):
    workflow = json.loads(path.read_text())
    nodes = workflow.values()
    prompt = next((n["inputs"]["text"] for n in nodes if n["_meta"]["title"] == PROMPT_TITLES[0]), "")
    size = next(({k: v for k, v in n["inputs"].items() if k in ("width", "height", "length")}
                 for n in nodes if "width" in n["inputs"] and "height" in n["inputs"]), {})
    kind = "video" if any(n["class_type"] == "SaveVideo" for n in nodes) else "image"
    return {
        "name": path.stem,
        "group": path.parent.name,
        "makes": kind,
        "size": size,
        "example_prompt": prompt[:300],
    }


def prepare(path, prompt, avoid, seed, width, height):
    workflow = json.loads(path.read_text())
    set_prompt = False
    for node in workflow.values():
        title = node["_meta"]["title"]
        inputs = node["inputs"]
        if node["class_type"] == "CLIPTextEncode" and title in PROMPT_TITLES:
            inputs["text"] = prompt
            set_prompt = True
        elif node["class_type"] == "CLIPTextEncode" and title == AVOID_TITLE and avoid:
            inputs["text"] = avoid
        for key in ("seed", "noise_seed"):
            if key in inputs and isinstance(inputs[key], int):
                inputs[key] = seed
        if width and height and node["class_type"] == "EmptyLatentImage":
            inputs["width"], inputs["height"] = width, height
    if not set_prompt:
        raise RuntimeError(f"{path.stem} has no prompt box to fill.")
    return workflow


# ---- Tools ----------------------------------------------------------------------------------


def tool_studio_status():
    url = server_url()
    if not url:
        return "ComfyUI is not running. It starts by itself when a workflow is run (about a minute)."
    queue = json.loads(call(url, "/queue"))
    return (f"ComfyUI is running at {url}. Rendering now: {len(queue.get('queue_running', []))}, "
            f"waiting: {len(queue.get('queue_pending', []))}. Files are saved under {OUTPUT_DIR}.")


def tool_list_workflows():
    items = [summarize(path) for path in workflow_files()]
    if not items:
        return "No workflows are installed. Run milestone4.sh again."
    return json.dumps(items, indent=1)


def tool_run_workflow(workflow, prompt, avoid=None, seed=None, width=None, height=None, wait_seconds=180):
    if not prompt or not prompt.strip():
        raise RuntimeError("Give a prompt: what the picture or video should show.")
    path = find_workflow(workflow)
    if width or height:
        if not (width and height) or width % 8 or height % 8:
            raise RuntimeError("Give both width and height, as multiples of 8.")
        if summarize(path)["makes"] == "video":
            raise RuntimeError("Video size is fixed by the workflow; only images take a size.")
    seed = int(seed) if seed is not None else random.randrange(1, 2**31)
    url = ensure_server()
    payload = {"prompt": prepare(path, prompt.strip(), avoid, seed, width, height), "client_id": uuid.uuid4().hex}
    try:
        prompt_id = json.loads(call(url, "/prompt", payload))["prompt_id"]
    except urllib.error.HTTPError as error:
        raise RuntimeError("ComfyUI rejected the workflow: " + error.read().decode()[:1500]) from error
    head = f"Job {prompt_id} started with {path.stem} (seed {seed}). "
    deadline = time.time() + min(int(wait_seconds or 0), MAX_WAIT)
    while True:
        done, text = describe_job(url, prompt_id)
        if done:
            return head + text
        if time.time() >= deadline:
            return head + text + f" Check later with job_status, id {prompt_id}. Video can take an hour or more."
        time.sleep(3)


def tool_job_status(prompt_id):
    url = server_url()
    if not url:
        return "ComfyUI is not running, so no job is in progress."
    return describe_job(url, prompt_id)[1]


def tool_cancel_jobs():
    url = server_url()
    if not url:
        return "ComfyUI is not running; nothing to cancel."
    call(url, "/interrupt", {})
    call(url, "/queue", {"clear": True})
    return "Stopped the current render and emptied the queue."


def tool_list_outputs(limit=20):
    files = [p for p in OUTPUT_DIR.rglob("*") if p.is_file() and not p.name.startswith(".")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    limit = max(1, min(int(limit or 20), 200))
    if not files:
        return f"Nothing has been made yet. Files will appear under {OUTPUT_DIR}."
    return "\n".join(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}  {p}" for p in files[:limit])


TOOLS = [
    {
        "name": "studio_status",
        "description": "Whether the studio's ComfyUI is running, what it is rendering, and where files are saved.",
        "inputSchema": {"type": "object", "properties": {}},
        "run": lambda **_: tool_studio_status(),
    },
    {
        "name": "list_workflows",
        "description": ("The studio's ready-made image and video workflows, with the size each one makes and an "
                        "example prompt. Use the 'name' with run_workflow."),
        "inputSchema": {"type": "object", "properties": {}},
        "run": lambda **_: tool_list_workflows(),
    },
    {
        "name": "run_workflow",
        "description": ("Render an image or video with one of the studio's workflows and a new prompt. Keep the "
                        "style words from the example prompt. Images finish in about a minute; a video can take an "
                        "hour or more, so the tool returns a job id to check with job_status."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow": {"type": "string", "description": "A name from list_workflows, e.g. 03_claymation"},
                "prompt": {"type": "string", "description": "What to show, including the style words"},
                "avoid": {"type": "string", "description": "What to keep out of the picture (optional)"},
                "seed": {"type": "integer", "description": "Repeat a result with the same seed (optional)"},
                "width": {"type": "integer", "description": "Image width in pixels, multiple of 8 (images only)"},
                "height": {"type": "integer", "description": "Image height in pixels, multiple of 8 (images only)"},
                "wait_seconds": {"type": "integer", "description": "How long to wait for the result; default 180"},
            },
            "required": ["workflow", "prompt"],
        },
        "run": lambda **kw: tool_run_workflow(**kw),
    },
    {
        "name": "job_status",
        "description": "Progress of a render started with run_workflow, and its files once finished.",
        "inputSchema": {"type": "object", "properties": {"prompt_id": {"type": "string"}}, "required": ["prompt_id"]},
        "run": lambda **kw: tool_job_status(**kw),
    },
    {
        "name": "cancel_jobs",
        "description": "Stop the render in progress and empty the queue.",
        "inputSchema": {"type": "object", "properties": {}},
        "run": lambda **_: tool_cancel_jobs(),
    },
    {
        "name": "list_outputs",
        "description": "The newest files the studio has made (images, videos, songs, stems), newest first.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "Default 20"}}},
        "run": lambda **kw: tool_list_outputs(**kw),
    },
]


# ---- Protocol -------------------------------------------------------------------------------


def handle(message):
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mac-ai-studio-comfyui", "version": "1.0"},
            "instructions": ("Tools for the Mac AI Studio's ComfyUI. Call list_workflows first, then run_workflow "
                             "with a prompt that keeps the example's style words."),
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{k: v for k, v in tool.items() if k != "run"} for tool in TOOLS]}
    if method == "tools/call":
        name = params.get("name")
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None:
            return {"content": [{"type": "text", "text": f"Unknown tool {name!r}."}], "isError": True}
        try:
            text = tool["run"](**(params.get("arguments") or {}))
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except (RuntimeError, TypeError, ValueError, OSError, urllib.error.URLError, subprocess.SubprocessError) as error:
            return {"content": [{"type": "text", "text": f"{type(error).__name__}: {error}"}], "isError": True}
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            log(f"comfy_mcp: not JSON: {line[:200]}")
            continue
        if "id" not in message:
            continue  # a notification, such as notifications/initialized
        try:
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": handle(message)}
        except LookupError as error:
            reply = {"jsonrpc": "2.0", "id": message["id"],
                     "error": {"code": -32601, "message": f"Method not found: {error}"}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
