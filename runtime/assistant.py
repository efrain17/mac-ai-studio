#!/usr/bin/env python3
"""Sets up the chat assistant: builds its reading material, registers the ComfyUI tools with
LM Studio and AnythingLLM, and loads the material into an AnythingLLM workspace.

Standard library only. Run by milestone4.sh:

  assistant.py knowledge   turn the fetched documentation into plain Markdown files
  assistant.py mcp         write the ComfyUI tool server into both apps' MCP settings
  assistant.py import      create the "Studio Help" workspace and upload the files (needs
                           AnythingLLM running; LM Studio's server for the model choice)
  assistant.py check       PASS/FAIL lines about the workspace, for the test
"""
import argparse
import json
import os
import pathlib
import re
import secrets
import sqlite3
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
ANYTHINGLLM_SECTIONS = ("agent", "agent-flows", "chatting-with-documents", "features", "installation-desktop",
                        "mcp-compatibility", "setup")
SYSTEM_PROMPT = """You are the help assistant inside Mac AI Studio, an offline creative studio on this Mac. The owner is a writer and designer, not a programmer: answer in plain words, in short numbered steps, and name the tab and the app to use. The tabs are Images & Video (ComfyUI), Music (ACE-Step), Stems & Voices (Demucs, with an Analyze tool), and Chat (AnythingLLM, with LM Studio behind it). Finished files are in the My Files folder (~/MacAIStudio/output). Answer from the documents when they cover the question, and say so when they do not. Never suggest a cloud service or a terminal command unless the documents give it."""

