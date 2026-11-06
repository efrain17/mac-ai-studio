#!/usr/bin/env python3
"""The Get Models window: find a ComfyUI template by name, see the model files it needs, and
download them with a progress bar. The app shows this page in a window of its own; it uses the
same steps as get-models.sh (get_models.py), so both put the same files in the same places.

Standard library only. Listens on 127.0.0.1; a request that starts or stops a download must
carry the X-Studio header, which other web pages cannot send to it.
"""
import argparse
import json
import pathlib
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
# Installed next to this file; in the repository it lives in tools/.
sys.path[:0] = [str(HERE), str(HERE.parent / "tools")]
import get_models as gm  # noqa: E402

CATALOG_SECONDS = 30


class Studio:
    def __init__(self, templates):
        self.templates = templates
        self.lock = threading.Lock()
        self.catalog_at = 0
        self.items = []
        self.job = {"state": "idle", "files": [], "total": 0, "done_bytes": 0, "message": ""}
        self.process = None
        self.cancelled = False

    def catalog(self):
        if time.time() - self.catalog_at > CATALOG_SECONDS:
            self.items = gm.catalog(self.templates)
            self.catalog_at = time.time()
        return self.items

    @staticmethod
    def key(item):
        return f"{item['kind']}:{item['name']}"

    def item(self, key):
        return next((i for i in self.catalog() if self.key(i) == key), None)

    def search(self, text):
        items = gm.find(self.catalog(), text) if text.strip() else [i for i in self.catalog() if i["models"]]
        return [{"key": self.key(i), "title": i["title"], "name": i["name"], "group": i["group"], "kind": i["kind"],
                 "files": len(i["models"]), "online": i["online"]} for i in items[:40]]

    def plan(self, key):
        item = self.item(key)
        if item is None:
            return None
        rows = gm.plan(item) if item["models"] else []
        return {"key": key, "title": item["title"], "name": item["name"], "online": item["online"],
                "rows": [{k: r[k] for k in ("name", "size", "folder", "state", "why")} for r in rows],
                "total": sum(r["size"] or 0 for r in rows if r["state"] == "to download"),
                "free": gm.free_bytes(), "spare": gm.SPARE_BYTES}

    # ---- The download, in a thread ----------------------------------------------------------

    def start(self, key):
        with self.lock:
            if self.job["state"] in ("checking", "downloading", "verifying"):
                return 409, "A download is already running."
            item = self.item(key)
            if item is None:
                return 404, "No such template or workflow."
            self.cancelled = False
            self.job = {"state": "checking", "title": item["title"], "files": [], "total": 0, "done_bytes": 0,
                        "message": "Asking Hugging Face for the files…"}
        threading.Thread(target=self.run, args=(item,), daemon=True).start()
        return 200, "Started."

    def run(self, item):
        rows = [r for r in gm.plan(item) if r["state"] == "to download"]
        total = sum(r["size"] or 0 for r in rows)
        files = [{"name": r["name"], "size": r["size"], "done": 0, "state": "waiting", "folder": r["folder"],
                  "verified": False} for r in rows]
        self.job.update(files=files, total=total)
        if not rows:
            self.finish("done", "Nothing to download: every file is already there.")
            return
        if total and gm.free_bytes() < total + gm.SPARE_BYTES:
            self.finish("failed", f"Not enough free space: {gm.size_text(total)} plus "
                                  f"{gm.size_text(gm.SPARE_BYTES)} to spare is needed.")
            return
        self.job.update(state="downloading", message="")
        problems = []
        for row, entry in zip(rows, files):
            if self.cancelled:
                break
            entry["state"] = "downloading"
            self.job["current"] = {"part": str(row["target"].with_name(row["target"].name + ".part")), "entry": entry}
            problem = gm.download(row["url"], row["target"], row["size"], row["sha"], started=self.started, quiet=True)
            self.job.pop("current", None)
            if self.cancelled:
                entry["state"] = "stopped"
                break
            if problem:
                entry.update(state="failed", why=problem)
                problems.append(f"{row['name']}: {problem}")
            else:
                entry.update(state="done", done=row["size"] or entry["done"], verified=bool(row["sha"]))
        self.job["done_bytes"] = self.done_bytes()
        if self.cancelled:
            self.finish("cancelled", "Stopped. What was downloaded is kept; Download again resumes where it stopped.")
        elif problems:
            self.finish("failed", "Some files did not download: " + "; ".join(problems))
        else:
            self.finish("done", "All files are in place. In ComfyUI press R (or reopen the Images & Video tab), "
                                "then open the template.")

    def started(self, process):
        self.process = process
        if self.cancelled:
            process.terminate()

    def finish(self, state, message):
        self.job.update(state=state, message=message)
        self.process = None

    def cancel(self):
        self.cancelled = True
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def done_bytes(self):
        total = 0
        current = self.job.get("current")
        for entry in self.job["files"]:
            if current and current["entry"] is entry:
                part = pathlib.Path(current["part"])
                entry["done"] = part.stat().st_size if part.exists() else 0
            total += entry["done"] or 0
        return total

    def snapshot(self):
        if self.job["state"] == "downloading":
            self.job["done_bytes"] = self.done_bytes()
        job = {k: v for k, v in self.job.items() if k != "current"}
        return json.loads(json.dumps(job))


