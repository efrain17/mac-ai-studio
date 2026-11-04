#!/bin/bash
# Milestone 4: the chat assistant. LM Studio runs an open model on this Mac, AnythingLLM gives it
# the studio's documentation to answer from and the ComfyUI tools to act with, and librosa adds
# an Analyze tool to the Stems & Voices page. Safe to run again. Needs milestones 1 to 3.
#
#   ./milestone4.sh           install (two apps, a 63 GB model, the documentation)
#   ./milestone4.sh --verify  check the installed model files against their checksums
#   ./milestone4.sh --import  load the documentation into AnythingLLM again
#   ./milestone4.sh --test    check the tools, the model and the apps without a person
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

MANIFEST="$REPO_DIR/manifests/milestone4.txt"
ACE_DIR="$STUDIO_HOME/ace-step"
STEMS_ENV="$ENVS_DIR/stems-voices"
KNOWLEDGE_DIR="$STUDIO_HOME/knowledge"
SOURCES_DIR="$KNOWLEDGE_DIR/sources"
LMSTUDIO_MODELS="$HOME/.lmstudio/models"
MCP_FILES=("$HOME/.lmstudio/mcp.json" "$ANYTHINGLLM_STORAGE/plugins/anythingllm_mcp_servers.json")
# The assistant's scripts need only Python's standard library; ComfyUI's Python is always there.
PY="$COMFYUI_ENV/bin/python"
export STUDIO_HOME

require_milestone3() {
  [ -x "$ACE_DIR/.venv/bin/python" ] && [ -x "$STEMS_ENV/bin/python" ] \
    || die "Milestone 3 is not installed. Run ./milestone3.sh first."
}

require_milestone4() {
  [ -f "$RUNTIME_DIR/services/40-chat.conf" ] && [ -x "$LMS" ] && [ -d "$KNOWLEDGE_DIR" ] \
    || die "Milestone 4 is not installed. Run ./milestone4.sh first."
}

# fetch_docs NAME REPO COMMIT [FOLDER...]: one documentation repository at one commit. Only the
# named folders and the files at its root are downloaded, never its images or history.
fetch_docs() {
  local name="$1" repo="$2" commit="$3" dir="$SOURCES_DIR/$1"
  shift 3
  if [ -d "$dir/.git" ] && [ "$("$GIT" -C "$dir" rev-parse HEAD 2>/dev/null)" = "$commit" ]; then
    echo "Already fetched: $name at ${commit:0:10}"
    return 0
  fi
  rm -rf "$dir"
  mkdir -p "$dir"
  "$GIT" -C "$dir" init -q
  "$GIT" -C "$dir" remote add origin "$repo"
  "$GIT" -C "$dir" sparse-checkout init --cone
  [ $# -eq 0 ] || "$GIT" -C "$dir" sparse-checkout set --cone "$@"
  "$GIT" -C "$dir" fetch -q --depth 1 --filter=blob:none origin "$commit" \
    || die "Could not fetch the $name documentation. Check the connection and run this again."
  "$GIT" -C "$dir" -c advice.detachedHead=false checkout -q FETCH_HEAD
  echo "$name at ${commit:0:10}"
}

import_documents() {
  "$PY" "$REPO_DIR/runtime/assistant.py" import --storage "$ANYTHINGLLM_STORAGE" \
    --knowledge "$KNOWLEDGE_DIR" --port "$ANYTHINGLLM_PORT" \
    --lmstudio-url "http://127.0.0.1:$LMSTUDIO_PORT" --match "$CHAT_MODEL_MATCH"
}

case "${1:-}" in
  --verify)
    verify_models "$MANIFEST"
    exit $?
    ;;
  --import)
    preflight 5
    require_milestone1
    require_milestone4
    say "Starting LM Studio's server and AnythingLLM"
    "$RUNTIME_DIR/services.sh" start 40-chat >/dev/null || die "The Chat tab did not start. See $LOG_DIR/40-chat.log"
    say "Loading the documents (embedding them takes a few minutes)"
    import_documents
    "$RUNTIME_DIR/services.sh" stop 40-chat
    exit 0
    ;;
  --test)
    preflight 5
    require_milestone1
    require_milestone3
    require_milestone4
    verify_models "$MANIFEST" || die "Model files are missing or damaged. Run ./milestone4.sh again."
    status=0
    say "ComfyUI tools (with a stand-in ComfyUI)"
    "$PY" "$REPO_DIR/tests/check_comfy_mcp.py" || status=1
    say "Analyze tool"
    "$STEMS_ENV/bin/python" "$REPO_DIR/tests/check_analyze.py" || status=1
    say "Chat tab (starts LM Studio's server and AnythingLLM)"
    if url="$("$RUNTIME_DIR/services.sh" start 40-chat)"; then
      echo "PASS  AnythingLLM answered at $url"
    else
      die "The Chat tab did not start. See $LOG_DIR/40-chat.log"
    fi
    say "Chat model (the first answer loads 63 GB; up to 15 minutes)"
    "$PY" - "http://127.0.0.1:$LMSTUDIO_PORT" "$CHAT_MODEL_MATCH" <<'PY' || status=1
