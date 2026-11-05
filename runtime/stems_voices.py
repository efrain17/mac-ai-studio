#!/usr/bin/env python3
"""Local page with four tools: stem splitting (Demucs), song analysis and chord charts (librosa),
and a library of voice profiles.

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
CHORDS_DIR = STUDIO_HOME / "output" / "chords"
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
SIX_STEMS = list(STEM_CHOICES)[1]
ALL_STEMS = ("vocals", "instrumental", "drums", "bass", "other", "guitar", "piano")
NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
NOTES_FLAT = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
# Keys written with flats, as musicians read them; every other key is written with sharps.
FLAT_KEYS = {"F major", "A# major", "D# major", "G# major", "C# major",
             "D minor", "G minor", "C minor", "F minor", "A# minor"}
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


# ---- Chords ---------------------------------------------------------------------------------

NO_CHORD = "N.C."
CHORD_SAMPLERATE = 22050
HOP = 512


def chord_name(root, quality, flats):
    return (NOTES_FLAT if flats else NOTES)[root] + ("m" if quality == "minor" else "")


def spell_key(key):
    """A key from estimate_key as a musician writes it ("A# major" -> "Bb major"), and whether
    its chords are written with flats."""
    if key not in FLAT_KEYS:
        return key, False
    note, mode = key.split()
    return f"{NOTES_FLAT[NOTES.index(note)]} {mode}", True


def timestamp(seconds):
    tenths = int(round(seconds * 10))
    minutes, tenths = divmod(tenths, 600)
    return f"{minutes}:{tenths // 10:02d}.{tenths % 10}"


def chord_templates():
    """The 24 major and minor triads as unit vectors over the 12 notes, with their names."""
    templates, labels = [], []
    for quality, intervals in (("major", (0, 4, 7)), ("minor", (0, 3, 7))):
        for root in range(12):
            template = np.zeros(12)
            template[[(root + step) % 12 for step in intervals]] = 1
            templates.append(template / np.linalg.norm(template))
            labels.append((root, quality))
    return np.array(templates), labels


def read_chords(audio, samplerate, flats=False):
    """The chords of a mono signal as (start, end, name) in seconds, one entry per change.

    The note mix (chroma) of the harmonic part is averaged between beats, matched against the 24
    major and minor triads, and smoothed with a Viterbi pass so passing notes do not make the
    chord flicker. Quiet beats are "N.C." (no chord). Sevenths and other extended chords come out
    as their major or minor triad.
    """
    import librosa  # Slow to import, so only when the page needs it.

    duration = len(audio) / samplerate
    if not np.any(audio):
        return [(0.0, round(duration, 2), NO_CHORD)]
    harmonic = librosa.effects.harmonic(audio)
    chroma = librosa.feature.chroma_cqt(y=harmonic, sr=samplerate, hop_length=HOP)
    frames = chroma.shape[1]
    _, beats = librosa.beat.beat_track(y=audio, sr=samplerate, hop_length=HOP)
    if len(beats) < 4:
        # No steady beat (a free-time intro, a pad): half-second steps instead.
        beats = np.arange(0, frames, max(1, int(0.5 * samplerate / HOP)))
    bounds = librosa.util.fix_frames(beats, x_min=0, x_max=frames)
    synced = librosa.util.sync(chroma, bounds, aggregate=np.median)
    times = librosa.frames_to_time(bounds, sr=samplerate, hop_length=HOP)
    times[-1] = duration
    rms = librosa.util.fix_length(librosa.feature.rms(y=audio, hop_length=HOP)[0], size=frames)
    loudness = librosa.util.sync(rms[np.newaxis, :], bounds, aggregate=np.mean)[0]
    # Quiet means below -50 dBFS, or 30 dB under the loudest beat: a stem's leftover bleed.
    quiet = (loudness < 10 ** (-50 / 20)) | (loudness < loudness.max() * 10 ** (-30 / 20))

    templates, labels = chord_templates()
    scores = templates @ (synced / (np.linalg.norm(synced, axis=0) + 1e-9))
    likelihood = np.exp(12 * scores)
    no_chord = np.where(quiet, likelihood.max(axis=0) * 50, likelihood.min(axis=0) * 1e-3)
    probabilities = np.vstack([likelihood, no_chord])
    probabilities /= probabilities.sum(axis=0, keepdims=True)
    # A chord usually lasts a few beats, so staying is likelier than changing on every beat.
    transition = librosa.sequence.transition_loop(len(labels) + 1, 0.7)
    path = librosa.sequence.viterbi_discriminative(probabilities, transition)

    segments = []
    for index, state in enumerate(path):
        name = NO_CHORD if state == len(labels) else chord_name(*labels[state], flats)
        start, end = float(times[index]), float(times[index + 1])
        if segments and segments[-1][2] == name:
            segments[-1] = (segments[-1][0], end, name)
        else:
            segments.append((start, end, name))
    return [(round(start, 2), round(end, 2), name) for start, end, name in segments]


def chart_section(title, segments, missing):
    """One instrument's part of the chart: the chords it uses, then each change with its time."""
    total = sum(end - start for start, end, _ in segments) or 1.0
    played = {}
    for start, end, name in segments:
        if name != NO_CHORD:
            played[name] = played.get(name, 0.0) + end - start
    lines = [f"== {title} =="]
    if sum(played.values()) / total < 0.1:
        lines.append(missing)
        return "\n".join(lines)
    lines.append("Chords used, most played first: " + " ".join(sorted(played, key=played.get, reverse=True)))
    lines.append("")
    lines += [f"{timestamp(start)}  {name}" for start, _, name in segments]
    return "\n".join(lines)


