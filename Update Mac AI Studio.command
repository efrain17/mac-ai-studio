#!/bin/bash
# Double-click to update the studio's Homebrew tools. Quit Mac AI Studio first.
cd "$(dirname "$0")" || exit 1
./update.sh
echo
printf 'Press Return to close this window.'
read -r _