import json
import sys
import time
import urllib.request

base, match = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(base + "/v1/models", timeout=60) as response:
    models = [m["id"] for m in json.loads(response.read())["data"]]
model = next((m for m in models if match in m), None)
if not model:
    sys.exit(f"FAIL  LM Studio lists no {match} model; it lists {models}")
print(f"PASS  LM Studio lists {model}")
started = time.time()
payload = {"model": model, "messages": [{"role": "user", "content": "Reply with the single word OK."}], "max_tokens": 50}
request = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=900) as response:
    answer = json.loads(response.read())["choices"][0]["message"]["content"].strip()
ok = "ok" in answer.lower()
print(f"{'PASS' if ok else 'FAIL'}  The model answered {answer!r} in {time.time() - started:.0f} s")
sys.exit(0 if ok else 1)
PY
    say "Workspace and documents"
    "$PY" "$REPO_DIR/runtime/assistant.py" check --storage "$ANYTHINGLLM_STORAGE" --port "$ANYTHINGLLM_PORT" || status=1
    say "ComfyUI tools registered in both apps"
    for file in "${MCP_FILES[@]}"; do
      if grep -q mac-ai-studio-comfyui "$file" 2>/dev/null; then echo "PASS  $file"; else echo "FAIL  $file"; status=1; fi
    done
    "$RUNTIME_DIR/services.sh" stop 40-chat
    [ "$status" = 0 ] || die "A check failed. See 'Chat assistant' in docs/TROUBLESHOOTING.md."
    echo
    echo "Asking the assistant a question needs a person: see Milestone 4 in docs/MANUAL_TESTS.md."
    exit 0
    ;;
  "") ;;
  *) die "Unknown option: $1" ;;
esac

preflight 80
require_milestone1
require_milestone3
start_run milestone4
use_homebrew
GIT="$BREW_PREFIX/bin/git"

say "LM Studio and AnythingLLM"
for cask in $BREW_CHAT_CASKS; do
  case "$cask" in
    lm-studio) app="/Applications/LM Studio.app" ;;
    *) app="/Applications/AnythingLLM.app" ;;
  esac
  if brew list --cask "$cask" >/dev/null 2>&1; then
    echo "$cask: already installed through Homebrew."
  elif [ -d "$app" ]; then
    echo "$cask: already installed; keeping the existing copy."
  else
    brew install --cask "$cask" || die "Homebrew could not install $cask."
  fi
done

say "LM Studio's command line tool"
# LM Studio installs lms the first time it opens. The owner clicks through one welcome screen.
if [ ! -x "$LMS" ]; then
  open -a "LM Studio"
  echo "LM Studio opened. Go through its welcome screen and leave it open. This script continues by itself."
  until [ -x "$LMS" ]; do sleep 10; done
fi
echo "lms: $LMS"

say "Chat model and embedding model (about 63 GB; this runs unattended)"
fetch_models "$MANIFEST"
verify_models "$MANIFEST" || die "A model file failed its checksum. Run ./milestone4.sh again."

say "Showing the chat model to LM Studio"
# LM Studio reads ~/.lmstudio/models/<publisher>/<model>; a link keeps the files with the others.
mkdir -p "$LMSTUDIO_MODELS/${CHAT_MODEL_REPO%/*}"
ln -sfn "$MODELS_DIR/lmstudio/$CHAT_MODEL_REPO" "$LMSTUDIO_MODELS/$CHAT_MODEL_REPO"
if "$LMS" ls 2>/dev/null | grep -qi "$CHAT_MODEL_MATCH"; then
  echo "LM Studio lists the model."
else
  warn "LM Studio does not list the model yet. Quit and reopen LM Studio, then run ./milestone4.sh --test."
fi

