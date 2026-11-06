#!/usr/bin/env python3
"""Sets up the chat assistant: builds its reading material, registers the ComfyUI tools with
LM Studio and AnythingLLM, and loads the material into an AnythingLLM workspace.

Standard library only. Run by milestone4.sh:

  assistant.py knowledge   turn the fetched documentation into plain Markdown files
  assistant.py mcp         write the ComfyUI tool server into both apps' MCP settings
  assistant.py import      create the "Studio Help" workspace and upload the files (needs
                           AnythingLLM running; LM Studio's server for the model choice)
  assistant.py check       PASS/FAIL lines about the workspace, for the test
  assistant.py diagnose    a report to copy and paste when the chat misbehaves
"""
import argparse
import datetime
import json
import os
import pathlib
import plistlib
import re
import secrets
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

STUDIO_HOME = pathlib.Path(os.environ.get("STUDIO_HOME", pathlib.Path.home() / "MacAIStudio"))
KNOWLEDGE_DIR = STUDIO_HOME / "knowledge"
SOURCES_DIR = KNOWLEDGE_DIR / "sources"
WORKSPACE = "Studio Help"
FOLDER = "mac-ai-studio"
KEY_NAME = "Mac AI Studio installer"
LOG_FILE = STUDIO_HOME / "logs" / "assistant.log"
REPORT_FILE = STUDIO_HOME / "logs" / "chat-report.txt"
# Documents added to the workspace per request: each request embeds them before it answers.
EMBED_BATCH = 4
ANYTHINGLLM_SECTIONS = ("agent", "agent-flows", "chatting-with-documents", "features", "installation-desktop",
                        "mcp-compatibility", "setup")
SYSTEM_PROMPT = """You are the help assistant inside Mac AI Studio, an offline creative studio on this Mac. The owner is a writer and designer, not a programmer: answer in plain words, in short numbered steps, and name the tab and the app to use. The tabs are Images & Video (ComfyUI), Music (ACE-Step), Stems & Voices (Demucs, with Analyze and Chords tools), and Chat (AnythingLLM, with LM Studio behind it). Finished files are in the My Files folder (~/MacAIStudio/output). Answer only from the documents you are given. End every answer with a line "Sources:" naming the document and page you used, for example "Sources: ComfyUI - troubleshooting (overview.mdx)". If the documents do not cover the question, say so plainly instead of guessing. Never suggest a cloud service or a terminal command unless the documents give it."""
# Answers come with their sources in a short list; Python package READMEs are long, so each is cut.
DESCRIPTION_LIMIT = 30000
# The packages whose own description (their README) is worth reading; the rest are listed by version.
KEY_PACKAGES = ("torch", "torchaudio", "torchvision", "torchcodec", "numpy", "safetensors", "transformers",
                "diffusers", "accelerate", "peft", "huggingface-hub", "gradio", "librosa", "soundfile", "demucs",
                "mlx", "mlx-lm", "pillow", "av", "einops", "comfyui-frontend-package")
# Run by each environment's own Python, so the versions are the ones actually installed.
PACKAGE_SCRIPT = r"""
import json, sys, importlib.metadata as metadata
wanted = set(sys.argv[1:])
found = {}
for dist in metadata.distributions():
    name = (dist.metadata["Name"] or "").strip()
    if not name:
        continue
    key = name.lower().replace("_", "-")
    entry = {"name": name, "version": dist.version, "summary": dist.metadata["Summary"] or ""}
    if key in wanted:
        text = dist.read_text("METADATA") or ""
        entry["description"] = text.split("\n\n", 1)[1] if "\n\n" in text else ""
    found[key] = entry
print(json.dumps(found))
"""

