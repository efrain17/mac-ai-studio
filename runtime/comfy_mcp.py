#!/usr/bin/env python3
"""Lets the local chat model work the studio's ComfyUI: list the workflows, render one with a new
prompt, follow the job, find the files it made, and create and update workflows of its own.

Standard library only. It speaks the Model Context Protocol over stdin and stdout, one JSON
message per line, which is how LM Studio and AnythingLLM start it. It talks only to the studio's
own ComfyUI on 127.0.0.1 and starts it through services.sh when needed. It writes only into the
studio's output folder, the Workflows panel's "Mac AI Studio/From chat" folder and
~/MacAIStudio/chat-workflows (see comfy_workflows.py); the studio's own workflows are never
changed. Read both files in full before trusting them.
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

import comfy_workflows as chat

STUDIO_HOME = pathlib.Path(os.environ.get("STUDIO_HOME", pathlib.Path.home() / "MacAIStudio"))
RUNTIME_DIR = STUDIO_HOME / "runtime"
WORKFLOWS_DIR = RUNTIME_DIR / "workflows"
OUTPUT_DIR = STUDIO_HOME / "output"
STORE = chat.Store(STUDIO_HOME, STUDIO_HOME / "ComfyUI")
CHAT_GROUP = "From chat"
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


_object_info = {}


def object_info(url):
    """ComfyUI's description of every installed node, read once per session."""
    if not _object_info:
        _object_info.update(json.loads(call(url, "/object_info", timeout=300)))
    return _object_info


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


def studio_names():
    return [path.stem for path in workflow_files()]


def load_workflow(name):
    """(graph, group, editable) for a studio workflow or one the chat made."""
    wanted = (name or "").strip().removesuffix(".json")
    if wanted.startswith(CHAT_GROUP + "/"):
        wanted = wanted[len(CHAT_GROUP) + 1:]
    for path in workflow_files():
        if path.stem == wanted or f"{path.parent.name}/{path.stem}" == wanted:
            return json.loads(path.read_text()), path.parent.name, False
    if wanted in STORE.names():
        return STORE.load(wanted)["api"], CHAT_GROUP, True
    raise RuntimeError(f"No workflow named {name!r}. Use list_workflows to see the names.")


def summarize(name, graph, group, editable, description=None):
    nodes = graph.values()
    prompt = next((n["inputs"].get("text", "") for n in nodes if n["_meta"]["title"] in PROMPT_TITLES), "")
    size = next(({k: v for k, v in n["inputs"].items() if k in ("width", "height", "length")}
                 for n in nodes if "width" in n["inputs"] and "height" in n["inputs"]), {})
    kind = "video" if any(n["class_type"] in ("SaveVideo", "SaveAnimatedWEBP", "SaveWEBM") for n in nodes) else "image"
    item = {"name": name, "group": group, "makes": kind, "size": size, "example_prompt": str(prompt)[:300]}
    if editable:
        item["made_by_chat"] = True
        item["description"] = description or ""
    return item


def prepare(graph, prompt, avoid, seed, width, height):
    workflow = json.loads(json.dumps(graph))
    set_prompt = False
    for node in workflow.values():
        title = node["_meta"]["title"]
        inputs = node["inputs"]
        if node["class_type"] == "CLIPTextEncode" and title in PROMPT_TITLES and prompt:
            inputs["text"] = prompt
            set_prompt = True
        elif node["class_type"] == "CLIPTextEncode" and title == AVOID_TITLE and avoid:
            inputs["text"] = avoid
        for key in ("seed", "noise_seed"):
            if key in inputs and isinstance(inputs[key], int):
                inputs[key] = seed
        if width and height and node["class_type"] == "EmptyLatentImage":
            inputs["width"], inputs["height"] = width, height
    if prompt and not set_prompt:
        raise RuntimeError("This workflow has no node titled 'Prompt' to fill. Run it without a prompt, or update it.")
    return workflow


def set_texts(graph, prompt, avoid):
    """The prompt and avoid shortcuts of create_workflow and update_workflow."""
    for node in graph.values():
        if node["class_type"] != "CLIPTextEncode":
            continue
        if prompt and node["_meta"]["title"] in PROMPT_TITLES:
            node["inputs"]["text"] = prompt
        elif avoid and node["_meta"]["title"] == AVOID_TITLE:
            node["inputs"]["text"] = avoid
    return graph


