# Pro music test

What `milestone3-pro.sh` does, why, and what to expect. Written on 2026-11-01, before any run on Apple Silicon. It installs nothing and changes no settings.

## Why a new test

`./milestone3.sh --test` splits an 8-second generated tone and confirms that two pages answer. That proves the tools start. It shows the owner nothing they would call music.

The Pro test produces what the owner actually wants and checks it: a complete song, rendered offline with the Music tab's own settings; its stems, made with the Stems & Voices page's own code; and a report in plain numbers. Everything lands in `My Files`.

## What it does

1. Stops the studio's tools. The Music tab holds its own copy of the models, and a second copy would double the memory.
2. Renders `indie_folk_vocal`: 2 minutes of warm indie folk with a female lead vocal, G major, 90 BPM, with the practice lyrics. Settings are the Music tab's: `acestep-v15-xl-turbo`, the 4B language model on MLX with thinking mode on, 8 diffusion steps (the right number for the turbo model), a fixed seed, 48 kHz WAV.
3. Splits the song with Demucs `htdemucs_ft` at full precision on Metal, through the page's `split_file` function in `runtime/stems_voices.py`. A pass here means the page's split works.
4. Checks the song and the stems, see below.
5. Checks the voice profile library (describe, save, reload, delete) in a temporary folder, so saved voices are never touched.
6. Opens `~/MacAIStudio/output/music_pro_test_samples`: the WAV, a `.json` with the caption, lyrics, settings and render time, and a `stems` folder.

## The checks

| Check | Passes when | Catches |
| --- | --- | --- |
| Song format | Stereo, 44.1 or 48 kHz | A mono or odd file |
| Song length | Within 15% of the asked length | A song cut short or run long |
| Song level | RMS between -30 and -6 dBFS, peak above -6 dBFS | A near-silent or wrongly scaled render |
| No clipping | Under 0.1% of samples at full scale | Distortion |
| Real stereo | Left/right correlation under 0.995 | Mono in a stereo file |
| No dropouts | No silence over 3 seconds | Gaps from a failed decode |
| Dynamics | Second-by-second level varies by 3 dB or more | A loop or drone instead of a song |
| Full bandwidth | Energy above 8 kHz at least -40 dB of the total | A muffled render |
| Stem files, Stems match | Four stereo WAVs with equal rate and length | A failed or partial split |
| Stems add up to the song | Song minus (vocals + instrumental) at least 12 dB below the song | A split that did not rebuild the input |
| Vocals were found | Vocal stem at least -20 dB relative to the song | Vocals lost in the instrumental |
| Drums and bass are separate | Correlation under 0.9 | Stems that are copies of each other |

The thresholds are deliberately lenient. They catch the failures that have been seen or are plausible on Metal, not matters of taste. The numbers printed next to each `PASS` are the ones worth comparing between runs.

The checks were tried on synthetic audio on a Linux machine: a clean signal passes every check, and a mono, clipped signal with a 4-second gap fails the right ones. They have not run on a real ACE-Step render yet.

## Judging the quality

```bash
./milestone3-pro.sh --samples
```

Renders three full songs with fixed seeds, so a second run gives the same songs:

| Song | Style | Length |
| --- | --- | --- |
| `indie_folk_vocal` | Warm indie folk, female vocal | 2:00 |
| `cinematic_score` | Orchestral trailer cue, instrumental | 1:30 |
| `upbeat_pop_vocal` | Modern pop, male vocal | 2:10 |

The two vocal songs are split into stems. The captions and lyrics are in `tests/generate_song.py` and in each song's `.json`, ready to paste into the Music tab for a live comparison.

## What to expect

- **Time is unmeasured.** ACE-Step quotes seconds per song on NVIDIA cards and nothing for Apple Silicon. Loading the models takes minutes (the Music tab allows 15). Write the render times from the `.json` files down.
- **Memory.** The XL model runs at full precision on Metal, as the Music tab does. The target 128 GB Mac has room; the script stops the Music tab first so there is only one copy.
- **The same known limits as the Music tab** apply: see [Music](TROUBLESHOOTING.md#music). The test changes no model, no setting and no file of ACE-Step's.
- **Taste is not tested.** A song can pass every check and still not be the song the owner wanted. The samples exist for listening.

## Files

- `milestone3-pro.sh`: the test, `--samples`, `--verify`
- `tests/generate_song.py`: renders songs with ACE-Step's Python API; holds the three song definitions
- `tests/check_music.py`: splits through the page's code and runs the checks
- `tests/check_voice_profiles.py`: the voice library check
- `runtime/stems_voices.py`: the page, with its split now in a `split_file` function the test shares
