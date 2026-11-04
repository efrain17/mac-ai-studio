#!/usr/bin/env python3
"""Splits a rendered song into stems and checks the song and the stems like an engineer would.

Runs in the stems environment (NumPy, SoundFile, Demucs). The split goes through the Stems &
Voices page's own code, so a pass here means the page's split works. Each line says PASS or FAIL
with the measured numbers. Exits non-zero on any FAIL.

  check_music.py --song SONG.wav --stems DIR [--expect-duration S]
                 [--expect-vocals | --expect-instrumental] [--no-split]

With a SONG.json next to the song (written by generate_song.py), the expected length and whether
there are vocals are read from it.
"""
import argparse
import json
import math
import pathlib
import sys

import numpy as np
import soundfile as sf

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent


def db(value):
    return 20 * math.log10(max(float(value), 1e-9))


def rms(data):
    return float(np.sqrt(np.mean(np.square(data, dtype=np.float64)))) if data.size else 0.0


def longest_run_at(flags):
    """Length of the longest run of True, and the index where it ends (0, -1 if none)."""
    best, best_end, current = 0, -1, 0
    for index, flag in enumerate(flags):
        current = current + 1 if flag else 0
        if current > best:
            best, best_end = current, index
    return best, best_end


def clock(seconds):
    return f"{int(seconds) // 60}:{seconds % 60:04.1f}"


def resample(data, old_rate, new_rate):
    """Resamples [samples, channels]: exactly through julius (Demucs's own resampler), or
    linearly where julius is not installed."""
    if old_rate == new_rate:
        return data
    try:
        import julius
        import torch
        tensor = torch.from_numpy(np.ascontiguousarray(data.T))
        return julius.resample_frac(tensor, old_rate, new_rate).numpy().T
    except ImportError:
        count = int(round(len(data) * new_rate / old_rate))
        positions = np.linspace(0, len(data) - 1, count)
        samples = np.arange(len(data))
        return np.stack([np.interp(positions, samples, data[:, c]) for c in range(data.shape[1])],
                        axis=1)


class Report:
    def __init__(self):
        self.failed = False

    def check(self, label, ok, detail):
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}", flush=True)
        self.failed = self.failed or not ok


