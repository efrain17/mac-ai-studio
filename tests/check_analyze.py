#!/usr/bin/env python3
"""Checks the Analyze tab's measurements without opening the page.

Makes a 12-second A major chord with a click on every beat at 120 BPM, then asks the page's own
analysis for its tempo, key, length and levels. Runs in the stems environment. Exits non-zero on
failure.
"""
import os
import pathlib
import sys
import tempfile

import numpy as np
import soundfile as sf

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
failed = False


def check(label, ok, detail):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}", flush=True)
    failed = failed or not ok


def test_song(path, samplerate=22050, seconds=12, bpm=120):
    t = np.arange(seconds * samplerate) / samplerate
    chord = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 277.18, 329.63, 440.0))  # A, C#, E, A
    chord = 0.2 * chord / np.abs(chord).max()
    clicks = np.zeros_like(t)
    for beat in np.arange(0, seconds, 60 / bpm):
        start = int(beat * samplerate)
        clicks[start:start + 400] = 0.8 * np.exp(-np.arange(400) / 60) * np.sign(np.sin(2 * np.pi * 1000 * t[:400]))
    sf.write(path, chord + clicks, samplerate)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        os.environ["STUDIO_HOME"] = temporary
        sys.path.insert(0, str(REPO_DIR / "runtime"))
        import stems_voices as page

        song = pathlib.Path(temporary) / "song.wav"
        test_song(song)
        result = page.analyze_file(song)
        check("Tempo", 115 <= result["tempo_bpm"] <= 125, f"{result['tempo_bpm']} BPM, expected 120")
        check("Key", result["key"] == "A major", result["key"])
        check("Length", result["length_seconds"] == 12.0, f"{result['length_seconds']} s")
        check("Peak", -2 <= result["peak_dbfs"] <= 0, f"{result['peak_dbfs']} dBFS")
        check("Loudness below peak", result["loudness_dbfs"] < result["peak_dbfs"], f"{result['loudness_dbfs']} dBFS")
        check("Key names", page.estimate_key(np.roll([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0], 2)) == "D major",
              "D F# A -> D major")
        text = page.analyze_song(str(song))
        check("Page text", "BPM" in text and "A major" in text, text.splitlines()[2])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
