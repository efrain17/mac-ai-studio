#!/usr/bin/env python3
"""Downloads the model files a ComfyUI template or saved workflow needs, into the folders the
studio's ComfyUI reads. Run through get-models.sh.

ComfyUI's templates name, for each model loader, the file, its Hugging Face address and the
kind of folder it belongs in ("properties.models" on the node, also inside subgraphs). This
reads that list, shows each file with its size and destination, asks, and downloads what is
missing. Each download is checked against the sha256 that Hugging Face reports for the file.
Only Hugging Face addresses are used, and only plain file names inside the model folders.

Standard library only. Run by the ComfyUI environment's Python, which has the templates.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

STUDIO_HOME = pathlib.Path(os.environ.get("STUDIO_HOME", pathlib.Path.home() / "MacAIStudio"))
MODELS_DIR = STUDIO_HOME / "models"
COMFYUI_DIR = STUDIO_HOME / "ComfyUI"
SAVED_DIR = COMFYUI_DIR / "user" / "default" / "workflows"
# Folder kinds the studio keeps in its shared library (ComfyUI/extra_model_paths.yaml, milestone 1);
# every other kind lives in ComfyUI's own models folder.
LIBRARY = {"checkpoints": "StableDiffusion", "loras": "Lora", "vae": "VAE", "controlnet": "ControlNet",
           "diffusion_models": "DiffusionModels", "unet": "DiffusionModels", "text_encoders": "TextEncoders",
           "clip": "TextEncoders"}
HOSTS = [h.strip() for h in os.environ.get("GET_MODELS_HOSTS", "huggingface.co").split(",") if h.strip()]
FILE_NAME = re.compile(r"^[\w.\- ()+]+$")
SPARE_BYTES = 5 * 10**9


def size_text(count):
    if count is None:
        return "size unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if count < 1000 or unit == "TB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1000


# ---- What there is --------------------------------------------------------------------------


def templates_dir(given):
    if given:
        return pathlib.Path(given)
    try:
        import comfyui_workflow_templates_json as package
    except ImportError:
        sys.exit("ComfyUI's templates are not installed in this environment. Run ./milestone1.sh again.")
    return pathlib.Path(list(package.__path__)[0]) / "templates"


def model_entries(workflow):
    """Every model a workflow names, once, including those inside subgraphs."""
    if not isinstance(workflow, dict):
        return []
    nodes = list(workflow.get("nodes") or [])
    for subgraph in (workflow.get("definitions") or {}).get("subgraphs") or []:
        nodes.extend(subgraph.get("nodes") or [])
    found, seen = [], set()
    for node in nodes:
        for model in (node.get("properties") or {}).get("models") or []:
            key = (model.get("directory"), model.get("name"))
            if isinstance(model, dict) and key not in seen:
                seen.add(key)
                found.append(model)
    return found


def catalog(templates):
    """Templates (from ComfyUI's index) and saved workflows, as dicts with what is needed."""
    items = []
    index = json.loads((templates / "index.json").read_text())
    for group in index:
        for entry in group.get("templates", []):
            path = templates / f"{entry['name']}.json"
            try:
                models = model_entries(json.loads(path.read_text()))
            except (OSError, ValueError):
                models = []
            online = entry.get("openSource") is False or "API" in (entry.get("tags") or [])
            items.append({"kind": "template", "name": entry["name"], "title": entry.get("title") or entry["name"],
                          "group": group.get("title", ""), "models": models, "online": online})
    if SAVED_DIR.is_dir():
        for path in sorted(SAVED_DIR.rglob("*.json")):
            try:
                models = model_entries(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue
            label = str(path.relative_to(SAVED_DIR).with_suffix(""))
            items.append({"kind": "saved", "name": label, "title": label, "group": "Your saved workflows",
                          "models": models, "online": False})
    return items


def find(items, text):
    wanted = " ".join(text.split()).lower()
    exact = [i for i in items if wanted in (i["name"].lower(), i["title"].lower())]
    if exact:
        return exact
    words = wanted.split()
    return [i for i in items if all(w in f"{i['title']} {i['name']}".lower() for w in words)]


def describe(item):
    if item["models"]:
        count = len(item["models"])
        return f"{count} model file{'s' if count != 1 else ''}"
    return "online service, cannot run offline" if item["online"] else "no model files needed"


def show_list(items, heading=None):
    if heading:
        print(heading)
    group = None
    for item in items:
        if item["group"] != group:
            group = item["group"]
            print(f"\n{group}")
        name = f"   ({item['name']})" if item["kind"] == "template" else ""
        print(f"  {item['title']}{name}: {describe(item)}")


# ---- Where files go, and whether they are safe -----------------------------------------------


def destination(model):
    folder = model.get("directory") or ""
    name = model.get("name") or ""
    if not re.fullmatch(r"[a-z0-9_]+", folder):
        return None, f"{folder!r} is not a model folder kind"
    parts = name.split("/")
    if not name or any(p in ("", ".", "..") or not FILE_NAME.match(p) for p in parts):
        return None, "not a plain file name"
    base = MODELS_DIR / LIBRARY[folder] if folder in LIBRARY else COMFYUI_DIR / "models" / folder
    return base.joinpath(*parts), None


def already_there(model, target):
    """In the folder the studio uses, or in ComfyUI's own folder of that kind."""
    other = COMFYUI_DIR / "models" / model["directory"] / model["name"]
    return target.exists() or other.exists()


def allowed(url):
    parsed = urllib.parse.urlparse(url or "")
    if parsed.netloc not in HOSTS:
        return False
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname == "127.0.0.1")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def remote_info(url):
    """(size, sha256, problem) from Hugging Face's answer, without downloading. Follows its own
    redirects (a renamed repository answers 307 with the new address) until the answer that
    carries the file's size and checksum, which comes before the hand-over to the file store."""
    opener = urllib.request.build_opener(NoRedirect)
    host = urllib.parse.urlparse(url).netloc
    for _ in range(6):
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "mac-ai-studio-get-models"})
        try:
            headers = opener.open(request, timeout=30).headers
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                return None, None, "needs a Hugging Face login (a gated model); download it by hand from its page"
            if error.code == 404:
                return None, None, "not found on Hugging Face"
            if error.code not in (301, 302, 303, 307, 308):
                return None, None, f"Hugging Face answered {error.code}"
            headers = error.headers
            following = urllib.parse.urljoin(url, headers.get("Location", ""))
            if not headers.get("X-Linked-Size") and urllib.parse.urlparse(following).netloc == host:
                url = following
                continue
        except (urllib.error.URLError, OSError) as error:
            return None, None, f"could not reach Hugging Face ({error})"
        size = headers.get("X-Linked-Size") or headers.get("Content-Length")
        etag = (headers.get("X-Linked-ETag") or headers.get("ETag") or "").removeprefix("W/").strip('"')
        sha = etag.lower() if re.fullmatch(r"[0-9a-fA-F]{64}", etag) else None
        return (int(size) if size and size.isdigit() and int(size) > 0 else None), sha, None
    return None, None, "Hugging Face kept redirecting"