def check_song(path, report, expect_duration):
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    seconds = len(data) / rate
    mono = data.mean(axis=1)
    peak = float(np.abs(data).max()) if data.size else 0.0
    level = rms(mono)

    report.check("Song format", data.shape[1] == 2 and rate in (44100, 48000),
                 f"{data.shape[1]} channels at {rate} Hz")
    if expect_duration:
        report.check("Song length", abs(seconds - expect_duration) <= 0.15 * expect_duration,
                     f"{seconds:.1f} s, asked for {expect_duration} s")
    else:
        report.check("Song length", seconds >= 10, f"{seconds:.1f} s")
    report.check("Song level", -30 <= db(level) <= -6 and db(peak) >= -6,
                 f"RMS {db(level):.1f} dBFS, peak {db(peak):.1f} dBFS")
    clipped = float(np.mean(np.abs(data) >= 0.999)) if data.size else 0.0
    report.check("No clipping", clipped < 0.001, f"{clipped * 100:.3f}% of samples at full scale")

    # A stereo file whose channels are identical is really mono.
    if data.shape[1] == 2 and data[:, 0].std() > 0 and data[:, 1].std() > 0:
        correlation = float(np.corrcoef(data[:, 0], data[:, 1])[0, 1])
    else:
        correlation = 1.0
    report.check("Real stereo", correlation < 0.995, f"left/right correlation {correlation:.3f}")

    # Dropouts: 50 ms windows under -60 dBFS, in a row, between the first and last sound. Silence
    # before the first note or after the last one is not a dropout: ACE-Step fills the asked length,
    # so a song that ends a few seconds early is followed by silence (seen on the Mac, 2026-11-04).
    window = rate // 20
    frames = mono[: len(mono) // window * window].reshape(-1, window)
    quiet = np.sqrt(np.mean(np.square(frames), axis=1)) < 10 ** (-60 / 20)
    sound = np.flatnonzero(~quiet)
    if sound.size:
        first, last = int(sound[0]), int(sound[-1])
        run, end = longest_run_at(quiet[first:last + 1])
        longest = run * window / rate
        at = (first + end - run + 1) * window / rate
        where = f" at {clock(at)}" if run else ""
        report.check("No dropouts", longest <= 3.0, f"longest gap inside the song {longest:.2f} s{where}")
        lead = first * window / rate
        tail = (len(quiet) - 1 - last) * window / rate
        span = (last + 1 - first) * window / rate
        total = len(quiet) * window / rate
        report.check("Music fills the file", span >= 0.85 * total,
                     f"sound from {clock(lead)} to {clock(lead + span)}, "
                     f"{lead:.1f} s of silence before and {tail:.1f} s after")
    else:
        report.check("No dropouts", False, "the whole file is silent")

    # Dynamics: a song has quieter and louder passages; a loop or a drone does not.
    levels = [db(rms(mono[start:start + rate])) for start in range(0, len(mono) - rate, rate)]
    spread = (max(levels) - min(levels)) if len(levels) >= 10 else 99.0
    report.check("Dynamics", spread >= 3.0, f"second-by-second level varies by {spread:.1f} dB")

    # Bandwidth: a real mix has energy above 8 kHz; a muffled render has almost none.
    segment = mono[: min(len(mono), rate * 30)]
    spectrum = np.abs(np.fft.rfft(segment))
    freqs = np.fft.rfftfreq(len(segment), 1 / rate)
    total = float(np.sum(spectrum ** 2))
    high = float(np.sum(spectrum[freqs >= 8000] ** 2))
    brightness = db(math.sqrt(high / total)) if total > 0 else -99.0
    report.check("Full bandwidth", brightness >= -40,
                 f"energy above 8 kHz is {brightness:.1f} dB of the total")
    return data, rate


def check_stems(song, rate, stems_dir, report, expect_vocals):
    stems = {}
    for name in ("vocals", "drums", "bass", "other", "instrumental"):
        path = stems_dir / f"{name}.wav"
        if not path.exists():
            report.check(f"Stem {name}", False, "missing")
            continue
        data, stem_rate = sf.read(path, dtype="float32", always_2d=True)
        stems[name] = (data, stem_rate)
        report.check(f"Stem {name}", data.shape[1] == 2 and rms(data) > 0,
                     f"{len(data) / stem_rate:.1f} s at {stem_rate} Hz, RMS {db(rms(data)):.1f} dBFS")
    if len(stems) < 5:
        return

    rates = {stem_rate for _, stem_rate in stems.values()}
    lengths = {len(data) for data, _ in stems.values()}
    report.check("Stems match", len(rates) == 1 and max(lengths) - min(lengths) <= 1,
                 f"rates {sorted(rates)}, lengths {sorted(lengths)}")
    if len(rates) != 1:
        return
    stem_rate = rates.pop()
    mix = resample(song, rate, stem_rate)
    count = min(min(lengths), len(mix))
    vocals = stems["vocals"][0][:count]
    instrumental = stems["instrumental"][0][:count]
    mix = mix[:count]

    # Demucs's stems add up to the song again, within what the model loses.
    residual = db(rms(mix - (vocals + instrumental))) - db(rms(mix))
    report.check("Stems add up to the song", residual <= -12,
                 f"what is left over is {residual:.1f} dB below the song")
    vocal_share = db(rms(vocals)) - db(rms(mix))
    if expect_vocals:
        report.check("Vocals were found", vocal_share >= -20,
                     f"the vocal stem is {vocal_share:.1f} dB relative to the song")
    else:
        report.check("No stray vocals", vocal_share <= -18,
                     f"the vocal stem is {vocal_share:.1f} dB relative to the song")
    drums, bass = stems["drums"][0][:count], stems["bass"][0][:count]
    correlation = float(np.corrcoef(drums.mean(axis=1), bass.mean(axis=1))[0, 1])
    report.check("Drums and bass are separate", abs(correlation) < 0.9,
                 f"correlation {correlation:.3f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--song", type=pathlib.Path, required=True)
    parser.add_argument("--stems", type=pathlib.Path, required=True,
                        help="folder that gets one subfolder per song, like the page's stems folder")
    parser.add_argument("--expect-duration", type=float)
    parser.add_argument("--expect-vocals", dest="vocals", action="store_true", default=None)
    parser.add_argument("--expect-instrumental", dest="vocals", action="store_false")
    parser.add_argument("--no-split", action="store_true", help="check the song only")
    args = parser.parse_args()

    sidecar = args.song.with_suffix(".json")
    if sidecar.exists():
        record = json.loads(sidecar.read_text())
        if args.expect_duration is None:
            args.expect_duration = record.get("duration_requested")
        if args.vocals is None:
            args.vocals = not record.get("instrumental", False)

    report = Report()
    print(f"== {args.song.name}", flush=True)
    song, rate = check_song(args.song, report, args.expect_duration)
    if not args.no_split:
        sys.path.insert(0, str(REPO_DIR / "runtime"))
        from stems_voices import safe_name, split_file  # the page's own split code

        target = args.stems / safe_name(args.song.stem)
        try:
            split_file(args.song, target)
        except RuntimeError as error:
            report.check("Split", False, str(error)[-1500:])
        else:
            check_stems(song, rate, target, report, args.vocals is not False)
    sys.exit(1 if report.failed else 0)


if __name__ == "__main__":
    main()
