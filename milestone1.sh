#!/bin/bash
# Milestone 1: Homebrew and its tools, ComfyUI, Stability Matrix, image models, and the desktop app.
# Safe to run again; finished steps are skipped and interrupted downloads resume.
#
#   ./milestone1.sh           install
#   ./milestone1.sh --check   only check this Mac and report conflicts; changes nothing
#   ./milestone1.sh --verify  check the installed models against their checksums
#   ./milestone1.sh --test    render one sample image in each of the three styles
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

MANIFEST="$REPO_DIR/manifests/milestone1.txt"
SM_LIBRARY_DIR="$STUDIO_HOME/StabilityMatrix"
SM_APPDATA_DIR="$HOME/Library/Application Support/StabilityMatrix"

report_conflicts() {
  say "Other software on this Mac (left untouched)"
  local tool found port
  for tool in brew conda python3 git ffmpeg; do
    found="$(/bin/zsh -lc "command -v $tool" 2>/dev/null || true)"
    [ -n "$found" ] && echo "Found $tool: $found"
  done
  [ -x /usr/local/bin/brew ] && warn "An Intel Homebrew exists in /usr/local. It stays as it is and the studio does not use it."
  for port in 8188 18188 17860 17870; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "Port $port is in use. The studio picks the next free port and leaves that program alone."
    fi
  done
  if ls -d /Applications/Stability*Matrix*.app >/dev/null 2>&1; then
    echo "Stability Matrix is already installed; its version and settings are kept."
  fi
}

case "${1:-}" in
  --check)
    preflight 50
    report_conflicts
    echo
    echo "This Mac can run the studio. Nothing was changed."
    exit 0
    ;;
  --verify)
    verify_models "$MANIFEST"
    exit $?
    ;;
  --test)
    preflight 5
    verify_models "$MANIFEST" || die "Models are missing or damaged. Run ./milestone1.sh again."
    url="$("$RUNTIME_DIR/services.sh" start 10-images)" || die "ComfyUI did not start. See $LOG_DIR/10-images.log"
    say "Rendering the three styles through $url"
    status=0
    "$COMFYUI_ENV/bin/python" "$REPO_DIR/tests/run_workflows.py" \
      --server "${url%/}" --workflows "$REPO_DIR/workflows/images/api" \
      --out "$OUTPUT_DIR/style_test_samples" || status=1
    "$RUNTIME_DIR/services.sh" stop 10-images
    open "$OUTPUT_DIR/style_test_samples"
    [ "$status" = 0 ] || die "An image test failed. See 'Images' in docs/TROUBLESHOOTING.md."
    exit 0
    ;;
  "") ;;
  *) die "Unknown option: $1" ;;
esac

preflight 50
start_run milestone1
report_conflicts

say "Homebrew"
if [ ! -x "$BREW_PREFIX/bin/brew" ]; then
  groups | grep -qw admin || die "Homebrew needs an administrator account. Log in as an admin and run this again."
  installer="$STUDIO_HOME/.downloads/homebrew-install.sh"
  download_verified \
    "https://raw.githubusercontent.com/Homebrew/install/$HOMEBREW_INSTALL_COMMIT/install.sh" \
    "$installer" "$HOMEBREW_INSTALL_SHA256"
  echo "Homebrew's installer now explains what it does and asks for the Mac's admin password."
  /bin/bash "$installer"
fi
use_homebrew
brew --version | head -1

say "Apple Command Line Tools"
if ! xcrun --sdk macosx --find swiftc >/dev/null 2>&1; then
  xcode-select --install 2>/dev/null || true
  echo "Click Install in the window that appeared. This script continues when it finishes."
  until xcrun --sdk macosx --find swiftc >/dev/null 2>&1; do sleep 15; done
fi

say "Git and Python 3.12"
# shellcheck disable=SC2086
brew_formulas $BREW_FORMULAS
GIT="$BREW_PREFIX/bin/git"
"$GIT" --version
"$BREW_PYTHON" --version