def save_chat_workflow(name, graph, description, based_on, created):
    url = ensure_server()
    info = object_info(url)
    graph, notes = chat.validate(graph, info)
    note = (description or "").strip() or None
    marker = {"made_by": "chat assistant", "name": name, "based_on": based_on}
    ui = chat.to_editor(graph, info, note=note, marker=marker)
    record = {"name": name, "description": description or "", "based_on": based_on, "created": created,
              "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    path = STORE.save(name, graph, ui, record)
    lines = [f"Saved {name!r} with {len(graph)} nodes. It is in ComfyUI's Workflows panel (press W) under "
             f"Mac AI Studio > From chat, file {path}. Run it with run_workflow, name {name!r}."]
    if notes:
        lines.append("Filled in: " + " ".join(notes))
    return "\n".join(lines)


# ---- Tools ----------------------------------------------------------------------------------


def tool_studio_status():
    url = server_url()
    if not url:
        return "ComfyUI is not running. It starts by itself when a workflow is run (about a minute)."
    queue = json.loads(call(url, "/queue"))
    return (f"ComfyUI is running at {url}. Rendering now: {len(queue.get('queue_running', []))}, "
            f"waiting: {len(queue.get('queue_pending', []))}. Files are saved under {OUTPUT_DIR}.")


def tool_list_workflows():
    items = [summarize(p.stem, json.loads(p.read_text()), p.parent.name, False) for p in workflow_files()]
    for name in STORE.names():
        record = STORE.load(name)
        items.append(summarize(name, record["api"], CHAT_GROUP, True, record.get("description")))
    if not items:
        return "No workflows are installed. Run milestone4.sh again."
    return json.dumps(items, indent=1)


def tool_run_workflow(workflow, prompt=None, avoid=None, seed=None, width=None, height=None, wait_seconds=180):
    graph, group, editable = load_workflow(workflow)
    name = workflow.strip().removesuffix(".json").split("/")[-1]
    if not editable and (not prompt or not prompt.strip()):
        raise RuntimeError("Give a prompt: what the picture or video should show.")
    if width or height:
        if not (width and height) or width % 8 or height % 8:
            raise RuntimeError("Give both width and height, as multiples of 8.")
        if summarize(name, graph, group, editable)["makes"] == "video":
            raise RuntimeError("Video size is fixed by the workflow; only images take a size.")
    hand_note = ""
    if editable and STORE.edited_by_hand(name):
        hand_note = (" Note: this workflow was changed by hand in ComfyUI since the chat saved it; this run uses the "
                     "chat's saved version. Run it from ComfyUI to include the changes made by hand.")
    seed = int(seed) if seed is not None else random.randrange(1, 2**31)
    url = ensure_server()
    payload = {"prompt": prepare(graph, (prompt or "").strip(), avoid, seed, width, height), "client_id": uuid.uuid4().hex}
    try:
        prompt_id = json.loads(call(url, "/prompt", payload))["prompt_id"]
    except urllib.error.HTTPError as error:
        raise RuntimeError("ComfyUI rejected the workflow: " + error.read().decode()[:1500]) from error
    head = f"Job {prompt_id} started with {name} (seed {seed}).{hand_note} "
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


def tool_list_node_types(search="", limit=25):
    info = object_info(ensure_server())
    names = chat.search_nodes(info, search, limit)
    if not names:
        return f"No node matches {search!r}. Try one word, such as 'sampler', 'lora', 'upscale' or 'save'."
    return "\n".join(chat.describe_node(name, info[name]) for name in names)


def tool_get_workflow(name):
    graph, group, editable = load_workflow(name)
    head = (f"{name} ({group}), {'made by the chat: update_workflow can change it' if editable else 'a studio workflow: '}"
            f"{'' if editable else 'use it as based_on for create_workflow; it is never changed itself'}.")
    return head + "\nGraph in API format:\n" + json.dumps(graph, indent=1)


def tool_create_workflow(name, based_on=None, graph=None, changes=None, prompt=None, avoid=None, description=None):
    name = chat.check_name(name, studio_names())
    if name in STORE.names():
        raise RuntimeError(f"The chat already made {name!r}. Use update_workflow to change it, or pick another name.")
    if graph:
        start = chat.normalize(graph)
    elif based_on:
        start = chat.normalize(load_workflow(based_on)[0])
    else:
        raise RuntimeError("Give based_on (a workflow from list_workflows to start from) or a full graph.")
    start = set_texts(chat.apply_changes(start, changes), prompt, avoid)
    return save_chat_workflow(name, start, description, based_on, time.strftime("%Y-%m-%d %H:%M:%S"))


def tool_update_workflow(name, graph=None, changes=None, prompt=None, avoid=None, description=None,
                         overwrite_hand_edits=False):
    name = (name or "").strip().removesuffix(".json").removeprefix(CHAT_GROUP + "/")
    if name in studio_names():
        raise RuntimeError(f"{name!r} is one of the studio's own workflows, which the chat does not change. "
                           "Use create_workflow with based_on to make a copy to change.")
    record = STORE.load(name)
    if STORE.edited_by_hand(name) and not overwrite_hand_edits:
        raise RuntimeError(f"{name!r} was changed by hand in ComfyUI after the chat saved it. Ask the owner before "
                           "replacing those changes; to replace them, call again with overwrite_hand_edits true. "
                           "The current file is kept in chat-workflows/history either way.")
    if not (graph or changes or prompt or avoid or description is not None):
        raise RuntimeError("Nothing to change: give changes, a new graph, prompt, avoid or description.")
    start = chat.normalize(graph) if graph else record["api"]
    start = set_texts(chat.apply_changes(start, changes), prompt, avoid)
    text = description if description is not None else record.get("description")
    return save_chat_workflow(name, start, text, record.get("based_on"), record.get("created"))


GRAPH_HELP = ('A workflow in API format: {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": '
              '"sd_xl_base_1.0.safetensors"}, "_meta": {"title": "Model"}}, "2": {...}}. A link is [node id, output '
              'number], e.g. "clip": ["1", 1]. Title the text node with the picture\'s description "Prompt" and the '
              'negative one "Avoid" so run_workflow can fill them.')
CHANGES_HELP = ('Changes to make, by node title or id: {"Render": {"steps": 40, "cfg": 6.5}, "Style LoRA": '
                '{"strength_model": 0.6}}. Use get_workflow to see the titles and inputs.')

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
                "prompt": {"type": "string", "description": "What to show, including the style words. Optional for "
                                                             "workflows the chat made, which can run as saved"},
                "avoid": {"type": "string", "description": "What to keep out of the picture (optional)"},
                "seed": {"type": "integer", "description": "Repeat a result with the same seed (optional)"},
                "width": {"type": "integer", "description": "Image width in pixels, multiple of 8 (images only)"},
                "height": {"type": "integer", "description": "Image height in pixels, multiple of 8 (images only)"},
                "wait_seconds": {"type": "integer", "description": "How long to wait for the result; default 180"},
            },
            "required": ["workflow"],
        },
        "run": lambda **kw: tool_run_workflow(**kw),
    },
    {
        "name": "list_node_types",
        "description": ("Search the nodes installed in the studio's ComfyUI and see each one's inputs, choices (such as "
                        "the installed model and LoRA files) and outputs. Use it before building or changing a graph."),
        "inputSchema": {"type": "object", "properties": {
            "search": {"type": "string", "description": "Words to look for, e.g. 'lora', 'upscale image', 'ksampler'"},
            "limit": {"type": "integer", "description": "How many nodes to show, default 25"}}},
        "run": lambda **kw: tool_list_node_types(**kw),
    },
    {
        "name": "get_workflow",
        "description": "The full graph of a workflow from list_workflows, with every node's title and settings.",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        "run": lambda **kw: tool_get_workflow(**kw),
    },
    {
        "name": "create_workflow",
        "description": ("Create a new ComfyUI workflow and save it in the Workflows panel under Mac AI Studio > From chat. "
                        "Easiest: start from a studio workflow with based_on and give changes. For a new structure, "
                        "give a full graph (check node names with list_node_types). The graph is checked against "
                        "ComfyUI before saving; errors say what to fix. The studio's own workflows are never changed."),
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "3 to 60 letters, digits, spaces, - or _"},
            "based_on": {"type": "string", "description": "A workflow name from list_workflows to start from"},
            "graph": {"type": "object", "description": GRAPH_HELP},
            "changes": {"type": "object", "description": CHANGES_HELP},
            "prompt": {"type": "string", "description": "Text for the node titled Prompt (optional)"},
            "avoid": {"type": "string", "description": "Text for the node titled Avoid (optional)"},
            "description": {"type": "string", "description": "What it is for; shown as a note in ComfyUI"}},
            "required": ["name"]},
        "run": lambda **kw: tool_create_workflow(**kw),
    },
    {
        "name": "update_workflow",
        "description": ("Change a workflow the chat created (only those; the studio's own are never changed). Give "
                        "changes for a few settings, or a full graph to replace it. The previous version is kept."),
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "A workflow from list_workflows with made_by_chat true"},
            "graph": {"type": "object", "description": GRAPH_HELP},
            "changes": {"type": "object", "description": CHANGES_HELP},
            "prompt": {"type": "string"}, "avoid": {"type": "string"}, "description": {"type": "string"},
            "overwrite_hand_edits": {"type": "boolean",
                                     "description": "Only after the owner agrees: replace changes made by hand in ComfyUI"}},
            "required": ["name"]},
        "run": lambda **kw: tool_update_workflow(**kw),
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
                             "with a prompt that keeps the example's style words. To make a new workflow, use "
                             "create_workflow (based_on a studio workflow plus changes is the most reliable); to change "
                             "one the chat made, update_workflow. Both save into ComfyUI's Workflows panel."),
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
        except (RuntimeError, TypeError, ValueError, KeyError, OSError, urllib.error.URLError,
                subprocess.SubprocessError) as error:
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
