#!/bin/bash
# Milestone 4: prepares the live training session. Installs nothing. It checks that everything
# from milestones 1 to 3 works, then opens the session guide and a folder of practice prompts.
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

TRAINING_DIR="$STUDIO_HOME/training"
bad=0

check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then echo "PASS  $label"; else echo "FAIL  $label"; bad=1; fi
}

preflight 5
require_milestone1
start_run milestone4

say "Models"
check "Image models (checksums)" verify_models "$REPO_DIR/manifests/milestone1.txt"
check "Video models (checksums)" verify_models "$REPO_DIR/manifests/milestone2.txt"
check "Music models (checksums)" verify_models "$REPO_DIR/manifests/milestone3.txt"

say "Programs"
check "Mac AI Studio app" test -d "/Applications/Mac AI Studio.app"
check "Stability Matrix app" ls -d /Applications/Stability*Matrix*.app
check "Sketch-and-fill node" test -f "$COMFYUI_DIR/custom_nodes/reveal_mask.py"

say "Each tool starts and answers (the first start can take several minutes)"
for service in 10-images 20-music 30-stems-voices; do
  if url="$("$RUNTIME_DIR/services.sh" start "$service" 2>/dev/null)"; then
    echo "PASS  $service at $url"
  else
    echo "FAIL  $service: see $LOG_DIR/$service.log"
    bad=1
  fi
done
"$RUNTIME_DIR/services.sh" stop-all

say "Offline check: nothing in the tools' settings allows a public address"
if grep -qE '0\.0\.0\.0|--share' "$RUNTIME_DIR"/services/*.conf; then
  echo "FAIL  a tool is set to listen beyond this Mac"
  bad=1
else
  echo "PASS  every tool listens on this Mac only"
fi

[ "$bad" = 0 ] || die "Fix the items marked FAIL before the session. See docs/TROUBLESHOOTING.md."

say "Session materials"
mkdir -p "$TRAINING_DIR"
cp "$REPO_DIR/docs/TRAINING_SESSION.md" "$TRAINING_DIR/"
cp "$REPO_DIR/assets/practice_prompts.md" "$TRAINING_DIR/"
open "$TRAINING_DIR"

show_next \
  "Everything passed. The session guide is open in $TRAINING_DIR." \
  "Run Milestone 4 in docs/MANUAL_TESTS.md during the session."