OVERVIEW = """# Mac AI Studio: what is installed and where

Mac AI Studio is one desktop app (in Applications) with four tabs. Each tab is a separate program running on this Mac only, with no internet needed. Quitting Mac AI Studio stops all of them.

| Tab | Program | What it does |
| --- | --- | --- |
| Images & Video (ComfyUI) | ComfyUI, a node editor | Renders images in three styles (gritty graphic novel, photorealistic human, claymation) and three video flows (text to video, sketch folder to video, sketch-and-fill animation). Each flow is a saved workflow in the Workflows panel (press W), under the Mac AI Studio folder; Pro video flows use Wan 2.2, the others LTX-Video |
| Music (ACE-Step) | ACE-Step 1.5 | Makes complete songs with vocals from a description (caption) and lyrics. Has a LoRA Training tab. Temperature, Top-K and Top-P are under Settings > LM Generation at the top of its page |
| Stems & Voices (Demucs) | Demucs and librosa, in a small page made for the studio | Split Stems: a song into vocals, drums, bass, other and instrumental WAV files (a 6-stem choice adds guitar and piano). Analyze: tempo, key, length and levels of a song. Chords: a text chord chart in letters (C, G, Am, F) with the time each chord starts; with "Separate guitar and keys" on, three charts: main progression, guitar and keys. Voice Profiles: saves singer descriptions to paste into the Music caption |
| Chat (AnythingLLM) | AnythingLLM, with LM Studio running the gpt-oss-120b model | This assistant, in AnythingLLM's own window; the tab shows its status and an Open AnythingLLM button. Answers questions about the studio from its documents. In agent mode (start a message with @agent) it can run the studio's image and video workflows through its ComfyUI tools |

## Folders

- Finished work: `~/MacAIStudio/output` (the **My Files** button). Images in `images/`, videos in `video/`, songs in `music/`, stems in `stems/`, chord charts in `chords/`.
- Sketches for the video flows: `~/MacAIStudio/input/sketches`.
- Models: `~/MacAIStudio/models` (the **Models** button opens Stability Matrix, which manages them).
- Logs: `~/MacAIStudio/logs`, one file per tool and one per install run.
- The assistant's reading material: `~/MacAIStudio/knowledge`.

## Programs that run behind the tabs

- ComfyUI listens on port 18188, ACE-Step on 17860, the stems page on 17870, the Chat tab's status page on 17880, LM Studio's server on 1234, AnythingLLM on 3001. All on 127.0.0.1 only.
- LM Studio is also a normal app in Applications: open it to chat with the model directly, with the same ComfyUI tools under its Integrations button.
- AnythingLLM is an app in Applications. The chat happens in its own window: the Chat tab starts it and LM Studio's server, shows whether both are running, and has an Open AnythingLLM button that brings its window forward. AnythingLLM's desktop app has no web page, so it cannot show inside Mac AI Studio.

## What the assistant's ComfyUI tools do

In agent mode the assistant can call: `list_workflows` (the ready-made workflows, and those the chat made, with an example prompt for each), `run_workflow` (render one with a new prompt; images take about a minute, video much longer), `job_status`, `cancel_jobs`, `list_outputs` (newest files made) and `studio_status`.

It can also make workflows: `create_workflow` saves a new one in ComfyUI's Workflows panel under **Mac AI Studio > From chat**, either as a copy of a studio workflow with changed settings (steps, cfg, sampler, size, LoRA strength, prompt) or as a new graph of installed nodes; `update_workflow` changes one the chat made; `get_workflow` shows a workflow's nodes and settings; `list_node_types` shows the installed nodes and their choices, such as the model and LoRA files. Every workflow is checked against ComfyUI before it is saved, and the previous version of an updated one is kept in `~/MacAIStudio/chat-workflows/history`. The studio's own workflows are never changed; a workflow edited by hand in ComfyUI is only replaced when the owner agrees. The tools cannot delete files, install nodes or models, or reach the internet.

Example requests: "@agent make a copy of the claymation workflow called Clay poster, 832 by 1216, 24 steps"; "@agent in Clay poster, lower the LoRA strength to 0.6"; "@agent run Clay poster with a fox in a red scarf".

## Models for ComfyUI's templates

ComfyUI's Templates window has hundreds of ready-made templates; most need model files the studio does not install. The easy way: press **Get Models** in Mac AI Studio's toolbar, type part of the template's name, click it, and press **Download**; a progress bar shows each file, **Stop** pauses and **Download** resumes. The same from Terminal, in the installer folder, `./get-models.sh "<title on the template's card, or the short name on its tab once opened>"` shows each file, its size and folder, asks, then downloads what is missing from Hugging Face and checks each file's checksum. `./get-models.sh --list` (optionally with a word, such as `--list flux`) lists the templates and what they need; `--check` shows without downloading. Files go into `~/MacAIStudio/models` (checkpoints, LoRAs, VAEs, ControlNets, diffusion models, text encoders) or `~/MacAIStudio/ComfyUI/models` (everything else). After downloading, press R in ComfyUI. Templates marked "online service" cannot run offline; gated models need a Hugging Face login and are downloaded by hand. See the guide "TEMPLATE_MODELS".

## Updating

Quit Mac AI Studio and double-click **Update Mac AI Studio.command** in the installer folder. It updates the programs that come from Homebrew (Git, Python, uv, FFmpeg, Miniconda, Stability Matrix, LM Studio, AnythingLLM) and checks the studio. ComfyUI, ACE-Step, Demucs and the models stay at their tested versions. LM Studio also offers updates by itself when it is opened; accepting them is fine. See the guide "Updating".
"""


