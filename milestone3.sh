#!/bin/bash
# Milestone 3: music studio (ACE-Step), LoRA training page, stem splitter (Demucs) and voice
# profiles. Each tool has a private environment. Safe to run again. Needs milestone 1.
#
#   ./milestone3.sh           install (about 39 GB of models, about 10 GB of tools)
#   ./milestone3.sh --verify  check the installed models against their checksums
#   ./milestone3.sh --test    start both tools and split a generated test tone offline
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

MANIFEST="$REPO_DIR/manifests/milestone3.txt"
ACE_DIR="$STUDIO_HOME/ace-step"
STEMS_ENV="$ENVS_DIR/stems-voices"

# Demucs looks for its weights through the Hugging Face cache and, if that fails, silently
# downloads older ones from another host. This stops that from ever going unnoticed.
demucs_offline_test() {
  local work tone
  work="$(mktemp -d "$TMPDIR/demucs.XXXXXX")"
  tone="$work/tone.wav"
  "$BREW_FFMPEG/bin/ffmpeg" -hide_banner -loglevel error -f lavfi \
    -i "sine=frequency=220:duration=8" -ac 2 -ar 44100 "$tone"
  HF_HUB_OFFLINE=1 PATH="$BREW_FFMPEG/bin:$PATH" "$STEMS_ENV/bin/python" -m demucs \
    -n "$DEMUCS_MODEL" -d mps --float32 --clip-mode none -o "$work/out" "$tone" \
    || die "Demucs could not split the test tone."
  [ -f "$work/out/$DEMUCS_MODEL/tone/vocals.wav" ] || die "Demucs produced no stems."
  if [ -n "$(ls -A "$TORCH_HOME/hub/checkpoints" 2>/dev/null)" ]; then
    die "Demucs used weights from outside the verified cache. See $TORCH_HOME/hub/checkpoints."
  fi
  rm -rf "$work"
  echo "Demucs split a test tone offline with the verified weights."
}

case "${1:-}" in
  --verify)
    verify_models "$MANIFEST"
    exit $?
    ;;
  --test)
    preflight 5
    require_milestone1
    verify_models "$MANIFEST" || die "Models are missing or damaged. Run ./milestone3.sh again."
    mkdir -p "$TMPDIR"
    say "Stem splitter"
    demucs_offline_test
    say "Pages"
    for service in 30-stems-voices 20-music; do
      url="$("$RUNTIME_DIR/services.sh" start "$service")" || die "$service did not start. See $LOG_DIR/$service.log"
      echo "PASS  $service answered at $url"
      "$RUNTIME_DIR/services.sh" stop "$service"
    done
    echo
    echo "Generating a song needs a person listening: see Milestone 3 in docs/MANUAL_TESTS.md."
    exit 0
    ;;
  "") ;;
  *) die "Unknown option: $1" ;;
esac

preflight 80
require_milestone1
start_run milestone3
use_homebrew
GIT="$BREW_PREFIX/bin/git"

say "uv and FFmpeg 8"
# shellcheck disable=SC2086
brew_formulas $BREW_MUSIC_FORMULAS

say "ACE-Step at ${ACE_STEP_COMMIT:0:10}"
if [ ! -d "$ACE_DIR/.git" ]; then
  mkdir -p "$ACE_DIR"
  "$GIT" -C "$ACE_DIR" init -q
  "$GIT" -C "$ACE_DIR" remote add origin "$ACE_STEP_REPO"
  "$GIT" -C "$ACE_DIR" fetch -q --depth 1 origin "$ACE_STEP_COMMIT"
  "$GIT" -C "$ACE_DIR" -c advice.detachedHead=false checkout -q FETCH_HEAD
fi
actual_commit="$("$GIT" -C "$ACE_DIR" rev-parse HEAD)"
[ "$actual_commit" = "$ACE_STEP_COMMIT" ] || die "ACE-Step is at $actual_commit, expected $ACE_STEP_COMMIT."

say "ACE-Step packages (from its own lock file; every hash is checked)"
(
  cd "$ACE_DIR"
  UV_PYTHON="$BREW_PYTHON" UV_PROJECT_ENVIRONMENT="$ACE_DIR/.venv" \
    "$BREW_PREFIX/bin/uv" sync --frozen
)

# Without this file ACE-Step falls back to its example settings, which select the wrong backend.
cat > "$ACE_DIR/.env" <<'EOF'
ACESTEP_LM_BACKEND=mlx
SERVER_NAME=127.0.0.1
EOF

say "ACE-Step checks: MLX, Metal and audio decoding"
"$ACE_DIR/.venv/bin/python" - <<'PY'
import sys
import mlx.core as mx
import torch
print("MLX device:", mx.default_device())
if not torch.backends.mps.is_available():
    sys.exit("PyTorch cannot use the Metal GPU on this Mac.")
