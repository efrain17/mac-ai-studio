#!/usr/bin/env python3
"""Checks the Chords tab without opening the page or running Demucs.

Makes a 16-second song that plays C, G, Am and F twice, two seconds each, with a click on every
beat at 120 BPM, and asks the page's own chord reader for its chords and their times. Then it
replaces the split with stand-in stems (the song as the guitar, a silent piano) and checks the
chart for each instrument. Runs in the stems environment. Exits non-zero on failure.
"""
import os
import pathlib
import sys
import tempfile

import numpy as np
import soundfile as sf

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
SAMPLERATE = 22050
# Root, third and fifth of each chord, as MIDI notes around middle C, with the root an octave down.
PROGRESSION = (("C", (48, 60, 64, 67)), ("G", (43, 59, 62, 67)), ("Am", (45, 60, 64, 69)), ("F", (41, 60, 65, 69)))
CHORD_SECONDS = 2.0
failed = False


def check(label, ok, detail):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}", flush=True)
    failed = failed or not ok


def tone(midi, seconds):
    t = np.arange(int(seconds * SAMPLERATE)) / SAMPLERATE
    frequency = 440.0 * 2 ** ((midi - 69) / 12)
    # A few harmonics, fading, like a plucked or struck string.
    wave = sum(np.sin(2 * np.pi * frequency * k * t) / k for k in (1, 2, 3))
    return wave * np.exp(-t * 0.8)


def test_song(repeats=2):
    parts = []
    for _ in range(repeats):
        for _, notes in PROGRESSION:
            parts.append(sum(tone(note, CHORD_SECONDS) for note in notes))
    song = np.concatenate(parts)
    song = 0.3 * song / np.abs(song).max()
    for beat in np.arange(0, len(song) / SAMPLERATE, 0.5):
        start = int(beat * SAMPLERATE)
        song[start:start + 300] += 0.3 * np.exp(-np.arange(300) / 40) * np.random.default_rng(1).uniform(-1, 1, 300)
    return song.astype(np.float32)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        os.environ["STUDIO_HOME"] = temporary
        sys.path.insert(0, str(REPO_DIR / "runtime"))
        import stems_voices as page

        song = test_song()
        segments = page.read_chords(song, SAMPLERATE)
        names = [name for _, _, name in segments if name != page.NO_CHORD]
        expected = [name for name, _ in PROGRESSION] * 2
        check("Chord names", names == expected, " ".join(names) + f" (expected {' '.join(expected)})")
        starts = [start for start, _, name in segments if name != page.NO_CHORD]
        offsets = [abs(start - i * CHORD_SECONDS) for i, start in enumerate(starts)]
        check("Chord times", len(offsets) == len(expected) and max(offsets) <= 0.6,
              "largest offset " + (f"{max(offsets):.2f} s" if offsets else "none"))

        silence = np.zeros(SAMPLERATE * 4, dtype=np.float32)
        check("Silence", all(name == page.NO_CHORD for _, _, name in page.read_chords(silence, SAMPLERATE)),
              "a silent part is marked N.C.")
        check("Chord spelling", page.chord_name(10, "major", flats=True) == "Bb"
              and page.chord_name(1, "minor", flats=False) == "C#m", "Bb in a flat key, C#m in a sharp key")
        check("Timestamps", page.timestamp(75.25) == "1:15.2", page.timestamp(75.25))

        path = pathlib.Path(temporary) / "Test Song.wav"
        sf.write(path, song, SAMPLERATE)

        def stand_in_split(source, target, progress=None, choice=None):
            target.mkdir(parents=True, exist_ok=True)
            written = {}
            for stem in ("vocals", "drums", "bass", "guitar", "piano", "other"):
                written[stem] = str(target / f"{stem}.wav")
                sf.write(written[stem], song if stem == "guitar" else np.zeros_like(song), SAMPLERATE)
            return written

        page.split_file = stand_in_split
        chart, saved = page.chord_chart(str(path), split=True)
        check("Chart sections", all(title in chart for title in ("Main progression", "Guitar", "Keys")),
              "main, guitar and keys")
        guitar = chart.split("== Guitar ==")[1].split("\n== ")[0]
        keys = chart.split("== Keys")[1]
        check("Guitar chart", "0:00.0  C" in guitar and "Am" in guitar, guitar.strip().splitlines()[0])
        check("Silent keys part", "No keyboard part" in keys, keys.strip().splitlines()[1])
        check("Saved as text", pathlib.Path(saved).read_text() == chart and saved.endswith("Test Song.txt"), saved)

        chart, _ = page.chord_chart(str(path), split=False)
        check("Whole song only", "Whole song" in chart and "Guitar" not in chart and "G" in chart,
              "one chart, no split")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