def handler(studio):
    class Page(BaseHTTPRequestHandler):
        def reply(self, body, status=200, kind="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)
            if url.path == "/":
                self.reply(PAGE, kind="text/html; charset=utf-8")
            elif url.path == "/api/search":
                self.reply({"results": studio.search(query.get("q", [""])[0])})
            elif url.path == "/api/plan":
                plan = studio.plan(query.get("key", [""])[0])
                self.reply(plan if plan else {"error": "No such template or workflow."}, 200 if plan else 404)
            elif url.path == "/api/job":
                self.reply(studio.snapshot())
            else:
                self.reply({"error": "not found"}, 404)

        def do_POST(self):
            if self.headers.get("X-Studio") != "1":
                self.reply({"error": "forbidden"}, 403)
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                body = {}
            if self.path == "/api/download":
                status, message = studio.start(str(body.get("key", "")))
                self.reply({"message": message}, status)
            elif self.path == "/api/cancel":
                studio.cancel()
                self.reply({"message": "Stopping."})
            else:
                self.reply({"error": "not found"}, 404)

        def log_message(self, *args):
            pass

    return Page


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Get models</title>
<style>
  :root { color-scheme: light dark; --bg: #f5f5f7; --card: #fff; --text: #1d1d1f; --muted: #6e6e73; --line: #d2d2d7;
          --accent: #0071e3; --good: #1f9d55; --bad: #d70015; --track: #e8e8ed; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #1c1c1e; --card: #2c2c2e; --text: #f5f5f7; --muted: #a1a1a6; --line: #3a3a3c;
            --accent: #2997ff; --good: #32d74b; --bad: #ff453a; --track: #3a3a3c; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 -apple-system, "Helvetica Neue", sans-serif; }
  main { max-width: 760px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  p.lead { margin: 0 0 16px; color: var(--muted); }
  input { width: 100%; font: inherit; font-size: 15px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px;
          background: var(--card); color: var(--text); }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; margin-top: 14px; overflow: hidden; }
  .results button { display: flex; width: 100%; justify-content: space-between; gap: 12px; text-align: left; font: inherit;
                    color: inherit; background: none; border: 0; border-top: 1px solid var(--line); padding: 9px 14px; cursor: pointer; }
  .results button:first-child { border-top: 0; }
  .results button:hover, .results button.on { background: color-mix(in srgb, var(--accent) 12%, transparent); }
  .muted { color: var(--muted); }
  .note { padding: 10px 14px; color: var(--muted); }
  table { width: 100%; border-collapse: collapse; }
  td, th { padding: 8px 14px; border-top: 1px solid var(--line); text-align: left; vertical-align: top; }
  th { border-top: 0; font-weight: 600; color: var(--muted); font-size: 12px; }
  td.size { white-space: nowrap; text-align: right; }
  .state-done, .state-already { color: var(--good); }
  .state-skipped, .state-failed { color: var(--bad); }
  .bar { height: 6px; background: var(--track); border-radius: 3px; overflow: hidden; margin-top: 6px; }
  .bar > div { height: 100%; width: 0; background: var(--accent); transition: width .4s; }
  .bar.big { height: 10px; border-radius: 5px; }
  .actions { display: flex; gap: 10px; align-items: center; padding: 12px 14px; border-top: 1px solid var(--line); flex-wrap: wrap; }
  .actions .grow { flex: 1; color: var(--muted); }
  button.primary, button.secondary { font: inherit; font-weight: 600; border-radius: 8px; padding: 8px 16px; cursor: pointer; border: 0; }
  button.primary { background: var(--accent); color: #fff; }
  button.primary:disabled { opacity: .45; cursor: default; }
  button.secondary { background: var(--track); color: var(--text); }
  .message { padding: 12px 14px; border-top: 1px solid var(--line); }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<main>
  <h1>Get models for a ComfyUI template</h1>
  <p class="lead">Type the title on the template's card in ComfyUI's Templates window, or the short name on its tab once opened.</p>
  <input id="search" placeholder="For example: Z-Image-Turbo" autocomplete="off" autofocus>
  <div class="card results" id="results"></div>

  <div class="card" id="plan" hidden>
    <div class="note" id="plan-title"></div>
    <table><thead><tr><th>File</th><th>Folder</th><th class="size">Size</th><th>Status</th></tr></thead><tbody id="rows"></tbody></table>
    <div class="actions">
      <span class="grow" id="summary"></span>
      <button class="secondary" id="cancel" hidden>Stop</button>
      <button class="primary" id="download" disabled>Download</button>
    </div>
    <div id="progress" hidden style="padding: 0 14px 12px">
      <div class="muted" id="progress-text"></div>
      <div class="bar big"><div id="progress-bar"></div></div>
    </div>
    <div class="message" id="message" hidden></div>
  </div>
</main>
<script>
const $ = id => document.getElementById(id);
const size = n => { if (n == null) return ""; const u = ["B","KB","MB","GB","TB"]; let i = 0;
  while (n >= 1000 && i < 4) { n /= 1000; i++; } return i ? n.toFixed(1) + " " + u[i] : n + " B"; };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let chosen = null, timer = null, polling = null;

async function search() {
  const q = $("search").value;
  const { results } = await (await fetch("/api/search?q=" + encodeURIComponent(q))).json();
  $("results").innerHTML = results.length ? results.map(r =>
    `<button data-key="${esc(r.key)}"><span>${esc(r.title)} <span class="muted">${r.kind === "saved" ? "your workflow" : esc(r.name)}</span></span>` +
    `<span class="muted">${r.online ? "online service" : r.files ? r.files + " file" + (r.files > 1 ? "s" : "") : "no files needed"}</span></button>`).join("")
    : `<div class="note">Nothing matches. Try one word from the title.</div>`;
  for (const b of $("results").querySelectorAll("button")) b.onclick = () => choose(b.dataset.key);
}

async function choose(key) {
  chosen = key;
  for (const b of $("results").querySelectorAll("button")) b.classList.toggle("on", b.dataset.key === key);
  $("plan").hidden = false; $("rows").innerHTML = ""; $("message").hidden = true; $("progress").hidden = true;
  $("plan-title").textContent = "Asking Hugging Face for the files…"; $("download").disabled = true; $("summary").textContent = "";
  const plan = await (await fetch("/api/plan?key=" + encodeURIComponent(key))).json();
  if (chosen !== key) return;
  $("plan-title").innerHTML = `<b>${esc(plan.title)}</b>` + (plan.online ? " uses an online service: it cannot run offline in the studio." : "");
  $("rows").innerHTML = plan.rows.map(rowHtml).join("") || `<tr><td colspan="4" class="muted">It needs no model files.</td></tr>`;
  const todo = plan.rows.filter(r => r.state === "to download").length;
  const enough = plan.free >= plan.total + plan.spare;
  $("summary").textContent = todo ? `${todo} to download, ${size(plan.total)}. Free on disk: ${size(plan.free)}.` +
    (enough ? "" : " Not enough space.") : "Every file is already there.";
  $("download").textContent = todo ? `Download ${size(plan.total)}` : "Download";
  $("download").disabled = !todo || !enough;
}

function rowHtml(r) {
  const label = r.state === "skipped" ? "Skipped: " + r.why : r.state === "already there" ? "Already there" : "To download";
  const css = r.state === "skipped" ? "skipped" : r.state === "already there" ? "already" : "";
  return `<tr><td>${esc(r.name)}</td><td class="muted">${esc(r.folder)}</td><td class="size">${size(r.size)}</td>` +
         `<td class="state-${css}">${esc(label)}</td></tr>`;
}

async function post(path, body) {
  return fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Studio": "1" }, body: JSON.stringify(body || {}) });
}

$("download").onclick = async () => {
  const answer = await post("/api/download", { key: chosen });
  if (!answer.ok) { show((await answer.json()).message, true); return; }
  watch();
};
$("cancel").onclick = () => post("/api/cancel");

function watch() {
  clearInterval(polling);
  polling = setInterval(async () => {
    const job = await (await fetch("/api/job")).json();
    const running = ["checking", "downloading", "verifying"].includes(job.state);
    $("download").disabled = running; $("cancel").hidden = !running; $("search").disabled = running;
    $("progress").hidden = false;
    const pct = job.total ? Math.min(100, 100 * job.done_bytes / job.total) : (job.state === "done" ? 100 : 0);
    $("progress-bar").style.width = pct + "%";
    $("progress-text").textContent = job.state === "checking" ? job.message :
      `${size(job.done_bytes)} of ${size(job.total)} (${pct.toFixed(0)}%)`;
    $("rows").innerHTML = job.files.map(f => `<tr><td>${esc(f.name)}<div class="bar"><div style="width:${f.size ? 100 * f.done / f.size : 0}%"></div></div></td>` +
      `<td class="muted">${esc(f.folder)}</td><td class="size">${size(f.size)}</td><td class="state-${f.state === "done" ? "done" : f.state === "failed" ? "failed" : ""}">` +
      `${esc({waiting: "Waiting", downloading: "Downloading…", done: f.verified ? "Done, checksum OK" : "Done", failed: "Failed: " + (f.why || ""), stopped: "Stopped"}[f.state] || f.state)}</td></tr>`).join("");
    if (!running && job.state !== "idle") {
      clearInterval(polling); $("search").disabled = false;
      // Fresh list: finished files now read "Already there", and Download offers only what is left.
      await choose(chosen); show(job.message, job.state === "failed");
    }
  }, 700);
}

function show(text, bad) {
  $("message").hidden = false; $("message").textContent = text;
  $("message").className = "message " + (bad ? "state-failed" : "state-done");
}

$("search").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 250); });
search();
fetch("/api/job").then(r => r.json()).then(job => { if (["checking", "downloading", "verifying"].includes(job.state)) watch(); });
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--templates", help="ComfyUI's templates folder (found by itself)")
    args = parser.parse_args()
    studio = Studio(gm.templates_dir(args.templates))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(studio))
    print(f"Get models page on http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
