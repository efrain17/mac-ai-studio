#!/bin/bash
# Updates every studio tool that comes from Homebrew, then checks that the studio still works.
# ComfyUI, ACE-Step, Demucs, PyTorch and the models are not in Homebrew and stay as installed.
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

preflight 10
[ -x "$BREW_PREFIX/bin/brew" ] || die "Homebrew is not installed. Run ./milestone1.sh first."
start_run update

export HOMEBREW_NO_ANALYTICS=1
export HOMEBREW_NO_ENV_HINTS=1
eval "$("$BREW_PREFIX/bin/brew" shellenv)"

if [ -x "$RUNTIME_DIR/services.sh" ]; then
  say "Stopping the studio"
  "$RUNTIME_DIR/services.sh" stop-all
fi

say "Checking for new versions"
brew update

say "Updating tools"
# Named one by one, so unrelated programs from Homebrew are not part of this update.
# shellcheck disable=SC2086
for name in $BREW_FORMULAS $BREW_MUSIC_FORMULAS; do
  if brew list --formula "$name" >/dev/null 2>&1; then
    brew upgrade --formula "$name" || warn "$name was not updated."
  fi
done
# These two are marked as updating themselves, which plain upgrades skip without this option.
# shellcheck disable=SC2086
for name in $BREW_CASKS; do
  if brew list --cask "$name" >/dev/null 2>&1; then
    brew upgrade --cask --greedy-auto-updates "$name" || warn "$name was not updated."
  fi
done

say "Checking the studio"
bad=0

check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then echo "PASS  $label"; else echo "FAIL  $label"; bad=1; fi
}

if [ -x "$COMFYUI_ENV/bin/python" ]; then
  check "Images and video: Python and PyTorch" "$COMFYUI_ENV/bin/python" -c 'import torch; torch.ones(1, device="mps")'
fi
if [ -x "$STUDIO_HOME/ace-step/.venv/bin/python" ]; then
  check "Music: Python, PyTorch and MLX" "$STUDIO_HOME/ace-step/.venv/bin/python" -c 'import torch, mlx.core'
  check "Music: FFmpeg" env DYLD_FALLBACK_LIBRARY_PATH="$BREW_FFMPEG/lib" \
    "$STUDIO_HOME/ace-step/.venv/bin/python" -c 'import torchcodec.decoders'
fi
if [ -x "$ENVS_DIR/stems-voices/bin/python" ]; then
  check "Stems: Python and Demucs" "$ENVS_DIR/stems-voices/bin/python" -c 'import demucs, gradio'
fi

if [ "$bad" != 0 ]; then
  die "An update affected the studio. Run the milestone scripts again to rebuild it, then see 'After an update' in docs/TROUBLESHOOTING.md."
fi

show_next "All tools are up to date and the studio passed its checks."