def clean(text):
    """Plain Markdown from a docs page: drops the front matter, imports and page components."""
    title = None
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head = text[3:end]
            match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', head, re.M)
            title = match.group(1) if match else None
            text = text[end + 4:]
    text = re.sub(r"^import .*$", "", text, flags=re.M)
    text = re.sub(r"^export .*$", "", text, flags=re.M)
    text = re.sub(r"</?[A-Z][\w.]*(\s[^>]*)?/?>", "", text)
    text = re.sub(r"<(iframe|video)\b.*?</\1>", "", text, flags=re.S)
    text = re.sub(r"<(img|source)\b[^>]*>", "", text)
    text = re.sub(r"\{/\*.*?\*/\}", "", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if title and not text.startswith("#"):
        text = f"# {title}\n\n{text}"
    return text


def merge(paths, heading):
    """One Markdown file from many pages, each under its own path, so citations show the page."""
    parts = [f"# {heading}\n"]
    for path in paths:
        body = clean(path.read_text(encoding="utf-8", errors="replace"))
        if body:
            parts.append(f"\n\n---\n\n*Page: {path.name}*\n\n{body}")
    return "".join(parts)


def pages(root, suffixes=(".md", ".mdx")):
    return sorted(p for p in root.rglob("*") if p.suffix in suffixes and p.is_file())


def write(name, text):
    target = KNOWLEDGE_DIR / f"{name}.md"
    target.write_text(text, encoding="utf-8")
    print(f"{target.name}: {len(text) // 1024} KB")


def packages_page(label, python):
    """The Python packages of one environment, from that environment's own Python: every package
    with its version, then the description of the main ones."""
    try:
        result = subprocess.run([python, "-I", "-c", PACKAGE_SCRIPT, *KEY_PACKAGES],
                                capture_output=True, text=True, timeout=300)
        found = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"WARNING: could not list the packages of {label} ({python}): {error}")
        return None
    folder = pathlib.Path(python).parent.parent
    lines = [f"# Python packages: {label}",
             "",
             f"The Python packages installed for {label}, in `{folder}`, at the exact versions the studio was "
             "tested with. The installer pins every version in its lock files, so do not upgrade them by hand; "
             "see the guide \"Updating\". When a tool reports a missing or broken package, run the milestone "
             "that installed it again.",
             "",
             "| Package | Version | What it is |",
             "| --- | --- | --- |"]
    for key in sorted(found):
        entry = found[key]
        summary = entry["summary"].replace("|", "/").strip()
        lines.append(f"| {entry['name']} | {entry['version']} | {summary} |")
    for key in KEY_PACKAGES:
        entry = found.get(key)
        if entry and entry.get("description", "").strip():
            body = clean(entry["description"])[:DESCRIPTION_LIMIT]
            lines += ["", "---", "", f"## {entry['name']} {entry['version']}", "", body]
    return "\n".join(lines) + "\n"


