#!/bin/bash
# Milestone 3 Pro: a real test of the music studio. Renders a complete song with ACE-Step the way
# the Music tab does, splits it with the Stems & Voices page's own code, and checks the song and
# the stems like an engineer would: length, level, clipping, stereo, dropouts, dynamics,
# bandwidth, and whether the stems add up to the song. Installs nothing. Needs milestone 3.
#
#   ./milestone3-pro.sh            the test: a 2-minute song with vocals, split and checked
#   ./milestone3-pro.sh --test     the same
#   ./milestone3-pro.sh --samples  three full songs in different styles, to judge the quality
#   ./milestone3-pro.sh --verify   check the installed models against their checksums
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

MANIFEST="$REPO_DIR/manifests/milestone3.txt"
ACE_DIR="$STUDIO_HOME/ace-step"
STEMS_ENV="$ENVS_DIR/stems-voices"
TEST_OUT="$OUTPUT_DIR/music_pro_test_samples"
SAMPLES_OUT="$OUTPUT_DIR/music_pro_samples"
# The page code reads this to find the studio.
export STUDIO_HOME

require_milestone3() {
  [ -x "$ACE_DIR/.venv/bin/python" ] && [ -x "$STEMS_ENV/bin/python" ] \
    && [ -f "$RUNTIME_DIR/services/20-music.conf" ] \
    || die "Milestone 3 is not installed. Run ./milestone3.sh first."
}

# render OUT SONGS [generate_song.py options]: the Music tab's models and settings, without the page.
render() {
  local out="$1" songs="$2"
  shift 2
  # The same environment as runtime/services/20-music.conf. torchcodec finds FFmpeg through the
  # DYLD variable, which macOS strips from scripts, so it is set on the command itself.
  (
    cd "$ACE_DIR"
    PATH="$BREW_FFMPEG/bin:$PATH" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 CHECK_UPDATE=false \
    TOKENIZERS_PARALLELISM=false ACESTEP_CHECKPOINTS_DIR="$MODELS_DIR/ace-step" \
    XDG_DATA_HOME="$ACE_DIR/.data" DYLD_FALLBACK_LIBRARY_PATH="$BREW_FFMPEG/lib" \
      "$ACE_DIR/.venv/bin/python" "$REPO_DIR/tests/generate_song.py" \
        --ace-dir "$ACE_DIR" --out "$out" --songs "$songs" "$@"
  )
}

# check_song SONG.wav STEMS_DIR [check_music.py options]: splits the song and checks everything.
check_song() {
  local song="$1" stems="$2"
  shift 2
  HF_HUB_OFFLINE=1 PATH="$BREW_FFMPEG/bin:$PATH" "$STEMS_ENV/bin/python" \
    "$REPO_DIR/tests/check_music.py" --song "$song" --stems "$stems" "$@"
}

# Demucs must never fetch weights from outside the verified cache (see milestone3.sh).
check_demucs_source() {
  if [ -n "$(ls -A "$TORCH_HOME/hub/checkpoints" 2>/dev/null)" ]; then
    die "Demucs used weights from outside the verified cache. See $TORCH_HOME/hub/checkpoints."
  fi
}

prepare() {
  preflight "$1"
  require_milestone1
  require_milestone3
  verify_models "$MANIFEST" || die "Models are missing or damaged. Run ./milestone3.sh again."
  start_run "$2"
  # The Music tab holds its own copy of the models; a second copy would double the memory.
  "$RUNTIME_DIR/services.sh" stop-all
  rm -rf "$3"
  mkdir -p "$3"
}

case "${1:-}" in
  --verify)
    verify_models "$MANIFEST"
    exit $?
    ;;
  ""|--test)
    prepare 5 milestone3-pro "$TEST_OUT"
    say "Song: 2 minutes of indie folk with vocals (the models take minutes to load)"
    render "$TEST_OUT" indie_folk_vocal --duration 120 \
      || die "The song did not render. See 'Music' in docs/TROUBLESHOOTING.md."
    status=0
    say "Stems and checks"
    check_song "$TEST_OUT/indie_folk_vocal.wav" "$TEST_OUT/stems" || status=1
    check_demucs_source
    say "Voice profiles"
    "$STEMS_ENV/bin/python" "$REPO_DIR/tests/check_voice_profiles.py" || status=1
    open "$TEST_OUT"
    [ "$status" = 0 ] || die "A check failed. See 'Music' and 'Stems and voices' in docs/TROUBLESHOOTING.md."
    show_next "Every check passed. The song, its stems and its settings are in $TEST_OUT."
    ;;
  --samples)
    prepare 10 milestone3-pro-samples "$SAMPLES_OUT"
    say "Three full songs: indie folk with vocals, cinematic score, upbeat pop with vocals"
    render "$SAMPLES_OUT" indie_folk_vocal,cinematic_score,upbeat_pop_vocal \
      || die "A song did not render. See 'Music' in docs/TROUBLESHOOTING.md."
    status=0
    say "Checks, with stems for the songs that have vocals"
    check_song "$SAMPLES_OUT/indie_folk_vocal.wav" "$SAMPLES_OUT/stems" || status=1
    check_song "$SAMPLES_OUT/upbeat_pop_vocal.wav" "$SAMPLES_OUT/stems" || status=1
    check_song "$SAMPLES_OUT/cinematic_score.wav" "$SAMPLES_OUT/stems" --no-split || status=1
    check_demucs_source
    open "$SAMPLES_OUT"
    [ "$status" = 0 ] || die "A check failed. See 'Music' and 'Stems and voices' in docs/TROUBLESHOOTING.md."
    show_next "Every check passed. The songs, stems and settings are in $SAMPLES_OUT." \
      "Each song's .json file holds the caption and lyrics, ready to paste into the Music tab."
    ;;
  *) die "Unknown option: $1" ;;
esac
