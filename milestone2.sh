#!/bin/bash
# Milestone 2: video pipelines in ComfyUI. Text to video, sketch folder to video, and the
# sketch-and-fill animation. Safe to run again. Needs milestone 1.
#
#   ./milestone2.sh             install (about 21 GB of models)
#   ./milestone2.sh --with-wan  also install the fallback video model (about 23 GB more; the
#                               same files as ./milestone2-pro.sh, which gives the full Pro flows)
#   ./milestone2.sh --verify    check the installed models against their checksums
#   ./milestone2.sh --test      render short videos and check them for Metal failures
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

MANIFEST="$REPO_DIR/manifests/milestone2.txt"
WAN_MANIFEST="$REPO_DIR/manifests/milestone2-pro.txt"
WORKFLOWS_DIR="$COMFYUI_DIR/user/default/workflows/Mac AI Studio"
TEST_OUT="$OUTPUT_DIR/video_test_samples"

with_wan=0
case "${1:-}" in
  --verify)
    bad=0
    verify_models "$MANIFEST" || bad=1
    if [ -f "$WORKFLOWS_DIR/D_wan_fallback.json" ]; then verify_models "$WAN_MANIFEST" || bad=1; fi
    exit "$bad"
    ;;
  --test)
    preflight 5
    require_milestone1
    verify_models "$MANIFEST" || die "Models are missing or damaged. Run ./milestone2.sh again."
    url="$("$RUNTIME_DIR/services.sh" start 10-images)" || die "ComfyUI did not start. See $LOG_DIR/10-images.log"
    say "Rendering short test videos through $url. This takes a while on the first run."
    rm -rf "$TEST_OUT"
    status=0
    "$COMFYUI_ENV/bin/python" "$REPO_DIR/tests/run_workflows.py" --quick \
      --server "${url%/}" --workflows "$REPO_DIR/workflows/video/api" --out "$TEST_OUT" || status=1
    say "Checking the videos"
    "$COMFYUI_ENV/bin/python" "$REPO_DIR/tests/check_videos.py" "$TEST_OUT" || status=1
    "$RUNTIME_DIR/services.sh" stop 10-images
    open "$TEST_OUT"
    [ "$status" = 0 ] || die "A video test failed. See 'Video' in docs/TROUBLESHOOTING.md."
    exit 0
    ;;
  --with-wan) with_wan=1 ;;
  "") ;;
  *) die "Unknown option: $1" ;;
esac

preflight 40
require_milestone1
start_run milestone2

say "Models (about 21 GB; this runs unattended)"
mkdir -p "$MODELS_DIR"/{StableDiffusion,TextEncoders,ControlNet,DiffusionModels,VAE}
fetch_models "$MANIFEST"
verify_models "$MANIFEST" || die "A model failed its checksum. Run ./milestone2.sh again."

if [ "$with_wan" = 1 ]; then
  say "Fallback video model (about 23 GB)"
  fetch_models "$WAN_MANIFEST"
  verify_models "$WAN_MANIFEST" || die "A model failed its checksum. Run ./milestone2.sh --with-wan again."
fi

say "Sketch-and-fill node"
cp "$REPO_DIR/custom_nodes/reveal_mask.py" "$COMFYUI_DIR/custom_nodes/reveal_mask.py"

say "Example sketches"
mkdir -p "$INPUT_DIR/sketches"
for sketch in "$REPO_DIR"/assets/sketches/*.png; do
  # Never overwrite a file with the same name: this folder is also where the owner's sketches go.
  cp -n "$sketch" "$INPUT_DIR/sketches/" || true
done
cp -n "$REPO_DIR/assets/sketches/house.png" "$INPUT_DIR/sketch_and_fill_example.png" || true

say "Video workflows"
mkdir -p "$WORKFLOWS_DIR"
cp "$REPO_DIR"/workflows/video/*.json "$WORKFLOWS_DIR/"
[ "$with_wan" = 0 ] || cp "$REPO_DIR"/workflows/video-wan/*.json "$WORKFLOWS_DIR/"

# Picks up the new node and workflows if the studio is running.
"$RUNTIME_DIR/services.sh" stop 10-images

show_next \
  "Check the video pipeline with: ./milestone2.sh --test" \
  "Sharper, longer clips with natural motion: ./milestone2-pro.sh" \
  "Manual test steps: docs/MANUAL_TESTS.md"