def cmd_knowledge(args):
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    for stale in KNOWLEDGE_DIR.glob("*.md"):
        stale.unlink()
    write("Mac AI Studio - overview", OVERVIEW)
    repo = pathlib.Path(args.repo_dir)
    for path in [repo / "README.md", *sorted((repo / "docs").glob("*.md")), repo / "assets" / "practice_prompts.md"]:
        write(f"Mac AI Studio - {path.stem}", path.read_text(encoding="utf-8"))

    notes = []
    for path in sorted(pathlib.Path(args.comfyui_dir, "user/default/workflows/Mac AI Studio").rglob("*.json")):
        workflow = json.loads(path.read_text())
        for node in workflow.get("nodes", []):
            if node.get("type") == "Note" and node.get("widgets_values"):
                notes.append(f"\n\n## {path.stem}\n\n{node['widgets_values'][0]}")
    if notes:
        write("Mac AI Studio - workflow notes", "# Notes shown inside each ComfyUI workflow" + "".join(notes))

    for item in args.python or []:
        label, _, python = item.partition("=")
        page = packages_page(label, python)
        if page:
            write(f"Python packages - {label}", page)

    comfy = SOURCES_DIR / "comfyui"
    for folder in sorted(p for p in comfy.glob("*") if p.is_dir() and not p.name.startswith(".")):
        found = pages(folder)
        if found:
            write(f"ComfyUI - {folder.name}", merge(found, f"ComfyUI documentation: {folder.name}"))

    lmstudio = SOURCES_DIR / "lmstudio"
    for folder, label in (("0_app", "app"), ("3_cli", "command line")):
        found = pages(lmstudio / folder)
        if found:
            write(f"LM Studio - {label}", merge(found, f"LM Studio documentation: {label}"))

    anything = SOURCES_DIR / "anythingllm" / "pages"
    if anything.is_dir():
        # Only the parts of AnythingLLM the studio uses: not its cloud, mobile, Docker or paid pages.
        for folder in sorted(p for p in anything.iterdir() if p.is_dir() and p.name in ANYTHINGLLM_SECTIONS):
            found = pages(folder)
            if found:
                write(f"AnythingLLM - {folder.name}", merge(found, f"AnythingLLM documentation: {folder.name}"))
        top = [p for p in anything.glob("*.mdx")]
        if top:
            write("AnythingLLM - pages", merge(sorted(top), "AnythingLLM documentation"))

    demucs = SOURCES_DIR / "demucs"
    if (demucs / "README.md").exists():
        write("Demucs - README", clean((demucs / "README.md").read_text(encoding="utf-8")))
    found = pages(demucs / "docs") if (demucs / "docs").is_dir() else []
    if found:
        write("Demucs - docs", merge(found, "Demucs documentation"))

    matrix = SOURCES_DIR / "stability-matrix" / "README.md"
    if matrix.exists():
        write("Stability Matrix - README", clean(matrix.read_text(encoding="utf-8")))

    ace = pathlib.Path(args.ace_dir)
    if (ace / "README.md").exists():
        write("ACE-Step - README", clean((ace / "README.md").read_text(encoding="utf-8")))
    found = pages(ace / "docs" / "en") if (ace / "docs" / "en").is_dir() else []
    if found:
        write("ACE-Step - docs", merge(found, "ACE-Step documentation"))

    for card in sorted(pathlib.Path(args.models_dir, "model-cards").rglob("README.md")):
        name = f"{card.parent.parent.name}/{card.parent.name}"
        write(f"Model card - {name.replace('/', ' - ')}", f"# Model card: {name}\n\n" + clean(card.read_text(encoding="utf-8")))
    print(f"{len(list(KNOWLEDGE_DIR.glob('*.md')))} files in {KNOWLEDGE_DIR}")


def cmd_mcp(args):
    entry = {
        "command": args.python,
        "args": [args.script],
        "env": {"STUDIO_HOME": str(STUDIO_HOME)},
    }
    for path, extra in ((pathlib.Path(args.lmstudio_file), {}),
                        (pathlib.Path(args.anythingllm_file), {"anythingllm": {"autoStart": True}})):
        settings = {}
        if path.exists():
            try:
                settings = json.loads(path.read_text())
            except ValueError:
                print(f"{path} was not valid JSON and is replaced.")
        servers = settings.setdefault("mcpServers", {})
        servers["mac-ai-studio-comfyui"] = {**entry, **extra}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n")
        print(f"ComfyUI tools registered in {path}")


# ---- Import into AnythingLLM ----------------------------------------------------------------