OVERVIEW = """# Mac AI Studio: what is installed and where

Mac AI Studio is one desktop app (in Applications) with four tabs. Each tab is a separate program running on this Mac only, with no internet needed. Quitting Mac AI Studio stops all of them.

| Tab | Program | What it does |
| --- | --- | --- |
| Images & Video (ComfyUI) | ComfyUI, a node editor | Renders images in three styles (gritty graphic novel, photorealistic human, claymation) and three video flows (text to video, sketch folder to video, sketch-and-fill animation). Each flow is a saved workflow in the Workflows panel (press W), under the Mac AI Studio folder; Pro video flows use Wan 2.2, the others LTX-Video |
| Music (ACE-Step) | ACE-Step 1.5 | Makes complete songs with vocals from a description (caption) and lyrics. Has a LoRA Training tab. Temperature, Top-K and Top-P are under Settings > LM Generation at the top of its page |
| Stems & Voices (Demucs) | Demucs, in a small page made for the studio | Split Stems: a song into vocals, drums, bass, other and instrumental WAV files (a 6-stem choice adds guitar and piano). Analyze: tempo, key, length and levels of a song (librosa). Voice Profiles: saves singer descriptions to paste into the Music caption |
| Chat (AnythingLLM) | AnythingLLM, with LM Studio running the gpt-oss-120b model | This assistant. Answers questions about the studio from its documents. In agent mode (start a message with @agent) it can run the studio's image and video workflows through its ComfyUI tools |

## Folders

- Finished work: `~/MacAIStudio/output` (the **My Files** button). Images in `images/`, videos in `video/`, songs in `music/`, stems in `stems/`.
- Sketches for the video flows: `~/MacAIStudio/input/sketches`.
- Models: `~/MacAIStudio/models` (the **Models** button opens Stability Matrix, which manages them).
- Logs: `~/MacAIStudio/logs`, one file per tool and one per install run.
- The assistant's reading material: `~/MacAIStudio/knowledge`.

## Programs that run behind the tabs

- ComfyUI listens on port 18188, ACE-Step on 17860, the stems page on 17870, LM Studio's server on 1234, AnythingLLM on 3001. All on 127.0.0.1 only.
- LM Studio is also a normal app in Applications: open it to chat with the model directly, with the same ComfyUI tools under its Integrations button.
- AnythingLLM is also an app in Applications; the Chat tab shows its page.

## What the assistant's ComfyUI tools do

In agent mode the assistant can call: `list_workflows` (the ready-made workflows and an example prompt for each), `run_workflow` (render one with a new prompt; images take about a minute, video much longer), `job_status`, `cancel_jobs`, `list_outputs` (newest files made) and `studio_status`. It cannot change the workflows themselves, delete files, or reach the internet.

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

    comfy = SOURCES_DIR / "comfyui"
    for folder in sorted(p for p in comfy.iterdir() if p.is_dir() and not p.name.startswith(".")):
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


def api(base, key, path, payload=None, method=None, timeout=120):
    data = None
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else {}


def upload(base, key, folder, path, workspace):
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in (("addToWorkspaces", workspace),):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
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
        "similarityThreshold": 0.25, "topN": 8, "chatMode": "chat",
        "queryRefusalResponse": "The studio's documents do not cover that. Ask about the tabs, the workflows, the music tools or the files.",
    }
    if existing:
        slug = existing["slug"]
        api(base, key, f"/workspace/{slug}/update", settings)
        print(f"Workspace '{WORKSPACE}' already exists ({slug}); settings refreshed.")
    else:
        slug = api(base, key, "/workspace/new", {"name": WORKSPACE, **settings})["workspace"]["slug"]
        print(f"Workspace '{WORKSPACE}' created ({slug}).")

    model = chat_model(args.lmstudio_url, args.match)
    if model:
        api(base, key, f"/workspace/{slug}/update",
            {"chatProvider": "lmstudio", "chatModel": model, "agentProvider": "lmstudio", "agentModel": model})
        print(f"Workspace uses LM Studio model {model}.")
    else:
        print(f"WARNING: LM Studio's server did not list a {args.match} model; the workspace keeps the app's default model.")

    known = {}
    for item in api(base, key, "/documents").get("localFiles", {}).get("items", []):
        if item.get("name") == FOLDER:
            for doc in item.get("items", []):
                known[doc.get("title")] = doc.get("name")
    files = sorted(pathlib.Path(args.knowledge).glob("*.md"))
    if not files:
        sys.exit(f"No files in {args.knowledge}. Run milestone4.sh again.")
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
            result = upload(base, key, FOLDER, path, slug)
        except urllib.error.HTTPError as error:
            sys.exit(f"Upload of {path.name} failed: {error.read().decode()[:500]}")
        if not result.get("success", True):
            sys.exit(f"Upload of {path.name} failed: {result.get('error')}")
        print(f"Added {path.name}")
    print(f"Done. Open the Chat tab and pick the '{WORKSPACE}' workspace.")


def cmd_check(args):
    """PASS/FAIL lines for the test: the workspace, its model and its documents."""
    base = f"http://127.0.0.1:{args.port}/api/v1"
    key = api_key(pathlib.Path(args.storage))
    workspace = next((w for w in api(base, key, "/workspaces").get("workspaces", []) if w["name"] == WORKSPACE), None)
    if not workspace:
        sys.exit(f"FAIL  No '{WORKSPACE}' workspace. Run ./milestone4.sh --import")
    print(f"PASS  Workspace '{WORKSPACE}' with model {workspace.get('chatModel') or 'the app default'}")
    documents = api(base, key, f"/workspace/{workspace['slug']}").get("workspace", [{}])
    count = len((documents[0] if isinstance(documents, list) else documents).get("documents", []))
    print(f"{'PASS' if count else 'FAIL'}  {count} documents in the workspace")
    sys.exit(0 if count else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    knowledge = commands.add_parser("knowledge")
    knowledge.add_argument("--repo-dir", required=True)
    knowledge.add_argument("--comfyui-dir", required=True)
    knowledge.add_argument("--ace-dir", required=True)
    knowledge.add_argument("--models-dir", required=True)
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

    checker = commands.add_parser("check")
    checker.add_argument("--storage", required=True)
    checker.add_argument("--port", type=int, default=3001)
    checker.set_defaults(run=cmd_check)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