def chord_chart(audio_path, split=True, progress=None):
    """A text chord chart of a song: one section for the whole song, or, after a 6-stem split, a
    main progression plus the guitar and keys parts. Saved next to the other finished work.

    Returns the chart and the path of the saved text file.
    """
    import librosa

    report = progress or (lambda fraction, desc=None: None)
    source = pathlib.Path(audio_path)
    report(0.02, desc="Reading the song")
    song, _ = librosa.load(str(source), sr=CHORD_SAMPLERATE, mono=True)
    if len(song) < CHORD_SAMPLERATE:
        raise RuntimeError("The file is shorter than one second.")
    key, flats = spell_key(estimate_key(librosa.feature.chroma_cqt(y=song, sr=CHORD_SAMPLERATE).mean(axis=1)))
    tempo, _ = librosa.beat.beat_track(y=song, sr=CHORD_SAMPLERATE)

    if split:
        stems = split_file(source, STEMS_DIR / safe_name(source.stem), progress, SIX_STEMS)
        parts = {stem: librosa.load(stems[stem], sr=CHORD_SAMPLERATE, mono=True)[0]
                 for stem in ("bass", "guitar", "piano", "other")}
        length = min(len(part) for part in parts.values())
        layers = [
            ("Main progression (bass, guitar, keys and the other instruments; no vocals or drums)",
             sum(part[:length] for part in parts.values()),
             "No chords found: the song has almost nothing but vocals and drums."),
            ("Guitar", parts["guitar"], "No guitar part found: the guitar stem is almost silent."),
            ("Keys (piano)", parts["piano"], "No keyboard part found: the piano stem is almost silent."),
        ]
    else:
        layers = [("Whole song", song, "No chords found: the song is almost silent.")]

    sections = []
    for index, (title, audio, missing) in enumerate(layers):
        report(0.92 + 0.07 * index / len(layers), desc=f"Reading the chords: {title.split(' (')[0]}")
        sections.append(chart_section(title, read_chords(audio, CHORD_SAMPLERATE, flats), missing))

    header = "\n".join([
        f"Chords: {source.stem}",
        f"Key: {key} (estimate)   Tempo: {round(float(np.atleast_1d(tempo)[0]))} BPM (estimate)",
        "C = C major, Am = A minor, N.C. = no chord. Each line is the time the chord starts.",
        "Read automatically: most chords come out right, some do not, and sevenths show as plain",
        "major or minor chords. Check the chart by ear before you rely on it.",
    ])
    chart = header + "\n\n" + "\n\n".join(sections) + "\n"
    CHORDS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHORDS_DIR / f"{safe_name(source.stem)}.txt"
    path.write_text(chart, encoding="utf-8")
    return chart, str(path)


def chords_for_page(audio_path, split, progress=gr.Progress()):
    if not audio_path:
        raise gr.Error("Add a song first.")
    try:
        chart, path = chord_chart(audio_path, split, progress)
    except (RuntimeError, ValueError, OSError) as error:
        print(error, flush=True)
        raise gr.Error("Reading the chords failed. See the logs folder.") from error
    message = f"Saved to {path}."
    if split:
        message += " The stems used are in the stems folder of My Files."
    return chart, path, message


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

        with gr.Tab("Chords"):
            gr.Markdown(
                "Drop in a song and press **Read chords** for a chord chart in letters (C, G, Am, "
                "F), with the time each chord starts. With **Separate guitar and keys** on, the "
                "song is split first and you get three charts: the main progression, the guitar "
                "and the keys. The chart is saved as a text file in the **chords** folder of My "
                "Files. It is an estimate: check it by ear."
            )
            to_read = gr.Audio(label="Song", type="filepath", sources=["upload"])
            separate = gr.Checkbox(value=True, label="Separate guitar and keys first (adds a few minutes)")
            read = gr.Button("Read chords", variant="primary")
            chord_status = gr.Markdown()
            chart = gr.Textbox(label="Chord chart", lines=24, buttons=["copy"])
            chart_file = gr.File(label="Chart as a text file")
            read.click(chords_for_page, [to_read, separate], [chart, chart_file, chord_status])

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
    CHORDS_DIR.mkdir(parents=True, exist_ok=True)
    build().launch(
        server_name="127.0.0.1",
        server_port=args.port,
        share=False,
        inbrowser=False,
        allowed_paths=[str(STEMS_DIR), str(CHORDS_DIR)],
        theme=gr.themes.Soft(font=["-apple-system", "Helvetica Neue", "sans-serif"],
                             font_mono=["SF Mono", "Menlo", "monospace"]),
    )


if __name__ == "__main__":
    main()