class Tee:
    """Prints as usual and appends every line to the studio's logs, with the time."""

    def __init__(self, stream, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream, self.file = stream, open(path, "a", encoding="utf-8")
        self.file.write(f"\n=== {sys.argv[1] if len(sys.argv) > 1 else ''} {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")

    def write(self, text):
        self.stream.write(text)
        self.file.write(redact(text))
        self.file.flush()

    def flush(self):
        self.stream.flush()


def redact(text):
    return re.sub(r"studio-[\w-]{8,}", "studio-…", text)


def api(base, key, path, payload=None, method=None, timeout=120):
    data = None
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        # The body says why (a 500 from AnythingLLM carries its message); keep it for the logs.
        detail = error.read().decode("utf-8", "replace")[:500]
        raise urllib.error.URLError(f"{method or ('POST' if data else 'GET')} {path}: HTTP {error.code} {detail}") from error
    return json.loads(body) if body else {}


def upload(base, key, folder, path):
    """Puts one file into AnythingLLM's document library. Adding it to the workspace is a separate,
    checked step (embed_missing): on the client's Mac the upload's addToWorkspaces option left
    every file out of the workspace without an error."""
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
             "Content-Type: text/markdown\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{base}/document/upload/{folder}", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.loads(response.read())


def api_key(storage):
    """The installer's own key in AnythingLLM's database, created the first time."""
    database = storage / "anythingllm.db"
    if not database.exists():
        sys.exit("AnythingLLM has not been opened yet: open the Chat tab once, then run this again.")
    connection = sqlite3.connect(database)
    try:
        row = connection.execute("SELECT secret FROM api_keys WHERE name = ?", (KEY_NAME,)).fetchone()
        if row:
            return row[0]
        secret = "studio-" + secrets.token_urlsafe(24)
        connection.execute("INSERT INTO api_keys (name, secret) VALUES (?, ?)", (KEY_NAME, secret))
        connection.commit()
        return secret
    finally:
        connection.close()


def chat_model(lmstudio_url, match):
    try:
        with urllib.request.urlopen(f"{lmstudio_url}/v1/models", timeout=30) as response:
            models = json.loads(response.read()).get("data", [])
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return next((m["id"] for m in models if match in m["id"]), None)


def set_provider(port, lmstudio_url, model):
    """Makes LM Studio AnythingLLM's model provider, the way its own settings page saves it.

    The desktop app keeps the provider in its environment; its settings page writes it through
    /api/system/update-env, which needs no key while the app has no password (the default). Without
    this, a workspace set to LM Studio fails with "No LMStudio API Base Path was set".
    """
    values = {"LLMProvider": "lmstudio", "LMStudioBasePath": f"{lmstudio_url}/v1"}
    if model:
        values["LMStudioModelPref"] = model
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/system/update-env", data=json.dumps(values).encode(), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            answer = json.loads(response.read() or b"{}")
    except (urllib.error.URLError, OSError, ValueError) as error:
        answer = {"error": str(error)}
    if answer.get("error"):
        print(f"WARNING: could not set LM Studio as AnythingLLM's provider ({answer['error']}). Set it by hand: "
              f"AnythingLLM settings > AI Providers > LLM > LM Studio, base URL {lmstudio_url}/v1.")
        return False
    print(f"AnythingLLM uses LM Studio at {lmstudio_url}/v1.")
    return True


def library(base, key):
    """The files in the studio's folder of AnythingLLM's document library: title -> stored name."""
    known = {}
    for item in api(base, key, "/documents").get("localFiles", {}).get("items", []):
        if item.get("name") == FOLDER:
            for doc in item.get("items", []):
                known[doc.get("title")] = doc.get("name")
    return known


def workspace_paths(base, key, slug):
    found = api(base, key, f"/workspace/{slug}").get("workspace", [{}])
    workspace = found[0] if isinstance(found, list) and found else found if isinstance(found, dict) else {}
    return {doc.get("docpath") for doc in workspace.get("documents", [])}


def embed_missing(base, key, slug, titles):
    """Adds every library file of the studio that the workspace lacks, a few per request, and
    returns the titles still missing afterwards."""
    known = library(base, key)
    present = workspace_paths(base, key, slug)
    todo = [(title, f"{FOLDER}/{known[title]}") for title in titles if title in known and f"{FOLDER}/{known[title]}" not in present]
    absent = [title for title in titles if title not in known]
    if absent:
        print("Not in AnythingLLM's library after the upload: " + ", ".join(absent))
    if todo:
        print(f"Adding {len(todo)} document(s) to the workspace (embedding; the large ComfyUI pages take minutes)")
    for start in range(0, len(todo), EMBED_BATCH):
        batch = todo[start:start + EMBED_BATCH]
        began = datetime.datetime.now()
        try:
            api(base, key, f"/workspace/{slug}/update-embeddings", {"adds": [path for _, path in batch]}, timeout=3600)
            outcome = "done"
        except (urllib.error.URLError, OSError) as error:
            outcome = f"error: {error}"
        seconds = (datetime.datetime.now() - began).total_seconds()
        print(f"  {', '.join(title for title, _ in batch)}: {outcome} ({seconds:.0f} s)")
    present = workspace_paths(base, key, slug)
    known = library(base, key)
    return [title for title in titles if title not in known or f"{FOLDER}/{known[title]}" not in present]


def cmd_import(args):
    storage = pathlib.Path(args.storage)
    base = f"http://127.0.0.1:{args.port}/api/v1"
    key = api_key(storage)
    try:
        api(base, key, "/auth")
    except (urllib.error.URLError, OSError) as error:
        sys.exit(f"AnythingLLM does not answer on port {args.port}: {error}. Open the Chat tab, then run this again.")

    workspaces = api(base, key, "/workspaces").get("workspaces", [])
    existing = next((w for w in workspaces if w["name"] == WORKSPACE), None)
    settings = {
        "openAiPrompt": SYSTEM_PROMPT, "openAiTemp": 0.3, "openAiHistory": 20,
        # Query mode answers only from the documents. No similarity threshold: the small offline
        # embedder often scores a relevant passage below AnythingLLM's default 0.25 for a plain
        # question, and query mode then refuses without asking the model. The 8 closest passages
        # always reach the model, and its instructions say what to do when they do not cover the
        # question, so this reply now only appears when the workspace holds no documents.
        "similarityThreshold": 0.0, "topN": 8, "chatMode": "query",
        "queryRefusalResponse": "The Studio Help workspace has no documents yet. Quit Mac AI Studio and run ./milestone4.sh --import in the installer folder, then ask again.",
    }
    if existing:
        slug = existing["slug"]
        api(base, key, f"/workspace/{slug}/update", settings)
        print(f"Workspace '{WORKSPACE}' already exists ({slug}); settings refreshed.")
    else:
        slug = api(base, key, "/workspace/new", {"name": WORKSPACE, **settings})["workspace"]["slug"]
        print(f"Workspace '{WORKSPACE}' created ({slug}).")

    model = chat_model(args.lmstudio_url, args.match)
    set_provider(args.port, args.lmstudio_url, model)
    if model:
        api(base, key, f"/workspace/{slug}/update",
            {"chatProvider": "lmstudio", "chatModel": model, "agentProvider": "lmstudio", "agentModel": model})
        print(f"Workspace uses LM Studio model {model}.")
    else:
        print(f"WARNING: LM Studio's server did not list a {args.match} model; the workspace keeps the app's default model.")

    files = sorted(pathlib.Path(args.knowledge).glob("*.md"))
    if not files:
        sys.exit(f"No files in {args.knowledge}. Run milestone4.sh again.")
    known = library(base, key)
    stale = [name for title, name in known.items() if title not in {f.name for f in files}]
    if stale:
        try:
            api(base, key, "/system/remove-documents", {"names": [f"{FOLDER}/{n}" for n in stale]}, method="DELETE")
            print(f"Removed {len(stale)} old file(s).")
        except (urllib.error.URLError, OSError) as error:
            print(f"Could not remove old files ({error}); remove the '{FOLDER}' folder in AnythingLLM by hand.")
    for path in files:
        if path.name in known:
            print(f"Already there: {path.name}")
            continue
        try:
            result = upload(base, key, FOLDER, path)
        except urllib.error.HTTPError as error:
            sys.exit(f"Upload of {path.name} failed: {error.read().decode()[:500]}")
        if not result.get("success", True):
            sys.exit(f"Upload of {path.name} failed: {result.get('error')}")
        print(f"Added {path.name}")

    missing = embed_missing(base, key, slug, [f.name for f in files])
    if missing:
        print(f"{len(files) - len(missing)} of {len(files)} documents in the workspace. These are not in the workspace: "
              + ", ".join(missing))
        sys.exit("Some documents could not be added. Run ./milestone4.sh --diagnose and send the report.")
    print(f"{len(files)} of {len(files)} documents in the workspace.")
    print(f"Done. Open the Chat tab and pick the '{WORKSPACE}' workspace.")


def cmd_check(args):
    """PASS/FAIL lines for the test: the provider, the workspace, its model and its documents."""
    base = f"http://127.0.0.1:{args.port}/api/v1"
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/setup-complete", timeout=30) as response:
            current = json.loads(response.read()).get("results", {})
    except (urllib.error.URLError, OSError, ValueError):
        current = {}
    provider_ok = current.get("LLMProvider") == "lmstudio" and bool(current.get("LMStudioBasePath"))
    if provider_ok:
        print(f"PASS  AnythingLLM uses LM Studio at {current['LMStudioBasePath']}")
    else:
        print(f"FAIL  AnythingLLM's LLM provider is {current.get('LLMProvider') or 'not set'}, not LM Studio with an "
              "address. Run ./milestone4.sh --import")
    key = api_key(pathlib.Path(args.storage))
    workspace = next((w for w in api(base, key, "/workspaces").get("workspaces", []) if w["name"] == WORKSPACE), None)
    if not workspace:
        sys.exit(f"FAIL  No '{WORKSPACE}' workspace. Run ./milestone4.sh --import")
    print(f"PASS  Workspace '{WORKSPACE}' with model {workspace.get('chatModel') or 'the app default'}")
    documents = api(base, key, f"/workspace/{workspace['slug']}").get("workspace", [{}])
    count = len((documents[0] if isinstance(documents, list) else documents).get("documents", []))
    print(f"{'PASS' if count else 'FAIL'}  {count} documents in the workspace")
    # The same search a chat question runs, without the model: proves the documents are embedded.
    question = "How do I split a song into stems?"
    try:
        found = api(base, key, f"/workspace/{workspace['slug']}/vector-search",
                    {"query": question, "topN": 4, "scoreThreshold": 0})
    except (urllib.error.URLError, OSError, ValueError) as error:
        found = {"results": [], "message": str(error)}
    results = found.get("results", [])
    if results:
        best = results[0]
        print(f"PASS  A question finds {len(results)} passages; the closest is from "
              f"'{best.get('metadata', {}).get('title')}' (score {best.get('score', 0):.2f})")
    else:
        print(f"FAIL  A question finds no passages ({found.get('message') or 'no results'}). Run ./milestone4.sh --import")
    sys.exit(0 if count and results and provider_ok else 1)


def tail(path, lines=60):
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return [f"(could not read: {error})"]
    return text[-lines:]


def app_version(app):
    try:
        with open(f"/Applications/{app}.app/Contents/Info.plist", "rb") as handle:
            return plistlib.load(handle).get("CFBundleShortVersionString", "unknown")
    except (OSError, ValueError):
        return "not found"


def cmd_diagnose(args):
    """Everything needed to see why the chat misbehaves, in one report, with keys removed."""
    lines = [f"=== Mac AI Studio chat report, {datetime.datetime.now():%Y-%m-%d %H:%M} ===",
             f"AnythingLLM app {app_version('AnythingLLM')}, LM Studio app {app_version('LM Studio')}"]

    def section(title):
        lines.extend(["", f"--- {title} ---"])

    def attempt(label, action):
        try:
            return action()
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, SystemExit) as error:
            lines.append(f"{label}: ERROR {error}")
            return None

    storage = pathlib.Path(args.storage)
    port = args.port
    section("AnythingLLM settings")
    raw = attempt("Settings", lambda: json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/setup-complete", timeout=30).read()).get("results", {}))
    if raw is not None:
        for name in ("LLMProvider", "LMStudioBasePath", "LMStudioModelPref", "EmbeddingEngine", "EmbeddingModelPref",
                     "VectorDB", "MultiUserMode", "RequiresAuth"):
            lines.append(f"{name}: {raw.get(name)}")

    section("LM Studio")
    models = attempt("Models", lambda: json.loads(urllib.request.urlopen(
        f"{args.lmstudio_url}/v1/models", timeout=30).read()).get("data", []))
    if models is not None:
        lines.append("Models: " + (", ".join(m.get("id", "?") for m in models) or "none"))

    section("Studio Help workspace")
    key = attempt("Key", lambda: api_key(storage))
    base = f"http://127.0.0.1:{port}/api/v1"
    workspace = None
    if key:
        workspaces = attempt("Workspaces", lambda: api(base, key, "/workspaces").get("workspaces", []))
        workspace = next((w for w in workspaces or [] if w.get("name") == WORKSPACE), None)
        if workspace:
            for name in ("slug", "chatMode", "similarityThreshold", "topN", "chatProvider", "chatModel",
                         "agentProvider", "agentModel", "vectorSearchMode"):
                lines.append(f"{name}: {workspace.get(name)}")
        else:
            lines.append(f"No '{WORKSPACE}' workspace. Workspaces: {[w.get('name') for w in workspaces or []]}")
    if key and workspace:
        known = attempt("Library", lambda: library(base, key)) or {}
        present = attempt("Workspace documents", lambda: workspace_paths(base, key, workspace["slug"])) or set()
        files = sorted(p.name for p in pathlib.Path(args.knowledge).glob("*.md"))
        lines.append(f"Knowledge files on disk: {len(files)} in {args.knowledge}")
        lines.append(f"In the library folder '{FOLDER}': {len(known)}")
        lines.append(f"In the workspace: {len(present)}")
        outside = [t for t in files if t in known and f"{FOLDER}/{known[t]}" not in present]
        if outside:
            lines.append("In the library but not in the workspace: " + ", ".join(outside))
        never = [t for t in files if t not in known]
        if never:
            lines.append("Never uploaded: " + ", ".join(never))

        section("Search with a sample question")
        found = attempt("Search", lambda: api(base, key, f"/workspace/{workspace['slug']}/vector-search",
                                                {"query": "How do I split a song into stems?", "topN": 4,
                                                 "scoreThreshold": 0}))
        if found is not None:
            results = found.get("results", [])
            lines.append(f"{len(results)} passages. {found.get('message') or ''}".strip())
            for result in results:
                lines.append(f"  {result.get('score', 0):.2f}  {result.get('metadata', {}).get('title')}")

    section("Log files")
    candidates = [pathlib.Path.home() / "Library" / "Logs" / "anythingllm-desktop",
                  pathlib.Path.home() / "Library" / "Logs" / "AnythingLLM",
                  storage / "logs", storage.parent / "logs"]
    logs = sorted({p for folder in candidates if folder.is_dir() for p in folder.glob("*.log")},
                  key=lambda p: p.stat().st_mtime, reverse=True)[:2]
    for path in [*logs, STUDIO_HOME / "logs" / "40-chat.log", LOG_FILE]:
        if path.exists():
            lines.extend(["", f"[{path}] last lines:", *tail(path, 60 if path in logs else 40)])
    if not logs:
        lines.append("No AnythingLLM log file found in " + ", ".join(str(c) for c in candidates))

    report = redact("\n".join(lines)) + "\n"
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved to {REPORT_FILE}. Copy everything from '=== Mac AI Studio chat report' to here.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    knowledge = commands.add_parser("knowledge")
    knowledge.add_argument("--repo-dir", required=True)
    knowledge.add_argument("--comfyui-dir", required=True)
    knowledge.add_argument("--ace-dir", required=True)
    knowledge.add_argument("--models-dir", required=True)
    knowledge.add_argument("--python", action="append", metavar="LABEL=PATH",
                           help="an environment whose packages the assistant should know; repeatable")
    knowledge.set_defaults(run=cmd_knowledge)

    mcp = commands.add_parser("mcp")
    mcp.add_argument("--python", required=True)
    mcp.add_argument("--script", required=True)
    mcp.add_argument("--lmstudio-file", required=True)
    mcp.add_argument("--anythingllm-file", required=True)
    mcp.set_defaults(run=cmd_mcp)

    importer = commands.add_parser("import")
    importer.add_argument("--storage", required=True)
    importer.add_argument("--knowledge", default=str(KNOWLEDGE_DIR))
    importer.add_argument("--port", type=int, default=3001)
    importer.add_argument("--lmstudio-url", default="http://127.0.0.1:1234")
    importer.add_argument("--match", default="gpt-oss-120b")
    importer.set_defaults(run=cmd_import)

    diagnose = commands.add_parser("diagnose")
    diagnose.add_argument("--storage", required=True)
    diagnose.add_argument("--knowledge", default=str(KNOWLEDGE_DIR))
    diagnose.add_argument("--port", type=int, default=3001)
    diagnose.add_argument("--lmstudio-url", default="http://127.0.0.1:1234")
    diagnose.set_defaults(run=cmd_diagnose)

    checker = commands.add_parser("check")
    checker.add_argument("--storage", required=True)
    checker.add_argument("--port", type=int, default=3001)
    checker.set_defaults(run=cmd_check)

    args = parser.parse_args()
    if args.command in ("import", "check"):
        # Kept in ~/MacAIStudio/logs/assistant.log, which the diagnose report includes.
        sys.stdout = Tee(sys.stdout, LOG_FILE)
    args.run(args)


if __name__ == "__main__":
    main()
