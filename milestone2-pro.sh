#!/bin/bash
# Milestone 2 Pro: the three video flows again, on Wan 2.2. A larger model with natural motion
# and a real negative prompt, 5-second clips at 1280x704 and 24 fps, and the sketch-and-fill
# animation now ends with the finished picture coming alive. Safe to run again. Needs
# milestones 1 and 2.
#
#   ./milestone2-pro.sh            install (about 23 GB of models)
#   ./milestone2-pro.sh --verify   check the installed models against their checksums
#   ./milestone2-pro.sh --test     render preview-size videos and check them for Metal failures
#   ./milestone2-pro.sh --samples  render every Pro workflow at full size, to judge the quality
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

MANIFEST="$REPO_DIR/manifests/milestone2-pro.txt"
WORKFLOWS_DIR="$COMFYUI_DIR/user/default/workflows/Mac AI Studio/Pro"
TEST_OUT="$OUTPUT_DIR/video_pro_test_samples"
SAMPLES_OUT="$OUTPUT_DIR/video_pro_samples"

# The Pro flows reuse milestone 2's picture model, sketch guide, reveal node and example sketches.
require_milestone2() {
  [ -f "$MODELS_DIR/ControlNet/xinsir-scribble-sdxl.safetensors" ] \
    && [ -f "$COMFYUI_DIR/custom_nodes/reveal_mask.py" ] \
    && [ -f "$INPUT_DIR/sketch_and_fill_example.png" ] \
    || die "Milestone 2 is not installed. Run ./milestone2.sh first."
}

# render OUT [run_workflows.py options]: renders every Pro workflow into OUT and checks the videos.
render() {
  local out="$1" url status=0
  shift
  url="$("$RUNTIME_DIR/services.sh" start 10-images)" || die "ComfyUI did not start. See $LOG_DIR/10-images.log"
  rm -rf "$out"
  "$COMFYUI_ENV/bin/python" "$REPO_DIR/tests/run_workflows.py" "$@" \
    --server "${url%/}" --workflows "$REPO_DIR/workflows/video-pro/api" --out "$out" || status=1
  say "Checking the videos"
  "$COMFYUI_ENV/bin/python" "$REPO_DIR/tests/check_videos.py" "$out" || status=1
  "$RUNTIME_DIR/services.sh" stop 10-images
  open "$out"
  return "$status"
}

case "${1:-}" in
  --verify)
    verify_models "$MANIFEST"
    exit $?
    ;;
  --test)
    preflight 5
    require_milestone1
    require_milestone2
    verify_models "$MANIFEST" || die "Models are missing or damaged. Run ./milestone2-pro.sh again."
    # 896x512 keeps Wan's token count a multiple of 64 at any length (see check_wan_size).
    say "Rendering preview-size test videos (896x512, 2 seconds). This takes a while on the first run."
    render "$TEST_OUT" --quick --size 896x512 --frames 49 \
      || die "A video test failed. See 'Video' in docs/TROUBLESHOOTING.md."
    exit 0
    ;;
  --samples)
    preflight 10
    require_milestone1
    require_milestone2
    verify_models "$MANIFEST" || die "Models are missing or damaged. Run ./milestone2-pro.sh again."
    start_run milestone2-pro-samples
    say "Rendering every Pro workflow at full size. This can take hours; the Mac stays awake."
    render "$SAMPLES_OUT" --timeout 14400 \
      || die "A render failed or came out damaged. See 'Video' in docs/TROUBLESHOOTING.md."
    exit 0
    ;;
  "") ;;
  *) die "Unknown option: $1" ;;
esac

preflight 30
require_milestone1
require_milestone2
start_run milestone2-pro

say "Models (about 23 GB; this runs unattended)"
mkdir -p "$MODELS_DIR"/{DiffusionModels,TextEncoders,VAE}
fetch_models "$MANIFEST"
verify_models "$MANIFEST" || die "A model failed its checksum. Run ./milestone2-pro.sh again."

say "Pro video workflows"
mkdir -p "$WORKFLOWS_DIR"
cp "$REPO_DIR"/workflows/video-pro/*.json "$WORKFLOWS_DIR/"

# Picks up the new workflows if the studio is running.
"$RUNTIME_DIR/services.sh" stop 10-images

show_next \
  "Check the Pro pipeline with: ./milestone2-pro.sh --test" \
  "Full-size samples to judge the quality: ./milestone2-pro.sh --samples" \
  "In the app, the workflows are in the Mac AI Studio > Pro folder (press W on the canvas)." \
  "Manual test steps: docs/MANUAL_TESTS.md"
