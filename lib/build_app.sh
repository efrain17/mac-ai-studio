# shellcheck shell=bash
# Compiles the native app and places it in /Applications. Needs Apple's Command Line Tools.

build_app() {
  local app="/Applications/Mac AI Studio.app"
  local tmp contents
  tmp="$(mktemp -d "$TMPDIR/app.XXXXXX")"
  contents="$tmp/Mac AI Studio.app/Contents"
  mkdir -p "$contents/MacOS" "$contents/Resources"

  xcrun --sdk macosx swiftc -O -swift-version 5 \
    -framework Cocoa -framework WebKit -framework UniformTypeIdentifiers \
    -o "$contents/MacOS/MacAIStudio" "$REPO_DIR/app/MacAIStudio.swift" \
    || die "The desktop app did not compile."

  printf '%s\n' "$RUNTIME_DIR/services.sh" > "$contents/Resources/services-path.txt"
  cp "$REPO_DIR/app/Info.plist" "$contents/Info.plist"
  [ -f "$REPO_DIR/app/AppIcon.icns" ] && cp "$REPO_DIR/app/AppIcon.icns" "$contents/Resources/"

  # A local ad-hoc signature: Apple Silicon refuses to run unsigned code.
  codesign --force --deep --sign - "$tmp/Mac AI Studio.app" >/dev/null \
    || die "Could not sign the desktop app."

  rm -rf "$app"
  ditto "$tmp/Mac AI Studio.app" "$app"
  rm -rf "$tmp"
  echo "Installed: $app"
}
