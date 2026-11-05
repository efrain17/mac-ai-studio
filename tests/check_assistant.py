#!/usr/bin/env python3
"""Checks the assistant setup without AnythingLLM: the MCP settings it writes, and the import
into a stand-in AnythingLLM (its key in a SQLite database, workspace, settings, uploads).

Standard library only. Exits non-zero on failure.
"""
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
failed = False
state = {"workspaces": [], "documents": {}, "updates": [], "models": True, "env": {}, "embedded": [], "refuse": set()}


def check(label, ok, detail):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}", flush=True)
    failed = failed or not ok


class FakeAnythingLLM(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return self.headers.get("Authorization", "").startswith("Bearer studio-")

    def do_GET(self):
        if self.path == "/v1/models":  # the stand-in LM Studio
            self.reply({"data": [{"id": "mlx-community/gpt-oss-120b-mxfp4-q8"}, {"id": "text-embedding-x"}]})
            return
        if self.path == "/api/setup-complete":  # the app's own settings, open without a password
            self.reply({"results": {"LLMProvider": state["env"].get("LLMProvider"),
                                    "LMStudioBasePath": state["env"].get("LMStudioBasePath")}})
        elif not self.authorized():
            self.reply({"error": "no"}, 403)
        elif self.path == "/api/v1/auth":
            self.reply({"authenticated": True})
        elif self.path == "/api/v1/workspaces":
            self.reply({"workspaces": state["workspaces"]})
        elif self.path == "/api/v1/documents":
            items = [{"name": f"{title}-x.json", "title": title} for title in state["documents"]]
            self.reply({"localFiles": {"items": [{"name": "mac-ai-studio", "items": items}]}})
        elif self.path.startswith("/api/v1/workspace/"):
            docs = [{"docpath": f"mac-ai-studio/{t}-x.json"} for t, w in state["documents"].items() if w]
            self.reply({"workspace": [{**state["workspaces"][0], "documents": docs}]})
        else:
            self.reply({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        if self.path == "/api/system/update-env":  # what AnythingLLM's settings page saves
            state["env"].update(json.loads(raw))
            self.reply({"newValues": json.loads(raw), "error": False})
            return
        if not self.authorized():
            self.reply({"error": "no"}, 403)
            return
        if self.path == "/api/v1/workspace/new":
            body = json.loads(raw)
            workspace = {"name": body["name"], "slug": "studio-help", "openAiPrompt": body.get("openAiPrompt"),
                         "chatMode": body.get("chatMode"), "similarityThreshold": body.get("similarityThreshold"),
                         "queryRefusalResponse": body.get("queryRefusalResponse")}
            state["workspaces"].append(workspace)
            self.reply({"workspace": workspace})
        elif self.path == "/api/v1/workspace/studio-help/update-embeddings":
            adds = json.loads(raw).get("adds", [])
            state["embedded"].append(adds)
            for docpath in adds:
                title = docpath.split("/", 1)[1].rsplit("-x.json", 1)[0]
                if title in state["documents"] and title not in state["refuse"]:
                    state["documents"][title] = "studio-help"
            self.reply({"workspace": state["workspaces"][0]})
        elif self.path == "/api/v1/workspace/studio-help/update":
            body = json.loads(raw)
            state["updates"].append(body)
            state["workspaces"][0].update(body)
            self.reply({"workspace": state["workspaces"][0]})
        elif self.path == "/api/v1/workspace/studio-help/vector-search":
            query = json.loads(raw).get("query", "")
            results = [{"text": f"About {query}", "metadata": {"title": title}, "score": 0.31}
                       for title, w in state["documents"].items() if w][:4]
            self.reply({"results": results} if results else {"results": [], "message": "No embeddings found for this workspace."})
        elif self.path == "/api/v1/document/upload/mac-ai-studio":
            text = raw.decode("utf-8", "replace")
            name = text.split('filename="', 1)[1].split('"', 1)[0]
            # Like the desktop app on the client's Mac: an upload reaches the library, not the workspace.
            state["documents"][name] = ""
            self.reply({"success": True, "documents": [{"location": f"mac-ai-studio/{name}-x.json"}]})
        else:
            self.reply({"error": "not found"}, 404)

    def do_DELETE(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        for name in body.get("names", []):
            state["documents"].pop(name.split("/", 1)[1].rsplit("-x.json", 1)[0], None)
        self.reply({"success": True})


def run(*arguments, env):
    return subprocess.run([sys.executable, str(REPO_DIR / "runtime" / "assistant.py"), *arguments],
                          capture_output=True, text=True, env=env)


def main():
    server = HTTPServer(("127.0.0.1", 0), FakeAnythingLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    with tempfile.TemporaryDirectory() as temporary:
        studio = pathlib.Path(temporary)
        env = {**os.environ, "STUDIO_HOME": str(studio)}
        storage = studio / "storage"
        (storage / "plugins").mkdir(parents=True)
        lmstudio_file = studio / "lmstudio" / "mcp.json"
        lmstudio_file.parent.mkdir()
        lmstudio_file.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        anything_file = storage / "plugins" / "anythingllm_mcp_servers.json"

        result = run("mcp", "--python", "/usr/bin/python3", "--script", "/studio/comfy_mcp.py",
                     "--lmstudio-file", str(lmstudio_file), "--anythingllm-file", str(anything_file), env=env)
        check("MCP command ran", result.returncode == 0, (result.stderr or result.stdout).strip()[-200:])
        written = json.loads(lmstudio_file.read_text())
        entry = written["mcpServers"].get("mac-ai-studio-comfyui", {})
        check("LM Studio keeps other servers", "other" in written["mcpServers"], ", ".join(written["mcpServers"]))
        check("LM Studio entry", entry.get("command") == "/usr/bin/python3" and entry.get("args") == ["/studio/comfy_mcp.py"]
              and entry.get("env", {}).get("STUDIO_HOME") == str(studio), json.dumps(entry))
        anything = json.loads(anything_file.read_text())["mcpServers"]["mac-ai-studio-comfyui"]
        check("AnythingLLM entry starts by itself", anything.get("anythingllm", {}).get("autoStart") is True, json.dumps(anything)[:100])

        knowledge = studio / "knowledge"
        knowledge.mkdir()
        for name in ("Mac AI Studio - overview.md", "ComfyUI - interface.md"):
            (knowledge / name).write_text(f"# {name}\n\nSome text.\n")
        database = storage / "anythingllm.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE api_keys (id INTEGER PRIMARY KEY, name TEXT, secret TEXT UNIQUE, createdBy INTEGER, "
                           "createdAt DATETIME DEFAULT CURRENT_TIMESTAMP, lastUpdatedAt DATETIME DEFAULT CURRENT_TIMESTAMP)")
        connection.commit()
        connection.close()
        state["documents"]["Old file.md"] = "studio-help"
        # Uploaded by an earlier import but never added to the workspace: the client's case.
        state["documents"]["ComfyUI - interface.md"] = ""

        importer = ("import", "--storage", str(storage), "--knowledge", str(knowledge), "--port", str(port),
                    "--lmstudio-url", f"http://127.0.0.1:{port}", "--match", "gpt-oss-120b")
        result = run(*importer, env=env)
        check("Import ran", result.returncode == 0, (result.stderr or result.stdout).strip()[-200:])
        keys = sqlite3.connect(database).execute("SELECT name, secret FROM api_keys").fetchall()
        check("One key in the database", len(keys) == 1 and keys[0][0] == "Mac AI Studio installer", str([k[0] for k in keys]))
        check("Workspace created", [w["name"] for w in state["workspaces"]] == ["Studio Help"], str(state["workspaces"])[:80])
        workspace = state["workspaces"][0]
        check("Answers only from the documents", workspace.get("chatMode") == "query", str(workspace.get("chatMode")))
        check("Every question reaches the documents", workspace.get("similarityThreshold") == 0,
              f"similarity threshold {workspace.get('similarityThreshold')}")
        check("Refusal explains an empty workspace", "--import" in (workspace.get("queryRefusalResponse") or ""),
              (workspace.get("queryRefusalResponse") or "")[:70])
        check("Asks for sources", "Sources:" in (workspace.get("openAiPrompt") or ""), "the instructions ask for a Sources line")
        check("LM Studio set as the provider", state["env"].get("LLMProvider") == "lmstudio"
              and state["env"].get("LMStudioBasePath") == f"http://127.0.0.1:{port}/v1"
              and state["env"].get("LMStudioModelPref") == "mlx-community/gpt-oss-120b-mxfp4-q8", json.dumps(state["env"]))
        check("Model chosen", any(u.get("chatModel") == "mlx-community/gpt-oss-120b-mxfp4-q8" and u.get("agentProvider") == "lmstudio"
                                  for u in state["updates"]), json.dumps(state["updates"])[:120])
        check("Files uploaded into the workspace", state["documents"] == {"Mac AI Studio - overview.md": "studio-help",
                                                                          "ComfyUI - interface.md": "studio-help"},
              json.dumps(state["documents"]))
        check("Old file removed", "Old file.md" not in state["documents"], "removed")

        result = run(*importer, env=env)
        check("Files added to the workspace in one step", state["embedded"][:1] == [[
              "mac-ai-studio/ComfyUI - interface.md-x.json", "mac-ai-studio/Mac AI Studio - overview.md-x.json"]],
              json.dumps(state["embedded"])[:140])
        check("Import reports the workspace", "2 of 2 documents in the workspace" in result.stdout,
              next((line for line in result.stdout.splitlines() if "documents in the workspace" in line), "no line"))
        state["embedded"].clear()
        result = run(*importer, env=env)
        check("Second import skips existing files", result.returncode == 0 and result.stdout.count("Already there") == 2
              and state["embedded"] == [], result.stdout.strip().splitlines()[-1])
        keys = sqlite3.connect(database).execute("SELECT count(*) FROM api_keys").fetchone()[0]
        check("Key reused", keys == 1, f"{keys} key(s)")
        state["documents"]["ComfyUI - interface.md"] = ""
        state["refuse"].add("ComfyUI - interface.md")
        result = run(*importer, env=env)
        check("A file that will not embed is named", result.returncode != 0 and "ComfyUI - interface.md" in result.stdout
              and "not in the workspace" in result.stdout,
              next((line for line in result.stdout.splitlines() if "not in the workspace" in line), result.stdout.strip()[-100:]))
        state["refuse"].clear()
        result = run(*importer, env=env)
        check("The next import adds it", result.returncode == 0 and state["documents"]["ComfyUI - interface.md"] == "studio-help",
              result.stdout.strip().splitlines()[-1])

        built = studio / "built"
        result = run("knowledge", "--repo-dir", str(REPO_DIR), "--comfyui-dir", str(studio / "none"),
                     "--ace-dir", str(studio / "none"), "--models-dir", str(studio / "none"),
                     "--python", f"Test environment={sys.executable}", env={**env, "STUDIO_HOME": str(built)})
        check("Knowledge built", result.returncode == 0, (result.stderr or result.stdout).strip()[-120:])
        packages = built / "knowledge" / "Python packages - Test environment.md"
        text = packages.read_text() if packages.exists() else ""
        check("Python packages listed", "| Package | Version |" in text and text.count("\n| ") > 2,
              f"{text.count(chr(10) + '| ') - 2} packages")
        check("Studio's own node documented", (built / "knowledge" / "Mac AI Studio - CUSTOM_NODE.md").exists(),
              "Mac AI Studio - CUSTOM_NODE.md")

        result = run("diagnose", "--storage", str(storage), "--knowledge", str(knowledge), "--port", str(port),
                     "--lmstudio-url", f"http://127.0.0.1:{port}", env=env)
        report = (studio / "logs" / "chat-report.txt").read_text() if (studio / "logs" / "chat-report.txt").exists() else ""
        check("Diagnose report", result.returncode == 0 and "LLMProvider: lmstudio" in report and "chatMode: query" in report
              and "In the workspace: 2" in report and "2 passages" in report, f"{len(report.splitlines())} lines")
        check("Report hides the key", "studio-" not in report.replace("studio-…", "").replace("studio-help", ""),
              "no API key in the report")
        check("Import logged", "documents in the workspace" in (studio / "logs" / "assistant.log").read_text(),
              "logs/assistant.log")

        result = run("check", "--storage", str(storage), "--port", str(port), env=env)
        check("Check reports the workspace", result.returncode == 0 and "2 documents" in result.stdout, result.stdout.strip()[-60:])
        check("Check finds passages for a question", "PASS  A question finds" in result.stdout,
              next((line for line in result.stdout.splitlines() if "question" in line), "no line"))
        check("Check reports the provider", "PASS  AnythingLLM uses LM Studio" in result.stdout, result.stdout.strip().splitlines()[0])
        state["env"].clear()
        result = run("check", "--storage", str(storage), "--port", str(port), env=env)
        check("Check catches a missing provider", result.returncode != 0 and "FAIL  AnythingLLM's LLM provider" in result.stdout,
              next((line for line in result.stdout.splitlines() if "provider" in line), result.stdout.strip()[-80:]))
    server.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
