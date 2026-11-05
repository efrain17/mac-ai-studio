# Problems and fixes

Run `./milestone1.sh --check` first. Logs are in `~/MacAIStudio/logs`: one per install run, plus one per tool.

Items marked *(reported)* come from upstream issue trackers and have not been reproduced with these exact versions.

## Installing

| Problem | Fix |
| --- | --- |
| `The studio needs Apple Silicon` | Use an Apple Silicon Mac. The tools have no working Intel build at these versions |
| `macOS ... is too old` | Update to macOS 15 or newer |
| `The Homebrew ... does not work on macOS` | Homebrew is too old for this macOS. Check with the Mac's owner, since other programs may use it. Run `/opt/homebrew/bin/brew update`, then run the script again. If it still fails, reinstall Homebrew from [brew.sh](https://brew.sh) |
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
| The Chat tab stops working after an update | LM Studio or AnythingLLM changed. Open each app once from Applications, then run `./milestone4.sh --test`. If the `lms` tool is gone, run `./milestone4.sh` again |
| A tool upgrade keeps breaking the studio | Hold it with `brew pin <name>` until a fix is available |
| Other programs changed after an update | Homebrew can also upgrade what depends on these tools. Check them with `brew list --versions` |

## Desktop app

| Problem | Fix |
| --- | --- |
| A tab says the tool did not start | The tab shows the reason. Click **Show logs** and open `<tool>.log`; the last lines say more. **Try again** starts the tool once more |
| A tab shows the loading screen for a long time | Nothing is frozen: the clock keeps counting, and the tool answers when its models are loaded. The screen says how long the studio waits before it reports a problem (3 minutes for images and stems, 5 for chat, 15 for music) |
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
| Motion looks rushed, the clip is over too quickly | The first flows use a small distilled model, LTX 2B, whose motion is hurried, and `--test` clips are only 1.4 seconds long. Use the **Pro** folder: 5-second Wan 2.2 clips at a natural pace. In any prompt, say how things move: "slowly", "steady camera" |
| LTX fails on this chip | Run `./milestone2-pro.sh` and use the **Pro** folder, which runs on Wan 2.2. `./milestone2.sh --with-wan` installs the same model with one plain workflow, `D_wan_fallback` |
| A Pro clip takes very long | Expected: a 5-billion-parameter model at 1280×704, with no published speed for ComfyUI on a Mac. For drafts, set **steps** to 20 in **Render video**, or 832×480 in **Video size**. Keep `euler` |
| A Pro render stops at once with `Invalid buffer size` and a size such as 133 GiB | Fixed on 2026-11-02: update the folder with `git pull` and run `./milestone2-pro.sh` again, which installs the corrected workflows. The old ones used 121 frames, a length ComfyUI could not split into small enough pieces. In **Video size**, keep **length** at 125, 93 or 61 |
| A Pro render runs out of memory | Wan 2.2 at full precision has been reported to need over 56 GB on a Mac. Close other apps, or render drafts at 832×480. The target 128 GB Mac has room |
| Vertical bands or oversaturation from the middle of a Pro clip *(reported)* | The Metal color drift, which `--test` catches. Confirm **Render video** uses `euler`, not `uni_pc`. If it persists, note the chip and macOS version and report it |
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
| `milestone3-pro.sh`: the song did not render | Read the newest `milestone3-pro-*.log` in `~/MacAIStudio/logs`. The models load the same way as the Music tab, so if the tab opens, they load; the first load takes minutes |
| `No dropouts` failed with "longest silence" and a few seconds, every other line `PASS` | Fixed on 2026-11-04. The old check also counted the silence after the last note, which ACE-Step adds when a song ends a little before the asked length. Run `git pull`, then `./milestone3-pro.sh --check` to check the same song again without rendering it. The new check names the time of any real gap |
| A Pro check fails on `Song level`, `Dynamics` or `No dropouts` | Listen to the file before blaming the model. The script uses fixed seeds, so run it again: a repeat failure is real. Then see the Metal rows above |

**Security note.** ACE-Step's lock pins Gradio 6.2.0, which has published advisories, fixed in 6.16.0. The studio keeps the upstream pin because changing it is untested. To limit exposure, the page listens only on this Mac, and neither `--share` nor `--enable-api` is used. Do not add them.

## Stems and voices

