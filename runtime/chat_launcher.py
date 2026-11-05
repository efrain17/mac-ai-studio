#!/usr/bin/env python3
"""The Chat tab's page: AnythingLLM's status and a button that brings its window forward.

AnythingLLM's desktop app has no web page; its port 3001 answers the API only, and a browser gets
a 404 there (docs.anythingllm.com, Desktop overview). So the chat itself happens in AnythingLLM's
own window, and this page, inside Mac AI Studio, says whether AnythingLLM and LM Studio's server
are running and opens AnythingLLM on a click.

Standard library only. Listens on 127.0.0.1.
"""
import argparse
import json
import os
import shlex
import subprocess
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPEN_COMMAND = shlex.split(os.environ.get("CHAT_OPEN_COMMAND", "open -a AnythingLLM"))
MODEL_MATCH = os.environ.get("CHAT_MODEL_MATCH", "gpt-oss-120b")

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chat (AnythingLLM)</title>
<style>
  :root { color-scheme: light dark; --bg: #f5f5f7; --card: #fff; --text: #1d1d1f; --muted: #6e6e73;
          --line: #d2d2d7; --accent: #0071e3; --good: #1f9d55; --wait: #b26a00; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #1c1c1e; --card: #2c2c2e; --text: #f5f5f7; --muted: #a1a1a6; --line: #3a3a3c;
            --accent: #2997ff; --good: #32d74b; --wait: #ffb340; }
  }
  body { margin: 0; background: var(--bg); color: var(--text);
         font: 15px/1.5 -apple-system, "Helvetica Neue", sans-serif; }
  main { max-width: 620px; margin: 8vh auto; padding: 0 24px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 28px 32px; }
  h1 { font-size: 22px; margin: 0 0 6px; }
  p { margin: 0 0 14px; color: var(--muted); }
  button { font: inherit; font-weight: 600; color: #fff; background: var(--accent); border: 0;
           border-radius: 8px; padding: 10px 20px; cursor: pointer; }
  ul.status { list-style: none; padding: 0; margin: 20px 0; }
  ul.status li { padding: 8px 0; border-top: 1px solid var(--line); display: flex; gap: 10px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 7px; background: var(--wait); flex: none; }
  .dot.on { background: var(--good); }
  h2 { font-size: 15px; margin: 24px 0 8px; }
  ol { margin: 0; padding-left: 20px; color: var(--muted); }
  code { font: 13px "SF Mono", Menlo, monospace; }
</style>
</head>
<body>
<main data-id="chat-launcher">
  <div class="card">
    <h1>Chat with the studio assistant</h1>
    <p>The chat opens in AnythingLLM's own window, next to this one. Use the <b>Studio Help</b> workspace:
       it has read every guide of the studio.</p>
    <button id="open" data-id="chat-open-button">Open AnythingLLM</button>
    <ul class="status" data-id="chat-status">
      <li><span class="dot" id="anythingllm-dot"></span><span id="anythingllm">AnythingLLM: checking…</span></li>
      <li><span class="dot" id="lmstudio-dot"></span><span id="lmstudio">LM Studio's server: checking…</span></li>
    </ul>
    <h2>Tips</h2>
    <ol>
      <li>The first answer takes a few minutes while the 63 GB model loads. Later answers start within seconds.</li>
      <li>Start a message with <code>@agent</code> to have it render an image or video in ComfyUI.</li>
      <li>Each answer ends with the documents it used.</li>
      <li>Quitting Mac AI Studio also quits AnythingLLM and unloads the model.</li>
    </ol>
  </div>
</main>
<script>
  function show(name, on, text) {
    document.getElementById(name).textContent = text;
    document.getElementById(name + "-dot").className = on ? "dot on" : "dot";
  }
  async function refresh() {
    try {
      const status = await (await fetch("/status")).json();
      show("anythingllm", status.anythingllm,
           status.anythingllm ? "AnythingLLM: running" : "AnythingLLM: starting…");
      show("lmstudio", status.lmstudio,
           status.model ? "LM Studio's server: running, with " + status.model
                        : status.lmstudio ? "LM Studio's server: running, but the chat model is not listed"
                                          : "LM Studio's server: not running yet");
    } catch (error) { /* The page is restarting; the next check updates it. */ }
  }
  document.getElementById("open").addEventListener("click", () => fetch("/open", { method: "POST" }));
  refresh();
  setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.loads(response.read())
    except (OSError, ValueError):
        return None


def status(anythingllm_port, lmstudio_port):
    models = get_json(f"http://127.0.0.1:{lmstudio_port}/v1/models")
    names = [m.get("id", "") for m in (models or {}).get("data", [])]
    return {
        "anythingllm": get_json(f"http://127.0.0.1:{anythingllm_port}/api/ping") is not None,
        "lmstudio": models is not None,
        "model": next((name for name in names if MODEL_MATCH in name), None),
    }


def handler(anythingllm_port, lmstudio_port):
    class Page(BaseHTTPRequestHandler):
        def reply(self, body, kind="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self.reply(PAGE, "text/html; charset=utf-8")
            elif self.path == "/status":
                self.reply(status(anythingllm_port, lmstudio_port))
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/open":
                self.send_error(404)
                return
            result = subprocess.run(OPEN_COMMAND, capture_output=True, text=True)
            self.reply({"ok": result.returncode == 0})

        def log_message(self, *args):
            pass

    return Page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--anythingllm-port", type=int, default=3001)
    parser.add_argument("--lmstudio-port", type=int, default=1234)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(args.anythingllm_port, args.lmstudio_port))
    print(f"Chat page on http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
