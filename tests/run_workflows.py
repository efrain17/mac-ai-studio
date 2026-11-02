#!/usr/bin/env python3
"""Runs workflows through a running ComfyUI and saves what they produce.

Standard library only. Exits non-zero if a render fails or an image comes back blank.
"""
import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def call(server, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        server + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def make_quick(workflow, width=512, height=320, frames=33):
    """Shrinks a video workflow so a test finishes in minutes.

    Sizes must be multiples of 32 and frames one more than a multiple of 8, so that both LTX and
    Wan accept them.
    """
    for node in workflow.values():
        inputs = node["inputs"]
        if "width" in inputs and "height" in inputs:
            inputs["width"], inputs["height"] = width, height
        if "length" in inputs:
            inputs["length"] = frames
        if node["class_type"] == "ProgressiveRevealMask":
            inputs["frames"] = frames
        if node["class_type"] == "EmptyImage":
            inputs["batch_size"] = frames


def render(server, workflow, timeout):
    payload = {"prompt": workflow, "client_id": uuid.uuid4().hex}
    try:
        prompt_id = json.loads(call(server, "/prompt", payload))["prompt_id"]
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"ComfyUI rejected the workflow: {error.read().decode()}") from error

    deadline = time.time() + timeout
    while time.time() < deadline:
        history = json.loads(call(server, f"/history/{prompt_id}"))
        if prompt_id in history:
            entry = history[prompt_id]
            if entry["status"].get("status_str") != "success":
                raise RuntimeError(json.dumps(entry["status"].get("messages"))[-2000:])
            return [
                item
                for output in entry["outputs"].values()
                for items in output.values()
                if isinstance(items, list)
                for item in items
                if isinstance(item, dict) and "filename" in item
            ]
        time.sleep(3)
    raise RuntimeError(f"Timed out after {timeout} s")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--workflows", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--quick", action="store_true", help="small, short video for a smoke test")
    parser.add_argument("--size", default="512x320", help="WIDTHxHEIGHT for --quick")
    parser.add_argument("--frames", type=int, default=33, help="frame count for --quick")
    parser.add_argument("--timeout", type=int, default=7200, help="seconds allowed per workflow")
    args = parser.parse_args()
    width, height = (int(part) for part in args.size.lower().split("x"))

    args.out.mkdir(parents=True, exist_ok=True)
    paths = sorted(args.workflows.glob("*.json"))
    if not paths:
        sys.exit("No workflows found.")

    failed = False
    for path in paths:
        started = time.time()
        try:
            workflow = json.loads(path.read_text())
            if args.quick:
                make_quick(workflow, width, height, args.frames)
            items = render(args.server, workflow, args.timeout)
            if not items:
                raise RuntimeError("nothing was produced")
            for index, item in enumerate(items):
                data = call(args.server, "/view?" + urllib.parse.urlencode(item))
                # A failed decode gives a flat picture, which compresses to almost nothing.
                if len(data) < 20_000:
                    raise RuntimeError(f"{item['filename']} is only {len(data)} bytes, likely blank")
                suffix = pathlib.Path(item["filename"]).suffix
                target = args.out / f"{path.stem}_{index:02d}{suffix}"
                target.write_bytes(data)
            print(f"PASS  {path.stem}: {len(items)} file(s) in {time.time() - started:.0f} s", flush=True)
        except (RuntimeError, urllib.error.URLError, OSError) as error:
            failed = True
            print(f"FAIL  {path.stem}: {error}", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
