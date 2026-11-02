#!/usr/bin/env python3
"""Renders complete songs with ACE-Step, offline, the way the Music tab does.

Runs in ACE-Step's own environment with the Music tab's settings: the XL turbo model, the 4B
language model on MLX, thinking mode on. Each song is saved as <name>.wav next to a <name>.json
with everything used to make it and how long it took. Exits non-zero if a song fails.

  generate_song.py --ace-dir DIR --out DIR [--songs a,b] [--duration SECONDS] [--seed N]
"""
import argparse
import json
import os
import pathlib
import shutil
import sys
import time

# Generic placeholder songs, so the test files use no private material. Captions follow
# ACE-Step's advice: genre, instruments, voice, mood, tempo. Lyrics use its structure tags.
SONGS = {
    "indie_folk_vocal": {
        "caption": "warm indie folk, fingerpicked acoustic guitar, soft brushed drums, upright bass, "
                   "young adult female lead vocal, intimate and hopeful, natural room reverb, 90 BPM",
        "lyrics": """[Verse 1]
Morning on the water
Paper boats in line
Every little ripple
Keeps a little time

[Chorus]
Carry me slowly
Over the bay
Carry me slowly
Into the day

[Verse 2]
Sunlight on the shoulder
Of the sleeping town
Someone hums a chorus
Nobody wrote down

[Chorus]
Carry me slowly
Over the bay
Carry me slowly
Into the day

[Bridge - quiet, just guitar]
If the wind forgets us
We will know the way

[Chorus - full]
Carry me slowly
Over the bay
Carry me slowly
Into the day

[Outro - guitar fades]""",
        "bpm": 90, "keyscale": "G major", "timesignature": "4", "language": "en", "duration": 120,
    },
    "cinematic_score": {
        "caption": "cinematic orchestral score, slow building strings, deep brass swells, soft piano "
                   "motif, taiko drums entering halfway, hopeful and vast, film trailer, instrumental",
        "lyrics": "[Instrumental]",
        "instrumental": True,
        "bpm": 70, "keyscale": "D minor", "timesignature": "4", "language": "unknown", "duration": 90,
    },
    "upbeat_pop_vocal": {
        "caption": "modern upbeat pop, punchy drums, bright synth chords, clean electric guitar, "
                   "adult male lead vocal, catchy anthemic chorus, polished radio mix, 120 BPM",
        "lyrics": """[Intro]

[Verse 1]
Streetlights blinking off one by one
Coffee in a paper cup, here comes the sun
Headphones on, the city starts to hum
Every step I take is a little drum

[Pre-Chorus]
Count it in, three, two, one

[Chorus]
We're wide awake, wide awake
Running down the avenue
Wide awake, wide awake
Morning feels brand new

[Verse 2]
Bus is late, I don't mind the wait
Window glass reflecting all the plans we make
Turn the corner, there's the open gate
Today is not the day I hesitate

[Pre-Chorus]
Count it in, three, two, one

[Chorus]
We're wide awake, wide awake
Running down the avenue
Wide awake, wide awake
Morning feels brand new

[Bridge]
Hold the note, let it ring
Let the whole block sing

[Chorus - big finish]
We're wide awake, wide awake
Running down the avenue
Wide awake, wide awake
Morning feels brand new

[Outro]""",
        "bpm": 120, "keyscale": "C major", "timesignature": "4", "language": "en", "duration": 130,
    },
}


def load_models(ace_dir, model, lm_model):
    """Loads the DiT and the language model with the Music tab's settings."""
    from acestep.handler import AceStepHandler
    from acestep.llm_inference import LLMHandler

    started = time.time()
    dit = AceStepHandler()
    # On Metal the handler picks float32 itself; use_mlx_dit matches the page's default.
    status, ok = dit.initialize_service(project_root=ace_dir, config_path=model, device="auto",
                                        use_mlx_dit=True)
    if not ok:
        sys.exit(f"The music model did not load: {status}")
    lm = LLMHandler()
    status, ok = lm.initialize(checkpoint_dir=os.environ["ACESTEP_CHECKPOINTS_DIR"],
                               lm_model_path=lm_model, backend="mlx", device="auto")
    if not ok:
        sys.exit(f"The language model did not load: {status}")
    print(f"Models loaded in {time.time() - started:.0f} s", flush=True)
    return dit, lm


