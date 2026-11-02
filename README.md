# Mac AI Studio

An offline creative studio for Apple Silicon Macs: images, video, music and stems, all opened from one desktop app. It needs no terminal in daily use, no cloud service and no subscription, and nothing leaves the Mac.

Built for an M-series Max MacBook Pro with 128 GB of memory and a 2 TB SSD. It runs on other Apple Silicon Macs on macOS 15 or newer, with slower renders. It refuses to run on Intel Macs.

## Install

Plug in the Mac and open Terminal in this folder. First, check the Mac. This changes nothing:

```bash
./milestone1.sh --check
```

Then run each milestone. Each one is safe to run again, and an interrupted download resumes.

```bash
./milestone1.sh
```

```bash
./milestone2.sh
```

Optional, for sharper and longer video clips that move at a natural pace. It needs milestone 2:

```bash
./milestone2-pro.sh
```

```bash
./milestone3.sh
```

Optional, to test the music studio with a real song instead of a test tone. It installs nothing:

```bash
./milestone3-pro.sh
```

```bash
./milestone4.sh
```

| Script | What it does | Disk | Time at 20 MB/s |
| --- | --- | --- | --- |
| `milestone1.sh` | Homebrew, Git, Python, Miniconda, Stability Matrix, ComfyUI, image models, desktop app | About 25 GB | About 30 min |
| `milestone2.sh` | Text to video, sketch folder to video, sketch-and-fill animation | About 21 GB | About 20 min |
| `milestone2-pro.sh` | Optional. The same three video flows on Wan 2.2: 5-second 1280×704 clips with natural motion, and sketch and fill that ends with the picture coming alive | About 23 GB | About 20 min |
| `milestone3.sh` | Music generation, LoRA training, stem splitter, voice profiles | About 50 GB | About 50 min |
| `milestone3-pro.sh` | Optional. Renders a complete song, splits it into stems and checks both; installs nothing | None | Depends on model loading |
| `milestone4.sh` | Checks everything, prepares the training session; installs nothing | None | Depends on model loading |

Size estimates cover models and tools. Keep at least 50 GB free for milestone 1, 40 GB for milestone 2, 30 GB for the Pro video flows and 80 GB for milestone 3, because the scripts stop below those limits.

The Homebrew installer asks you to press Return and type the Mac's admin password once. The rest runs unattended, and the Mac stays awake while a script runs.

## Daily use

Open **Mac AI Studio** from Applications. Its tabs are **Images & Video**, **Music**, and **Stems & Voices**. Quitting the app stops everything it started. Finished work is saved in `~/MacAIStudio/output`; the **My Files** button opens that folder.

## Updating

Quit Mac AI Studio, then double-click **Update Mac AI Studio.command** in this folder. Or run:

```bash
./update.sh
```

This updates the tools that come from Homebrew: Git, Python 3.12, uv, FFmpeg 8, Miniconda and Stability Matrix. Then it checks that the studio still works. Keep this folder on the Mac, because the update runs from it.

ComfyUI, ACE-Step, Demucs, PyTorch and the models are not updated this way, because Homebrew does not provide them for this setup. A Homebrew update can break the studio, since new releases are not tested with it first. If the check fails, see [After an update](docs/TROUBLESHOOTING.md#after-an-update).

## Guides

- [Manual test steps](docs/MANUAL_TESTS.md): how to test and show each milestone
- [Pro video flows](docs/VIDEO_PRO.md): why the first videos looked rushed, what the Pro flows change, what to expect
- [Pro music test](docs/MUSIC_PRO.md): a real song rendered, split and checked, and what each check means
- [Problems and fixes](docs/TROUBLESHOOTING.md)
- [Dependencies, versions and sources](docs/DEPENDENCIES.md)
- [Training session guide](docs/TRAINING_SESSION.md)

## Sharing a Mac with other work

The studio is built to run on a computer that is already in daily use:

- **Homebrew for the shared tools.** Git, Python 3.12, uv, FFmpeg 8, Miniconda and Stability Matrix come from Homebrew, so they can be updated together. They are shared with anything else on the Mac that uses Homebrew.
- **Private folder for the rest.** ComfyUI, ACE-Step, the Python packages, caches and models stay in `~/MacAIStudio`, with a separate environment per tool.
- **Shell settings untouched.** No script edits `.zshrc` or `.bash_profile`, and the studio does not use conda. If the Mac already has conda, a second one is not added.
- **Other Python setups ignored.** `PYTHONPATH`, active conda environments, user site-packages, and pip or uv settings are all cleared for the studio's processes.
- **Existing Homebrew packages left alone during install.** Installing upgrades nothing. `update.sh` upgrades only the studio's tools by name, plus whatever Homebrew requires them to bring along. An Intel Homebrew in `/usr/local` is ignored.
- **Ports.** Tools use 18188, 17860 and 17870, not the usual 8188 and 7860. If a port is busy, the tool takes the next free one and leaves the other program running.
- **This Mac only.** Every tool listens on `127.0.0.1`.
- **Existing Stability Matrix kept.** Its copy, settings and library are not changed.
- **Backups.** Models and environments are excluded from Time Machine, since they can be downloaded again.

## Remove it

```bash
./uninstall.sh
```

This asks first, and moves your finished work to Documents. Homebrew and everything installed through it stay, since other programs may rely on them.

## What has been tested

These scripts have **not yet been run on Apple Silicon**. They were developed on an Intel Mac, which cannot run them.

| Tested for real | Not tested yet (needs an Apple Silicon Mac) |
| --- | --- |
| Refusal on an unsupported Mac; script syntax and lint | Running any `milestone` script from start to finish |
| Model URLs, sizes and checksums; resume, damage and repair handling | Every Homebrew install and `update.sh`; Stability Matrix and its shared models |
| Port conflicts and clean tool shutdown | PyTorch on Metal; every render time |
| Desktop app build, launch and quit, with stand-in tools | The app showing the real tools; clicking through its dialogs |
| The three image workflows on CPU, with an older ComfyUI (reduced size and steps) | The same workflows on ComfyUI v0.43.0 |
| A real offline Demucs split, and voice profiles, on CPU; the song and stem checks on synthetic audio | Demucs on Metal; ACE-Step (never started), so also the Pro music test |
| Reveal node's masks and frames, calculated without ComfyUI | All six video workflows (compared with v0.43.0 source only) |

Run all four scripts on a spare or rented Apple Silicon Mac before relying on them.

## Known limits

- **Voice design.** No official offline tool found creates reusable *singing* voices from a text description on Apple Silicon. The Voice Profiles page saves a reusable description for the Music tab's caption. It guides the singer's style, but does not reproduce one identical singer across songs.
- **Video takes time.** The Pro flows run a 5-billion-parameter model at 1280×704, with no published speed for ComfyUI on a Mac. Expect a long wait per 5-second clip, and measure it on the first run. See [Pro video flows](docs/VIDEO_PRO.md).
- **LoRA training on a Mac is fragile.** ACE-Step's upstream issues report out-of-memory errors and failed training at half precision. A trained LoRA also has no effect while the MLX DiT option is on. See [Music](docs/TROUBLESHOOTING.md#music).
- **Temperature, Top-K and Top-P** are real controls, but they sit in ACE-Step's generation settings, not its training page.
- **Licenses.** See [model licenses](docs/DEPENDENCIES.md#model-licenses). Check them before commercial use, especially the Demucs weights, the Graphic Novel LoRA and LTX-Video.