say "AnythingLLM's embedding model, so the first import needs no internet"
if [ ! -e "$ANYTHINGLLM_STORAGE/models/Xenova/all-MiniLM-L6-v2" ]; then
  mkdir -p "$ANYTHINGLLM_STORAGE/models/Xenova"
  cp -R "$MODELS_DIR/anythingllm/Xenova/all-MiniLM-L6-v2" "$ANYTHINGLLM_STORAGE/models/Xenova/"
fi
echo "Embedding model in place."

say "Analyze tool (librosa) for the Stems & Voices page"
make_venv "$STEMS_ENV"
"$STEMS_ENV/bin/python" -m pip install --require-hashes --only-binary=:all: \
  -r "$REPO_DIR/locks/stems-voices-macos-arm64.lock"
"$STEMS_ENV/bin/python" -c 'import librosa; print("librosa", librosa.__version__)'
cp "$REPO_DIR/runtime/stems_voices.py" "$RUNTIME_DIR/"

say "Documentation for the assistant, each at a fixed version"
mkdir -p "$SOURCES_DIR"
# shellcheck disable=SC2086
fetch_docs comfyui "$KNOWLEDGE_COMFYUI_REPO" "$KNOWLEDGE_COMFYUI_COMMIT" $KNOWLEDGE_COMFYUI_DIRS
# shellcheck disable=SC2086
fetch_docs lmstudio "$KNOWLEDGE_LMSTUDIO_REPO" "$KNOWLEDGE_LMSTUDIO_COMMIT" $KNOWLEDGE_LMSTUDIO_DIRS
# shellcheck disable=SC2086
fetch_docs anythingllm "$KNOWLEDGE_ANYTHINGLLM_REPO" "$KNOWLEDGE_ANYTHINGLLM_COMMIT" $KNOWLEDGE_ANYTHINGLLM_DIRS
# shellcheck disable=SC2086
fetch_docs demucs "$KNOWLEDGE_DEMUCS_REPO" "$KNOWLEDGE_DEMUCS_COMMIT" $KNOWLEDGE_DEMUCS_DIRS
# shellcheck disable=SC2086
fetch_docs stability-matrix "$KNOWLEDGE_STABILITY_MATRIX_REPO" "$KNOWLEDGE_STABILITY_MATRIX_COMMIT" $KNOWLEDGE_STABILITY_MATRIX_DIRS

say "Reading material, as plain Markdown files"
"$PY" "$REPO_DIR/runtime/assistant.py" knowledge --repo-dir "$REPO_DIR" \
  --comfyui-dir "$COMFYUI_DIR" --ace-dir "$ACE_DIR" --models-dir "$MODELS_DIR"

say "ComfyUI tools for the assistant"
mkdir -p "$RUNTIME_DIR/workflows"
rm -rf "$RUNTIME_DIR/workflows"/*
for group in images video video-pro; do
  # The Pro flows are offered only when milestone2-pro.sh installed their models.
  if [ "$group" = "video-pro" ] && [ ! -d "$COMFYUI_DIR/user/default/workflows/Mac AI Studio/Pro" ]; then
    continue
  fi
  mkdir -p "$RUNTIME_DIR/workflows/$group"
  cp "$REPO_DIR/workflows/$group/api/"*.json "$RUNTIME_DIR/workflows/$group/"
done
cp "$REPO_DIR/runtime/comfy_mcp.py" "$REPO_DIR/runtime/assistant.py" "$RUNTIME_DIR/"
"$PY" "$REPO_DIR/runtime/assistant.py" mcp --python "$PY" --script "$RUNTIME_DIR/comfy_mcp.py" \
  --lmstudio-file "${MCP_FILES[0]}" --anythingllm-file "${MCP_FILES[1]}"

say "Adding the Chat tab to the desktop app"
install_runtime 40-chat.conf

say "Loading the documents into AnythingLLM (embedding them takes a few minutes)"
if "$RUNTIME_DIR/services.sh" start 40-chat >/dev/null; then
  import_documents || warn "The import did not finish. Run ./milestone4.sh --import after opening the Chat tab once."
  "$RUNTIME_DIR/services.sh" stop 40-chat
else
  warn "AnythingLLM did not start, so the documents are not loaded yet. See $LOG_DIR/40-chat.log, then run ./milestone4.sh --import."
fi
exclude_from_backups "$SOURCES_DIR"

show_next \
  "Open Mac AI Studio; the Chat (AnythingLLM) tab is now there. On its first open, pick LM Studio as the" \
  "LLM provider in its settings (see Milestone 4 in docs/MANUAL_TESTS.md), then ask it a question." \
  "Check the tools with: ./milestone4.sh --test"