| Problem | Fix |
| --- | --- |
| `Demucs used weights from outside the verified cache` | Stop. It tried an unverified source. Run `./milestone3.sh` again |
| Split fails on Metal | Set `export DEMUCS_DEVICE=cpu` in `~/MacAIStudio/runtime/services/30-stems-voices.conf`. It is slower |
| Can't find the stems | **My Files**, then `stems/<song name>` |
| Guitar or piano stem is poor, or empty | Expected: the 6-stem model is weaker than the 4-stem one, and its piano stem is the weakest. Keyboards, synths and strings stay in **Other** with either choice; no Demucs model separates them |
| `6 stems` fails but `4 stems` works | The second model is missing. Run `./milestone3.sh` again; it downloads only what is missing |
| Logic Pro level seems very high | The stems are 32-bit float with no limiting, to keep their relative levels. Lower the track fader |
| Voices are not one identical singer | A known limit. A profile is a description, not a voice model |
| `Stems add up to the song` fails in the Pro test | The split ran but did not rebuild the song. Run `DEMUCS_DEVICE=cpu ./milestone3-pro.sh`; if that passes, Metal is the cause, and the fix above applies to the page too |

## Chat assistant

| Problem | Fix |
| --- | --- |
| The Chat tab says it did not start | Open `~/MacAIStudio/logs/40-chat.log`. `AnythingLLM did not answer on port 3001` can mean another program holds the port AnythingLLM needs; quit that program. Otherwise open AnythingLLM once from Applications, then try the tab again |
| `LM Studio opened. Go through its welcome screen` and the script waits | Finish LM Studio's first screen and leave the app open. It then installs its `lms` command, and the script continues |
| `LM Studio does not list the model yet` | Quit and reopen LM Studio; its model list is read at start. The files are linked into `~/.lmstudio/models` |
| Every answer says the model is not set, or the chat fails at once | The one-time choice in AnythingLLM's settings is missing: **AI Providers > LLM > LM Studio**, model `gpt-oss-120b`. See Milestone 4 in [MANUAL_TESTS.md](MANUAL_TESTS.md) |
| The first answer takes minutes | Normal: LM Studio loads 63 GB on the first question, and again after the Chat tab was closed. Later answers start within seconds |
| Answers do not cite the documents, or the workspace is empty | Run `./milestone4.sh --import` with the Chat tab closed. It adds any missing file. `AnythingLLM has not been opened yet` means the Chat tab must be opened once first |
| `@agent` does nothing, or says it has no tools | Open AnythingLLM's **Agent Skills** page once; it reads the tool settings then. The file is `~/Library/Application Support/anythingllm-desktop/storage/plugins/anythingllm_mcp_servers.json` |
| The agent cannot render: `ComfyUI did not start` | The tools start ComfyUI the way the app does. See `~/MacAIStudio/logs/10-images.log`, and the Images section above |
| Out of memory while rendering from the chat | The chat model (63 GB) and a video model are loaded together. Close the Chat tab, which unloads the model, before long video renders, or render images only from the chat |
| The Chat tab shows a status page, not the chat | Expected. AnythingLLM's desktop app has no web page, so the chat is in its own window. Press **Open AnythingLLM** on the tab to bring it forward. Quitting Mac AI Studio quits it |
| The Chat tab says `Not Found` | The studio still has the first version of the Chat tab, which tried to show AnythingLLM inside the app. Quit Mac AI Studio, run `git pull` and `./milestone4.sh` again, then reopen the app |
| A dot on the Chat tab stays orange | `AnythingLLM: starting…` for more than a minute: open AnythingLLM from Applications once. `the chat model is not listed`: open LM Studio and check that the gpt-oss-120b model is in its list. See `~/MacAIStudio/logs/40-chat.log` |
| `The analysis failed` on the Analyze tab | The file is shorter than a second, or not an audio file. See `~/MacAIStudio/logs/30-stems-voices.log` |
| `Reading the chords failed` on the Chords tab | The same causes, or the split failed: see `~/MacAIStudio/logs/30-stems-voices.log`. Try again with **Separate guitar and keys** off, which skips the split |
| Some chords in the chart are wrong | Expected now and then. The reader knows major and minor chords only, so `G7` shows as `G` and `Cmaj7` as `C` or `Em`. Busy mixes, distorted guitars and heavy vocals confuse it most; the guitar and keys charts, made from separated stems, are usually cleaner than the whole song |
| The keys chart says no keyboard part, but the song has one | The 6-stem model's piano stem is weak and often misses synths and organs, which end up in the main progression instead |
| The assistant says the documents do not cover a question it should know | Ask with the words the studio uses (the tab or node name). Answers come only from the documents; if it still fails, run `./milestone4.sh --import` with the Chat tab closed |
| LM Studio asks to update | Allowed; it is the same program the update script updates. Say no while you have a deadline |

The assistant's reading material is in `~/MacAIStudio/knowledge`, one Markdown file per topic. It covers the studio's own guides, ComfyUI, LM Studio, AnythingLLM, Demucs, ACE-Step and the model cards, at the versions installed.
