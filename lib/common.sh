# shellcheck shell=bash disable=SC2034
# Shared by the milestone scripts. Written for the bash 3.2 that ships with macOS.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../versions.env
. "$REPO_DIR/versions.env"
# shellcheck source=../runtime/env.sh
. "$REPO_DIR/runtime/env.sh"
# shellcheck source=build_app.sh
. "$REPO_DIR/lib/build_app.sh"

say()  { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }
size_of()   { stat -f %z "$1"; }
free_gb()   { df -g "$1" | awk 'NR==2 {print $4}'; }

# Creates the private folders and keeps a log of the whole run.
start_run() {
  local name="$1"
  case "$STUDIO_HOME" in
    *' '*) die "The install folder cannot contain spaces (Miniconda's rule): $STUDIO_HOME" ;;
  esac
  mkdir -p "$STUDIO_HOME" "$ENVS_DIR" "$LOG_DIR" "$RUN_DIR" "$CACHE_DIR" "$TMPDIR" \
    "$STUDIO_HOME/.downloads" "$MODELS_DIR" "$INPUT_DIR" "$OUTPUT_DIR"
  exec > >(tee -a "$LOG_DIR/$name-$(date +%Y%m%d-%H%M%S).log") 2>&1
  # Keeps the Mac awake for as long as this script runs, and stops by itself afterwards.
  caffeinate -dims -w $$ &
  if pmset -g batt | grep -q 'Battery Power'; then
    warn "This Mac is on battery. Plug it in: long downloads and installs may drain it."
  fi
}

# preflight MIN_FREE_GB: refuses any Mac the pinned builds cannot run on.
preflight() {
  local min_free="$1" arch translated macos major chip mem_gb probe
  arch="$(uname -m)"
  translated="$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)"
  macos="$(sw_vers -productVersion)"
  major="${macos%%.*}"
  chip="$(sysctl -n machdep.cpu.brand_string)"
  mem_gb=$(( $(sysctl -n hw.memsize) / 1073741824 ))
  probe="$STUDIO_HOME"
  [ -d "$probe" ] || probe="$HOME"

  echo "Mac: $chip, ${mem_gb} GB memory, macOS $macos, $(free_gb "$probe") GB free"

  [ "$translated" = "1" ] && die "This Terminal runs under Rosetta. Open a native Terminal and run it again."
  [ "$arch" = "arm64" ] || die "This Mac is $arch ($chip). The studio needs Apple Silicon."
  [ "$major" -ge 15 ] || die "macOS $macos is too old. Homebrew's ready-made packages need macOS 15 or newer."
  [ "$(free_gb "$probe")" -ge "$min_free" ] || die "Need at least $min_free GB free on disk."

  case "$chip" in
    *Max*) ;;
    *) warn "The target chip is an M-series Max; this Mac reports $chip. Render times will differ." ;;
  esac
  [ "$mem_gb" -ge 128 ] || warn "The target memory is 128 GB; this Mac has $mem_gb GB. Render times will differ."
}

# require_milestone1: later milestones build on the first one.
require_milestone1() {
  [ -x "$COMFYUI_ENV/bin/python" ] && [ -x "$BREW_PREFIX/bin/brew" ] && [ -x "$RUNTIME_DIR/services.sh" ] \
    || die "Milestone 1 is not installed. Run ./milestone1.sh first."
}

# Settings for installing: nothing the Mac already has gets upgraded or removed.
# Upgrades happen only through update.sh.
use_homebrew() {
  export HOMEBREW_NO_AUTO_UPDATE=1
  export HOMEBREW_NO_INSTALL_UPGRADE=1
  export HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK=1
  export HOMEBREW_NO_INSTALL_CLEANUP=1
  export HOMEBREW_NO_ANALYTICS=1
  export HOMEBREW_NO_ENV_HINTS=1
  eval "$("$BREW_PREFIX/bin/brew" shellenv)"
}

# Installs Homebrew formulas that are not already there.
brew_formulas() {
  local name
  for name in "$@"; do
    brew list --formula "$name" >/dev/null 2>&1 || brew install "$name" \
      || die "Homebrew could not install $name."
  done
}

