#!/bin/bash
# Downloads the model files a ComfyUI template, or a workflow you saved, needs, into the folders
# the studio's ComfyUI reads. It shows each file with its size and folder first, and asks.
#
#   ./get-models.sh --list                          every template and saved workflow, and what it needs
#   ./get-models.sh --list flux                     only those whose name contains "flux"
#   ./get-models.sh "Z-Image-Turbo: Text to Image"  show what is missing, ask, then download
#   ./get-models.sh --check "Z-Image-Turbo"         show what is missing; download nothing
#
# The name is the title on the template's card in ComfyUI's Templates window (or any part of
# it), or the name of a workflow in the Workflows panel. Safe to run again: files already there
# are skipped and an interrupted download resumes. Only Hugging Face addresses are used, and each
# file is checked against the checksum Hugging Face reports for it.
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

require_milestone1
for argument in "$@"; do
  case "$argument" in
    --list|--check|--help|-h) listing=1 ;;
  esac
done
# A download is logged and keeps the Mac awake; a list or a check is just printed.
[ $# -eq 0 ] || [ -n "${listing:-}" ] || start_run get-models
"$COMFYUI_ENV/bin/python" -I -u "$REPO_DIR/tools/get_models.py" "$@"