say "Miniconda"
# The studio runs on Homebrew's Python and does not use conda. A second conda would take over the
# conda command on this Mac, so an existing one, including Miniforge, stays in place.
existing_conda="$(/bin/zsh -lc 'command -v conda' 2>/dev/null || true)"
if brew list --cask miniconda >/dev/null 2>&1; then
  echo "Already installed through Homebrew."
elif [ -n "$existing_conda" ] || brew list --cask miniforge >/dev/null 2>&1; then
  echo "This Mac already has conda ($existing_conda); keeping it."
else
  brew install --cask miniconda || die "Homebrew could not install Miniconda."
fi

say "Python environment for ComfyUI"
make_venv "$COMFYUI_ENV"

say "ComfyUI $COMFYUI_TAG"
if [ ! -d "$COMFYUI_DIR/.git" ]; then
  "$GIT" -c advice.detachedHead=false clone --depth 1 --branch "$COMFYUI_TAG" "$COMFYUI_REPO" "$COMFYUI_DIR"
fi
actual_commit="$("$GIT" -C "$COMFYUI_DIR" rev-parse HEAD)"
[ "$actual_commit" = "$COMFYUI_COMMIT" ] || die "ComfyUI is at $actual_commit, expected $COMFYUI_COMMIT."

say "ComfyUI packages (each one checked against its locked hash)"
"$COMFYUI_ENV/bin/python" -m pip install --require-hashes --only-binary=:all: \
  -r "$REPO_DIR/locks/comfyui-macos-arm64.lock"

say "PyTorch Metal check"
"$COMFYUI_ENV/bin/python" - <<'PY'
import sys
import torch
if not torch.backends.mps.is_available():
    sys.exit("PyTorch cannot use the Metal GPU on this Mac.")
print("PyTorch", torch.__version__, "using", torch.ones(1, device="mps").device)
PY

say "Model folders"
mkdir -p "$MODELS_DIR"/{StableDiffusion,Lora,VAE}
cat > "$COMFYUI_DIR/extra_model_paths.yaml" <<EOF
mac_ai_studio:
  base_path: $MODELS_DIR
  is_default: true
  checkpoints: StableDiffusion
  loras: Lora
  vae: VAE
  controlnet: ControlNet
  diffusion_models: DiffusionModels
  text_encoders: TextEncoders
EOF

say "Style workflows"
workflows_dir="$COMFYUI_DIR/user/default/workflows/Mac AI Studio"
mkdir -p "$workflows_dir"
cp "$REPO_DIR"/workflows/images/*.json "$workflows_dir/"

say "Stability Matrix"
if ls -d /Applications/Stability*Matrix*.app >/dev/null 2>&1; then
  echo "Already installed; keeping the existing copy."
else
  brew install --cask stability-matrix || die "Homebrew could not install Stability Matrix."
fi

# Points Stability Matrix at the same models as ComfyUI, so nothing is stored twice.
# An existing library is the owner's: it is kept, and the shared models stay available by hand.
if [ -f "$SM_APPDATA_DIR/library.json" ]; then
  warn "Stability Matrix already has a library; it is kept. Studio models are in $MODELS_DIR."
else
  mkdir -p "$SM_LIBRARY_DIR" "$SM_APPDATA_DIR"
  ln -sfn "$MODELS_DIR" "$SM_LIBRARY_DIR/Models"
  printf '{\n  "LibraryPath": "%s"\n}\n' "$SM_LIBRARY_DIR" > "$SM_APPDATA_DIR/library.json"
fi

say "Models (about 14.8 GB; this runs unattended)"
fetch_models "$MANIFEST"
verify_models "$MANIFEST" || die "A model failed its checksum. Run ./milestone1.sh again."

say "Desktop app"
install_runtime 10-images.conf
build_app

exclude_from_backups "$MODELS_DIR" "$ENVS_DIR" "$CACHE_DIR" "$STUDIO_HOME/.downloads"

show_next \
  "Open Mac AI Studio from Applications." \
  "Run the sample images with: ./milestone1.sh --test" \
  "Manual test steps: docs/MANUAL_TESTS.md"