# ---- Download -------------------------------------------------------------------------------


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, target, size, sha):
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    # Resumes an interrupted download; a finished .part is checked instead of fetched again.
    if not (part.exists() and size and part.stat().st_size == size):
        result = subprocess.run(["curl", "-fL", "--progress-bar", "--retry", "5", "--retry-delay", "5", "--retry-connrefused",
                                 "-C", "-", "-o", str(part), url])
        if result.returncode != 0:
            return f"the download stopped (curl {result.returncode}); run this again to resume"
    if size and part.stat().st_size != size:
        part.unlink()
        return f"the file is {part.stat().st_size if part.exists() else 'not'} bytes, not {size}"
    if sha:
        print(f"  Checking {target.name}…", flush=True)
        actual = sha256_file(part)
        if actual != sha:
            part.unlink()
            return f"its checksum does not match Hugging Face's ({actual[:12]}… instead of {sha[:12]}…); it was deleted"
    part.replace(target)
    return None


def plan_and_get(item, check_only, assume_yes):
    print(f"{item['title']}" + (f" (template {item['name']})" if item["kind"] == "template" else " (your saved workflow)"))
    if not item["models"]:
        if item["online"]:
            print("It uses an online service: no model files to download, and it cannot run offline in the studio.")
        else:
            print("It names no model files: nothing to download.")
        return 0
    rows, todo, problems = [], [], 0
    for model in item["models"]:
        target, why = destination(model)
        name = model.get("name", "?")
        if target is None:
            rows.append((name, None, "-", f"skipped: {why}"))
            problems += 1
            continue
        shown = str(target.parent.relative_to(STUDIO_HOME))
        if already_there(model, target):
            rows.append((name, None, shown, "already there"))
            continue
        if not allowed(model.get("url")):
            rows.append((name, None, shown, f"skipped: not a Hugging Face address ({model.get('url', '')[:60]})"))
            problems += 1
            continue
        size, sha, problem = remote_info(model["url"])
        if problem:
            rows.append((name, size, shown, f"skipped: {problem}"))
            problems += 1
            continue
        rows.append((name, size, shown, "to download"))
        todo.append((model, target, size, sha))
    width = max(len(r[0]) for r in rows)
    for name, size, shown, state in rows:
        print(f"  {name:<{width}}  {size_text(size) if size is not None else '':>9}  {shown:<28}  {state}")
    if not todo:
        print("Nothing to download." + (" Some files need attention; see above." if problems else ""))
        return 1 if problems else 0
    total = sum(size or 0 for _, _, size, _ in todo)
    free = shutil.disk_usage(STUDIO_HOME if STUDIO_HOME.exists() else pathlib.Path.home()).free
    question = (f"Download {len(todo)} file{'s' if len(todo) != 1 else ''}, {size_text(total)}? "
                f"Free on disk: {size_text(free)}.")
    if check_only:
        print(question.replace("?", " needed.", 1) + " Nothing was downloaded (--check).")
        return 0
    if total and free < total + SPARE_BYTES:
        print(f"Not enough free space: {size_text(total)} plus {size_text(SPARE_BYTES)} spare is needed.")
        return 1
    print(question)
    if not assume_yes:
        answer = input("Type yes to start: ").strip().lower()
        if answer not in ("yes", "y"):
            print("Nothing was downloaded.")
            return 0
    failures = 0
    for model, target, size, sha in todo:
        print(f"\n{model['name']} ({size_text(size)}) -> {target.parent}", flush=True)
        problem = download(model["url"], target, size, sha)
        if problem:
            print(f"  FAILED: {problem}")
            failures += 1
        else:
            print("  Done" + (", checksum matches Hugging Face's." if sha else " (Hugging Face gave no checksum for it)."))
    print()
    if failures:
        print(f"{failures} file(s) did not download. Run the same command again: finished files are skipped.")
        return 1
    print("All files are in place. In ComfyUI press R (or reopen the Images & Video tab), then open the template.")
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", nargs="*", help="a template's title or name, or a saved workflow's name")
    parser.add_argument("--list", action="store_true", help="list the matches instead of downloading")
    parser.add_argument("--check", action="store_true", help="show what is needed; download nothing")
    parser.add_argument("--yes", action="store_true", help="do not ask before downloading")
    parser.add_argument("--templates", help="ComfyUI's templates folder (found by itself)")
    args = parser.parse_args()
    items = catalog(templates_dir(args.templates))
    text = " ".join(args.name)
    if not text or args.list:
        matches = find(items, text) if text else items
        show_list(matches, "Use the title as it appears on the card in ComfyUI's Templates window, or any part of it:")
        return 0
    matches = find(items, text)
    if not matches:
        print(f"No template or saved workflow called {text!r}. List them with: ./get-models.sh --list")
        return 1
    if len(matches) > 1:
        show_list(matches[:40], f"{len(matches)} match {text!r}. Type more of the name, or copy one title exactly:")
        return 1
    return plan_and_get(matches[0], args.check, args.yes)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # The list was piped into a command such as head that stopped reading.
        sys.stdout = None
        sys.exit(0)
