#!/bin/bash
# Removes the studio and frees its disk space. Finished work is kept: the output folder moves to
# Documents first. Homebrew and everything installed through it stay, since other programs may
# rely on them.
set -euo pipefail
. "$(dirname "$0")/runtime/env.sh"

[ -d "$STUDIO_HOME" ] || { echo "Nothing to remove: $STUDIO_HOME does not exist."; exit 0; }

echo "This removes $STUDIO_HOME ($(du -sh "$STUDIO_HOME" | cut -f1)) and /Applications/Mac AI Studio.app."
echo "Your finished files in $OUTPUT_DIR, and the workflows the chat made, move to Documents and are kept."
printf 'Type REMOVE to continue: '
read -r answer
[ "$answer" = "REMOVE" ] || { echo "Nothing was changed."; exit 0; }

[ ! -x "$RUNTIME_DIR/services.sh" ] || "$RUNTIME_DIR/services.sh" stop-all

# Workflows the chat made are the owner's work too: they go with the finished files.
chat_workflows="$STUDIO_HOME/ComfyUI/user/default/workflows/Mac AI Studio/From chat"
if [ -d "$chat_workflows" ] && [ -n "$(ls -A "$chat_workflows")" ]; then
  mkdir -p "$OUTPUT_DIR/workflows from chat"
  cp "$chat_workflows"/*.json "$OUTPUT_DIR/workflows from chat/"
fi

if [ -d "$OUTPUT_DIR" ] && [ -n "$(ls -A "$OUTPUT_DIR")" ]; then
  kept="$HOME/Documents/MacAIStudio-output-$(date +%Y%m%d-%H%M%S)"
  mv "$OUTPUT_DIR" "$kept"
  echo "Your files are in $kept"
fi

# The app and library settings only point into the studio folder if the studio created them.
library_file="$HOME/Library/Application Support/StabilityMatrix/library.json"
if [ -f "$library_file" ] && grep -q "$STUDIO_HOME" "$library_file"; then
  rm -f "$library_file"
fi
# The chat model was linked into LM Studio's model list; LM Studio and AnythingLLM themselves stay.
rm -f "$HOME/.lmstudio/models/mlx-community/gpt-oss-120b-MXFP4-Q8"
rm -rf "/Applications/Mac AI Studio.app" "$STUDIO_HOME"
echo "Removed. LM Studio, AnythingLLM and their settings stay; delete them from Applications if you do not want them."
