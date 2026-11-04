#!/usr/bin/env python3
"""Local page with three tools: stem splitting (Demucs), song analysis (librosa) and a library of
voice profiles.

Runs on 127.0.0.1 only, with analytics off. Nothing leaves the Mac.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import gradio as gr
import numpy as np
import soundfile as sf

STUDIO_HOME = pathlib.Path(os.environ["STUDIO_HOME"])
STEMS_DIR = STUDIO_HOME / "output" / "stems"
PROFILES_FILE = STUDIO_HOME / "output" / "voice_profiles.json"
DEMUCS_MODEL = os.environ.get("DEMUCS_MODEL", "htdemucs_ft")
DEMUCS_MODEL_6S = os.environ.get("DEMUCS_MODEL_6S", "htdemucs_6s")
DEMUCS_DEVICE = os.environ.get("DEMUCS_DEVICE", "mps")
# What each choice produces, in the order the page shows them. "other" is what the model could
# not name: with 4 stems it holds guitars, keys, synths and strings together.
STEM_CHOICES = {
    "4 stems: vocals, drums, bass, other (best quality)": (DEMUCS_MODEL, ("vocals", "drums", "bass", "other")),
    "6 stems: adds guitar and piano (piano is weak)": (DEMUCS_MODEL_6S, ("vocals", "drums", "bass", "guitar", "piano", "other")),
}
DEFAULT_CHOICE = next(iter(STEM_CHOICES))
ALL_STEMS = ("vocals", "instrumental", "drums", "bass", "other", "guitar", "piano")
NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
# Krumhansl-Kessler key profiles: how much each of the 12 notes belongs to a major or minor key.
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

AGES = ["child", "teenager", "young adult", "adult", "middle-aged", "elderly"]
GENDERS = ["female", "male", "androgynous"]
TONES = ["warm", "bright", "dark", "breathy", "powerful", "soft", "nasal", "operatic"]
RASPINESS = ["clean", "slightly raspy", "raspy", "very raspy, gravelly"]


def safe_name(name):
    cleaned = re.sub(r"[^\w\- ]", "", name, flags=re.UNICODE).strip()
    return cleaned or "untitled"


# ---- Stems ----------------------------------------------------------------------------------


def split_file(source, target, progress=None, choice=DEFAULT_CHOICE):
    """Splits one song into WAV stems inside TARGET: the model's stems plus an instrumental.

    Returns the written paths by stem name. The page and the Pro test both call this, so a test
    pass means the page's own split works.
    """
    model, stems = STEM_CHOICES[choice]
    report = progress or (lambda fraction, desc=None: None)
    target.mkdir(parents=True, exist_ok=True)
    for stale in ALL_STEMS:
        # A 4-stem split after a 6-stem one must not leave the old guitar and piano behind.
        (target / f"{stale}.wav").unlink(missing_ok=True)
    report(0.05, desc="Splitting the song. This can take several minutes.")
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as work:
        # Float output with no clip handling keeps the stems' relative levels exact.
        command = [
            sys.executable, "-m", "demucs", "-n", model, "-d", DEMUCS_DEVICE,
            "--float32", "--clip-mode", "none", "-o", work, "--filename", "{stem}.{ext}",
            str(source),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)

        report(0.9, desc="Writing the WAV files")
        produced = pathlib.Path(work) / model
        written = {}
        instrumental = None
        samplerate = None
        for stem in stems:
            data, samplerate = sf.read(produced / f"{stem}.wav", dtype="float32", always_2d=True)
            if stem != "vocals":
                instrumental = data if instrumental is None else instrumental + data
            path = target / f"{stem}.wav"
            sf.write(path, data, samplerate, subtype="FLOAT")
            written[stem] = str(path)
        # Demucs's "other" is only what remains, so the instrumental is the sum of all non-vocals.
        path = target / "instrumental.wav"
        sf.write(path, instrumental.astype(np.float32), samplerate, subtype="FLOAT")
        written["instrumental"] = str(path)
    return written


def split_stems(audio_path, choice, progress=gr.Progress()):
    if not audio_path:
        raise gr.Error("Add a song first.")
    source = pathlib.Path(audio_path)
    target = STEMS_DIR / safe_name(source.stem)
    try:
        written = split_file(source, target, progress, choice or DEFAULT_CHOICE)
    except RuntimeError as error:
        print(error, flush=True)
        raise gr.Error("The split failed. See the logs folder.") from error
    message = f"Saved to {target}. Drag the WAV files from that folder into your audio software."
    # Players for stems this choice did not produce are hidden.
    players = [gr.update(value=written.get(stem), visible=stem in written) for stem in ALL_STEMS]
    return [*players, message]


# ---- Analysis -------------------------------------------------------------------------------


def estimate_key(chroma):
    """The key whose profile matches the note mix best, e.g. "A major" or "F# minor"."""
    chroma = np.asarray(chroma, dtype=float)
    best, best_score = "unknown", -2.0
    for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
        for shift in range(12):
            score = np.corrcoef(chroma, np.roll(profile, shift))[0, 1]
            if score > best_score:
                best, best_score = f"{NOTES[shift]} {mode}", score
    return best


def db(value):
    return 20 * np.log10(max(float(value), 1e-9))


def analyze_file(source):
    """Tempo, key, length and levels of one audio file, as a dict of plain values."""
    import librosa  # Slow to import, so only when the page needs it.

    audio, samplerate = librosa.load(str(source), sr=None, mono=True)
    if len(audio) < samplerate:
        raise RuntimeError("The file is shorter than one second.")
    tempo, beats = librosa.beat.beat_track(y=audio, sr=samplerate)
    chroma = librosa.feature.chroma_cqt(y=audio, sr=samplerate).mean(axis=1)
    return {
        "length_seconds": round(len(audio) / samplerate, 1),
        "tempo_bpm": round(float(np.atleast_1d(tempo)[0]), 1),
        "beats": int(len(beats)),
        "key": estimate_key(chroma),
        "peak_dbfs": round(db(np.abs(audio).max()), 1),
        "loudness_dbfs": round(db(np.sqrt(np.mean(audio**2))), 1),
        "samplerate": int(samplerate),
    }


def analyze_song(audio_path):
    if not audio_path:
        raise gr.Error("Add a song first.")
    try:
        result = analyze_file(audio_path)
    except (RuntimeError, ValueError, OSError) as error:
        print(error, flush=True)
        raise gr.Error("The analysis failed. See the logs folder.") from error
    minutes, seconds = divmod(result["length_seconds"], 60)
    return (
        f"| | |\n|---|---|\n"
        f"| **Tempo** | {result['tempo_bpm']} BPM ({result['beats']} beats found) |\n"
        f"| **Key** | {result['key']} |\n"
        f"| **Length** | {int(minutes)}:{seconds:04.1f} |\n"
        f"| **Peak level** | {result['peak_dbfs']} dBFS |\n"
        f"| **Average loudness** | {result['loudness_dbfs']} dBFS |\n"
        f"| **Sample rate** | {result['samplerate']} Hz |\n\n"
        "Tempo and key are estimates. A song with a tempo change or a key change gets one overall value."
    )


# ---- Voice profiles -------------------------------------------------------------------------


def load_profiles():
    if PROFILES_FILE.exists():
        return json.loads(PROFILES_FILE.read_text())
    return {}


def save_profiles(profiles):
    PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = PROFILES_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(profiles, indent=2, ensure_ascii=False))
    temporary.replace(PROFILES_FILE)


def describe(age, gender, tone, raspiness, accent, notes):
    parts = [f"{age} {gender} lead vocal", f"{tone} tone", f"{raspiness} voice"]
    if accent.strip():
        parts.append(f"{accent.strip()} accent")
    if notes.strip():
        parts.append(notes.strip())
    return ", ".join(parts)


def save_profile(name, age, gender, tone, raspiness, accent, notes):
    if not name.strip():
        raise gr.Error("Give the voice a name.")
    profiles = load_profiles()
    text = describe(age, gender, tone, raspiness, accent, notes)
    profiles[name.strip()] = {
        "age": age, "gender": gender, "tone": tone, "raspiness": raspiness,
        "accent": accent, "notes": notes, "text": text,
    }
    save_profiles(profiles)
    return text, gr.update(choices=sorted(profiles), value=name.strip())


def use_profile(name):
    return load_profiles().get(name, {}).get("text", "")


def delete_profile(name):
    profiles = load_profiles()
    profiles.pop(name, None)
    save_profiles(profiles)
    return gr.update(choices=sorted(profiles), value=None), ""


# ---- Page -----------------------------------------------------------------------------------


def build():
    with gr.Blocks(title="Stems and Voices", analytics_enabled=False) as page:
        with gr.Tab("Split Stems"):
            gr.Markdown(
                "Drop in a song and press **Split**. You get separate WAV files. **Other** is "
                "everything the model could not name: guitars, keys, synths and strings. The "
                "6-stem choice pulls guitar and piano out of it, with lower quality overall."
            )
            song = gr.Audio(label="Song", type="filepath", sources=["upload"])
            choice = gr.Radio(list(STEM_CHOICES), value=DEFAULT_CHOICE, label="Stems")
            split = gr.Button("Split", variant="primary")
            status = gr.Markdown()
            players = {}
            with gr.Row():
                players["vocals"] = gr.Audio(label="Vocals", interactive=False)
                players["instrumental"] = gr.Audio(label="Instrumental", interactive=False)
            with gr.Row():
                players["drums"] = gr.Audio(label="Drums", interactive=False)
                players["bass"] = gr.Audio(label="Bass", interactive=False)
            with gr.Row():
                players["other"] = gr.Audio(label="Other", interactive=False)
                players["guitar"] = gr.Audio(label="Guitar", interactive=False, visible=False)
                players["piano"] = gr.Audio(label="Piano", interactive=False, visible=False)
            split.click(split_stems, [song, choice], [*(players[s] for s in ALL_STEMS), status])

        with gr.Tab("Analyze"):
            gr.Markdown(
                "Drop in a song to read its tempo, key, length and levels before taking it into "
                "your audio software. Works on a generated song or on a stem."
            )
            to_analyze = gr.Audio(label="Song or stem", type="filepath", sources=["upload"])
            analyze = gr.Button("Analyze", variant="primary")
            analysis = gr.Markdown()
            analyze.click(analyze_song, to_analyze, analysis)

        with gr.Tab("Voice Profiles"):
            gr.Markdown(
                "Describe a singer and save it. Choose a saved voice, copy its description, and "
                "paste it into the **Caption** box on the Music tab. A description guides the "
                "singer's style; it does not reproduce one identical singer across songs."
            )
            with gr.Row():
                with gr.Column():
                    name = gr.Textbox(label="Voice name")
                    age = gr.Dropdown(AGES, value="young adult", label="Age")
                    gender = gr.Dropdown(GENDERS, value="female", label="Voice")
                    tone = gr.Dropdown(TONES, value="warm", label="Tone")
                    raspiness = gr.Dropdown(RASPINESS, value="clean", label="Raspiness")
                    accent = gr.Textbox(label="Accent (optional)")
                    notes = gr.Textbox(label="Anything else (optional)")
                    save = gr.Button("Save voice", variant="primary")
                with gr.Column():
                    saved = gr.Dropdown(sorted(load_profiles()), label="Saved voices")
                    text = gr.Textbox(label="Description to copy", lines=4, buttons=["copy"])
                    delete = gr.Button("Delete this voice")
            save.click(save_profile, [name, age, gender, tone, raspiness, accent, notes], [text, saved])
            saved.change(use_profile, saved, text)
            delete.click(delete_profile, saved, [saved, text])
    return page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    STEMS_DIR.mkdir(parents=True, exist_ok=True)
    build().launch(
        server_name="127.0.0.1",
        server_port=args.port,
        share=False,
        inbrowser=False,
        allowed_paths=[str(STEMS_DIR)],
        theme=gr.themes.Soft(font=["-apple-system", "Helvetica Neue", "sans-serif"],
                             font_mono=["SF Mono", "Menlo", "monospace"]),
    )


if __name__ == "__main__":
    main()