# download_verified URL DEST SHA256: resumes partial files, never leaves a bad file at DEST.
download_verified() {
  local url="$1" dest="$2" expected="$3" part actual
  part="$dest.part"
  if [ -f "$dest" ] && [ "$(sha256_of "$dest")" = "$expected" ]; then
    echo "Already downloaded: $(basename "$dest")"
    return 0
  fi
  rm -f "$dest"
  mkdir -p "$(dirname "$dest")"
  # A finished .part would make curl's resume fail with HTTP 416.
  if [ -f "$part" ] && [ "$(sha256_of "$part")" = "$expected" ]; then
    mv "$part" "$dest"
    return 0
  fi
  curl -fL --retry 5 --retry-delay 5 --retry-connrefused -C - -o "$part" "$url" \
    || die "Download failed: $url
Check the internet connection and run this script again; it resumes where it stopped."
  actual="$(sha256_of "$part")"
  if [ "$actual" != "$expected" ]; then
    rm -f "$part"
    die "Checksum mismatch for $(basename "$dest"): expected $expected, got $actual"
  fi
  mv "$part" "$dest"
}

# fetch_models MANIFEST: downloads and verifies every model it lists.
# Line format: folder|filename|bytes|sha256|url|license
fetch_models() {
  local folder name bytes sha url license
  while IFS='|' read -r folder name bytes sha url license; do
    case "$folder" in ''|\#*) continue ;; esac
    say "$folder/$name ($(( bytes / 1048576 )) MB, license: $license)"
    download_verified "$url" "$MODELS_DIR/$folder/$name" "$sha"
  done < "$1"
}

# verify_models MANIFEST: checks files on disk and downloads nothing. Non-zero if any is wrong.
verify_models() {
  local folder name bytes sha url license dest bad=0
  while IFS='|' read -r folder name bytes sha url license; do
    case "$folder" in ''|\#*) continue ;; esac
    dest="$MODELS_DIR/$folder/$name"
    if [ ! -f "$dest" ]; then
      echo "MISSING  $folder/$name"; bad=1
    elif [ "$(size_of "$dest")" != "$bytes" ] || [ "$(sha256_of "$dest")" != "$sha" ]; then
      echo "DAMAGED  $folder/$name"; bad=1
    else
      echo "OK       $folder/$name"
    fi
  done < "$1"
  return "$bad"
}

# Makes a Python environment from Homebrew's Python 3.12. Each tool has its own, so their
# packages never clash. One broken by a Python upgrade is rebuilt.
make_venv() {
  local prefix="$1"
  if ! "$prefix/bin/python" -c '' >/dev/null 2>&1; then
    rm -rf "$prefix"
    "$BREW_PYTHON" -m venv "$prefix" || die "Could not create the environment at $prefix."
  fi
  local arch
  arch="$("$prefix/bin/python" -c 'import platform; print(platform.machine())')"
  [ "$arch" = "arm64" ] || die "$prefix has an $arch Python, expected arm64."
}

# Copies the service launcher files out of the repo, so the repo can be moved or deleted.
install_runtime() {
  mkdir -p "$RUNTIME_DIR/services"
  cp "$REPO_DIR/runtime/env.sh" "$REPO_DIR/runtime/services.sh" "$RUNTIME_DIR/"
  chmod +x "$RUNTIME_DIR/services.sh"
  local conf
  for conf in "$@"; do
    cp "$REPO_DIR/runtime/services/$conf" "$RUNTIME_DIR/services/"
  done
}

# Backups would otherwise copy tens of GB of files that can always be downloaded again.
exclude_from_backups() {
  local path
  for path in "$@"; do
    [ -e "$path" ] && tmutil addexclusion "$path" 2>/dev/null || true
  done
}

# Finishes a milestone by rendering a check image, or by printing where to go next.
show_next() {
  say "Finished. Log: $LOG_DIR"
  printf '%s\n' "$@"
}