def render(dit, lm, name, song, out, duration, seed, steps, audio_format):
    from acestep.inference import GenerationConfig, GenerationParams, generate_music

    params = GenerationParams(
        task_type="text2music", thinking=True, caption=song["caption"], lyrics=song["lyrics"],
        instrumental=song.get("instrumental", False), bpm=song["bpm"], keyscale=song["keyscale"],
        timesignature=song["timesignature"], vocal_language=song["language"],
        duration=float(duration), inference_steps=steps, seed=seed,
    )
    config = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[seed],
                              audio_format=audio_format)
    work = out / f".render-{name}"
    started = time.time()
    result = generate_music(dit, lm, params=params, config=config, save_dir=str(work))
    elapsed = time.time() - started
    if not result.success or not result.audios or not result.audios[0].get("path"):
        raise RuntimeError(result.error or result.status_message or "nothing was produced")
    produced = pathlib.Path(result.audios[0]["path"])
    target = out / f"{name}{produced.suffix}"
    shutil.move(str(produced), target)
    shutil.rmtree(work, ignore_errors=True)
    record = {
        "song": name, "caption": song["caption"], "lyrics": song["lyrics"],
        "instrumental": song.get("instrumental", False), "bpm": song["bpm"],
        "keyscale": song["keyscale"], "timesignature": song["timesignature"],
        "language": song["language"], "duration_requested": duration, "seed": seed,
        "inference_steps": steps, "thinking": True, "sample_rate": result.audios[0].get("sample_rate"),
        "seconds_to_render": round(elapsed), "file": target.name,
        # What the language model decided (tempo, key, length), when it reports it.
        "model_notes": json.loads(json.dumps(result.extra_outputs, default=str)),
    }
    target.with_suffix(".json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return target, elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ace-dir", type=pathlib.Path, required=True, help="ACE-Step's folder")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--songs", default="indie_folk_vocal",
                        help="comma-separated names from: " + ", ".join(SONGS))
    parser.add_argument("--duration", type=int, help="seconds, for every song listed")
    parser.add_argument("--seed", type=int, default=4601, help="first seed; each song adds one")
    parser.add_argument("--steps", type=int, default=8, help="diffusion steps; 8 is right for turbo")
    parser.add_argument("--model", default="acestep-v15-xl-turbo")
    parser.add_argument("--lm-model", default="acestep-5Hz-lm-4B")
    parser.add_argument("--format", default="wav", help="wav, wav32 or flac")
    args = parser.parse_args()

    names = [name.strip() for name in args.songs.split(",") if name.strip()]
    unknown = [name for name in names if name not in SONGS]
    if unknown or not names:
        sys.exit(f"Unknown song(s): {', '.join(unknown) or '(none given)'}. Choose from: {', '.join(SONGS)}")
    args.out.mkdir(parents=True, exist_ok=True)

    # ACE-Step reads its .env from its own folder, and imports from there.
    ace_dir = str(args.ace_dir.resolve())
    os.chdir(ace_dir)
    sys.path.insert(0, ace_dir)
    dit, lm = load_models(ace_dir, args.model, args.lm_model)

    failed = False
    for index, name in enumerate(names):
        song = SONGS[name]
        duration = args.duration or song["duration"]
        try:
            target, elapsed = render(dit, lm, name, song, args.out, duration, args.seed + index,
                                     args.steps, args.format)
            print(f"PASS  {name}: {target.name}, {duration} s of music in {elapsed:.0f} s", flush=True)
        except (RuntimeError, OSError) as error:
            failed = True
            print(f"FAIL  {name}: {error}", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
