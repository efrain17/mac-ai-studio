# Problems and fixes

Run `./milestone1.sh --check` first. Logs are in `~/MacAIStudio/logs`: one per install run, plus one per tool.

Items marked *(reported)* come from upstream issue trackers and have not been reproduced with these exact versions.

## Installing

| Problem | Fix |
| --- | --- |
| `The studio needs Apple Silicon` | Use an Apple Silicon Mac. The tools have no working Intel build at these versions |
| `macOS ... is too old` | Update to macOS 15 or newer |
| `Homebrew could not install ...` | Run `brew doctor`, follow what it says, and run the script again |
| Stability Matrix is blocked on first open | Go to **System Settings > Privacy & Security** and choose **Open Anyway** |
| `This Mac already has conda` | Not an error. The studio does not use conda, so the existing one is kept |
| `This Terminal runs under Rosetta` | Open Terminal's Get Info in Finder, turn off **Open using Rosetta**, then reopen it |
| `Homebrew needs an administrator account` | Log in as an admin, or have one run milestone 1 |
| The script pauses at the Command Line Tools window | Click **Install**. The script continues when it finishes |
| `Need at least N GB free` | Free up space. The limit includes working room |
| `Download failed` | Check the connection and run the same script again. It resumes |
| `Checksum mismatch` | The bad file was already removed. Run the script again. If it repeats, the source may have changed: do not bypass the check |
| Hash error from pip or uv | A package no longer matches the lock. Do not remove `--require-hashes`. Regenerate the lock deliberately ([how](DEPENDENCIES.md#updating-versions)) |
| `Stability Matrix already has a library` | Not an error. Your library is kept. To share studio models, add `~/MacAIStudio/models` in its settings |

## After an update

`update.sh` updates Homebrew tools to their newest releases, which have not been tested with the studio. If its check fails:

1. Run the milestone scripts again, in order. They rebuild what the update broke, and they skip models that are still fine.
2. Run `--test` on the affected milestone.
3. If it still fails, read the tool's log. A Python or FFmpeg release is the most likely cause.

| Problem | Fix |
| --- | --- |
| Music fails after an update, mentioning FFmpeg | `ffmpeg@8` changed. Check `~/MacAIStudio/logs/20-music.log` |
| Every tool fails with a Python error | `python@3.12` changed. Run the milestone scripts again to rebuild the environments |
| A tool upgrade keeps breaking the studio | Hold it with `brew pin <name>` until a fix is available |
| Other programs changed after an update | Homebrew can also upgrade what depends on these tools. Check them with `brew list --versions` |

## Desktop app

| Problem | Fix |
| --- | --- |
| A tab says the tool did not start | Open `~/MacAIStudio/logs/<tool>.log`. The last lines give the reason |
| "Not installed correctly" on launch | Run `./milestone1.sh` again |
| The app was force-quit and a tool still runs | Run `~/MacAIStudio/runtime/services.sh stop-all` |
| The app does not appear after moving the Mac's user folder | Run `./milestone1.sh` again to rebuild it |

The port can differ from the usual one if something else is using it. That is intended. Check it with:

```bash
~/MacAIStudio/runtime/services.sh status
```

## Images

| Problem | Fix |
| --- | --- |
| Solid black or gray image | The check fails on purpose. Confirm the **VAE** box says `sdxl_vae_fp16_fix.safetensors` |
| Red box around a model box | Run `./milestone1.sh --verify`, then press `R` on the canvas to refresh the model list |
| Style looks weak | Keep the trigger words in the prompt: `graphic novel illustration` or `Clay Animation, Clay` |
| Workflow folder is empty | Run `./milestone1.sh` again; it copies the workflows |

## Video

Metal failures are often silent. A video can finish with no error and still be wrong.

| Problem | Likely cause and fix |
| --- | --- |
| Black video *(reported)* | The launcher already sets `--use-split-cross-attention`, the reported fix. Check that `~/MacAIStudio/logs/10-images.log` shows that it started with this setting. If it persists, install the fallback model |
| Color grows and turns to noise across frames *(reported)* | This is Wan with `uni_pc`. Use `euler`, which the fallback workflow already sets |
| LTX fails on this chip | Run `./milestone2.sh --with-wan`, then use `D_wan_fallback` |
| An operation is "not implemented for MPS" | Add `export PYTORCH_ENABLE_MPS_FALLBACK=1` to `~/MacAIStudio/runtime/services/10-images.conf`. It is off so that such failures are visible, and it makes that operation slower |
| Workflow rejected, mentioning `format.codec` | Those input names were read from source, not run. Reopen the workflow from the list; if it persists, set the **Save video** box again by hand and save |
| Sketch folder order looks random | ComfyUI's folder node does not sort. Each video is still correct |
| Sketch folder runs out of memory | The folder node holds all intermediates. Split large folders into batches |
| Folder is missing from the **Sketch folder** box | The folder must be inside `~/MacAIStudio/input`. Press `R` to refresh |
| Sketch is ignored | Use dark lines on white paper. The workflow inverts it for the guide model |
| Hands appear in `A` or `B` | LTX runs at cfg 1, so negative prompts have no effect there. Describe the scene without any mention of drawing. `C` cannot show hands: no model paints its frames |
| Mac gets very hot, renders slow down *(reported)* | Expected on long batches. Use a hard surface and allow breaks |
| Do not use | `fp8`, `nvfp4` and `int8` model files *(reported)* to fail on Metal |

## Music

| Problem | Likely cause and fix |
| --- | --- |
| Music tab takes minutes to open | Normal on first start. The limit is 15 minutes |
| Garbled XL output *(reported)* | Fixed at the pinned commit, which is why it is newer than the last tag. Do not "update" to `v0.1.8` |
| Repetitive XL output *(reported)* | Turn off DCW and set **LM Codes Strength** to 0 |
| Memory climbs and generation stalls *(reported)* | Leave **Auto-score** off with MLX and XL |
| Crash or hang at 80–97% *(reported)* | Restart the app. If it repeats, turn off MLX DiT |
| Out of memory *(reported)* | Quit other apps. Avoid `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0`, which ACE-Step's issues warn may cause a system failure |
| Vocal gender ignores the caption *(reported)* | Generate again with a clearer caption, such as "female lead vocal" |
| A trained LoRA has no effect *(reported)* | Turn off **MLX DiT**. It is slower and uses more memory |
| Training stops or the loss shows NaN *(reported)* | Half precision can fail on Metal. The reported workaround is a terminal command, so do this for the owner: preprocess at full precision, then point the Train tab at the result. Restart the app between stages |
| `cannot decode audio through FFmpeg` during install | Keep `ffmpeg@8`. torchcodec 0.10 cannot load FFmpeg 9, which is what the plain `ffmpeg` formula installs |

**Security note.** ACE-Step's lock pins Gradio 6.2.0, which has published advisories, fixed in 6.16.0. The studio keeps the upstream pin because changing it is untested. To limit exposure, the page listens only on this Mac, and neither `--share` nor `--enable-api` is used. Do not add them.

## Stems and voices

| Problem | Fix |
| --- | --- |
| `Demucs used weights from outside the verified cache` | Stop. It tried an unverified source. Run `./milestone3.sh` again |
| Split fails on Metal | Set `export DEMUCS_DEVICE=cpu` in `~/MacAIStudio/runtime/services/30-stems-voices.conf`. It is slower |
| Can't find the stems | **My Files**, then `stems/<song name>` |
| Logic Pro level seems very high | The stems are 32-bit float with no limiting, to keep their relative levels. Lower the track fader |
| Voices are not one identical singer | A known limit. A profile is a description, not a voice model |
