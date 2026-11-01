#!/usr/bin/env python3
"""Checks rendered videos for the silent failures Metal can produce.

Metal bugs often give black or steadily corrupting video with no error, so a clean exit from the
renderer proves nothing. Runs in the ComfyUI environment, which has PyAV and NumPy.
"""
import pathlib
import sys

import av
import numpy as np


def check(path):
    with av.open(str(path)) as container:
        frames = [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
    if len(frames) < 2:
        return f"only {len(frames)} frame(s)"
    brightness = [float(frame.mean()) for frame in frames]
    if max(brightness) < 25:
        return f"all frames are black (peak brightness {max(brightness):.1f})"
    if max(float(frame.std()) for frame in frames) < 2:
        return "frames are a flat color"
    saturation = [float((frame.max(axis=2) - frame.min(axis=2)).mean()) for frame in frames]
    third = max(1, len(frames) // 3)
    start, end = np.mean(saturation[:third]), np.mean(saturation[-third:])
    print(f"       {len(frames)} frames, brightness {min(brightness):.0f}-{max(brightness):.0f}, "
          f"color {start:.0f} to {end:.0f}")
    # Sketch-and-fill starts on white paper, so rising color is expected there.
    if "sketch_and_fill" not in path.name and start > 5 and end > start * 2.5:
        return f"color keeps growing ({start:.0f} to {end:.0f}), the sign of Metal corruption"
    return None


def main():
    paths = sorted(pathlib.Path(sys.argv[1]).glob("*.mp4"))
    if not paths:
        sys.exit("No videos to check.")
    failed = False
    for path in paths:
        problem = check(path)
        print(f"{'FAIL' if problem else 'PASS'}  {path.name}" + (f": {problem}" if problem else ""))
        failed = failed or bool(problem)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