print("PyTorch", torch.__version__, "with Metal")
PY
check_wav="$TMPDIR/ace-check.wav"
"$BREW_FFMPEG/bin/ffmpeg" -y -hide_banner -loglevel error -f lavfi -i "sine=frequency=220:duration=1" "$check_wav"
DYLD_FALLBACK_LIBRARY_PATH="$BREW_FFMPEG/lib" "$ACE_DIR/.venv/bin/python" - "$check_wav" <<'PY' \
  || die "ACE-Step cannot decode audio through FFmpeg. See 'Music' in docs/TROUBLESHOOTING.md."
import sys
from torchcodec.decoders import AudioDecoder
print("Decoded", AudioDecoder(sys.argv[1]).get_all_samples().data.shape[-1], "audio samples")
PY
rm -f "$check_wav"

say "Music models (about 38 GB; this runs unattended)"
fetch_models "$MANIFEST"
verify_models "$MANIFEST" || die "A model failed its checksum. Run ./milestone3.sh again."

say "Model settings files, at the same pinned commits"
"$ACE_DIR/.venv/bin/python" - "$MODELS_DIR/ace-step" <<'PY'
import sys
from huggingface_hub import snapshot_download
root = sys.argv[1]
for repo, commit, folder in (
    ("ACE-Step/Ace-Step1.5", "19671f406d603126926c1b7e2adc169acbcade22", root),
    ("ACE-Step/acestep-v15-xl-turbo", "d4a0b288b83ebb7e25a8c0b32c573c22e134e8ee", root + "/acestep-v15-xl-turbo"),
    ("ACE-Step/acestep-5Hz-lm-4B", "0a3ec94b557aea7d508da38b31cfe7341f6ff737", root + "/acestep-5Hz-lm-4B"),
):
    snapshot_download(repo, revision=commit, local_dir=folder, ignore_patterns=["*.safetensors", "*.pt"])
PY

# Music is saved with the rest of the owner's work, not inside the program's folder.
mkdir -p "$OUTPUT_DIR/music"
if [ ! -L "$ACE_DIR/gradio_outputs" ]; then
  rm -rf "$ACE_DIR/gradio_outputs"
  ln -s "$OUTPUT_DIR/music" "$ACE_DIR/gradio_outputs"
fi

say "Stem splitter and voice page"
make_venv "$STEMS_ENV"
"$STEMS_ENV/bin/python" -m pip install --require-hashes --only-binary=:all: \
  -r "$REPO_DIR/locks/stems-voices-macos-arm64.lock"

say "Demucs weights ($DEMUCS_MODEL)"
"$STEMS_ENV/bin/python" - "$DEMUCS_MODEL_REPO" "$DEMUCS_MODEL_COMMIT" "$HF_HOME" <<'PY'
import hashlib
import pathlib
import sys
from huggingface_hub import snapshot_download

repo, commit, hf_home = sys.argv[1:]
expected = {
    "f7e0c4bc.safetensors": "2c85ab3c62dd6edd8e0b965e38b16fd1cdde357cc25de6b6bc9ce7c83f60925f",
    "d12395a8.safetensors": "5b01a97567ae9a3178a6236fb520251045c03eb8834bc8c24a4eec11d6c8fb56",
    "92cfc3b6.safetensors": "a241863551f30d01c42bd7b97da40839922ead3acb0f1fcab25682f55b4eeb59",
    "04573f0d.safetensors": "68854b0d7c2b3274723b5761f6fd9f5aec5f1bcd3f0de7c1669546fdb7871b7c",
}
snapshot = pathlib.Path(snapshot_download(repo, revision=commit))
for name, digest in expected.items():
    if hashlib.sha256((snapshot / name).read_bytes()).hexdigest() != digest:
        sys.exit(f"Checksum mismatch for {name}")
# Demucs asks for the "main" revision by name; offline, that name must point at the pinned commit.
refs = pathlib.Path(hf_home) / "hub" / ("models--" + repo.replace("/", "--")) / "refs"
refs.mkdir(parents=True, exist_ok=True)
(refs / "main").write_text(commit)
print("Weights verified at", commit[:10])
PY

say "Stem splitter offline test"
demucs_offline_test

say "Adding the tools to the desktop app"
install_runtime 20-music.conf 30-stems-voices.conf
cp "$REPO_DIR/runtime/stems_voices.py" "$RUNTIME_DIR/"
exclude_from_backups "$ACE_DIR/.venv" "$STEMS_ENV"

show_next \
  "Check the tools with: ./milestone3.sh --test" \
  "Open Mac AI Studio; the Music and Stems & Voices tabs are now there." \
  "Manual test steps: docs/MANUAL_TESTS.md"
