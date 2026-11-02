# Pro video flows

Why the first videos looked rushed, what `milestone2-pro.sh` changes, and what to expect from it. Written on 2026-11-01, before any run on Apple Silicon.

## What the owner saw

`./milestone2.sh --test` renders deliberately small clips: 512×320, 33 frames, about 1.4 seconds each. They exist to catch black frames and color corruption, the silent failures Metal can produce. They were never meant to show quality. The full workflows in the app render 1216×704 for 4 seconds.

Two things make even the full-size clips look rushed:

- **The model.** Milestone 2 uses LTX-Video 2B distilled: a 6 GB model that renders in eight steps. It is quick, but its motion is hurried, and because it runs at guidance 1 the negative prompt has no effect, so nothing steers it away from faults.
- **The length.** Four seconds, with motion at full speed from the first frame.

## What the Pro flows change

| | Milestone 2 | Milestone 2 Pro |
| --- | --- | --- |
| Model | LTX-Video 2B distilled, 6 GB | Wan 2.2 TI2V 5B at full precision, 10 GB, plus its 11 GB text encoder |
| Clip | 1216×704, 97 frames, 4 s at 24 fps | 1280×704, 125 frames, 5.2 s at 24 fps |
| Sampling | 8 distilled steps, guidance 1, no negative prompt | 25 euler steps, guidance 5, Wan's own negative prompt |
| Prompt | One line | A shot description: subject, setting, light, camera move, pace |
| Sketch and fill | 4 s of drawing and filling | 7 s of drawing and filling, a short hold, then 5 s in which the finished picture comes alive, in one file |
| In the app | **Mac AI Studio** folder | **Mac AI Studio > Pro** folder, each workflow with a **Read me** note on its canvas |

The three flows keep their jobs: `A` text to video, `B` one clip per sketch in a folder, `C` sketch and fill. The picture step in `B` and `C`, SDXL guided by the scribble ControlNet, is unchanged apart from the size. Milestone 2 stays installed and untouched, so the owner can compare.

## Why Wan 2.2 5B

- It is the model this project already trusts as the fallback: same pinned files, same checksums, so the Pro install adds no new download source.
- It takes a negative prompt and classifier-free guidance, which the distilled LTX cannot.
- Its motion is paced naturally, which is the complaint being fixed.
- It is one model for text to video and image to video, so all three flows share the same files.
- Its license is Apache-2.0, with no extra terms to read before commercial use.
- It runs on ComfyUI's built-in nodes. The project adds no third-party nodes.

Rejected for this Mac: Wan 2.2 A14B (two 28 GB files; at half precision on Metal, hours per clip), HunyuanVideo 1.5 (no report of it running on Metal was found), LTX-Video 13B (the same hurried motion, and its two-stage upscaler needs third-party nodes). Any `fp8`, `nvfp4` or `int8` file stays out, as before: they are reported to fail on Metal.

## What to expect

- **Render time is unmeasured.** No published number exists for this model in ComfyUI on a Mac. The nearest: an 8-bit MLX build of the same model renders 720p × 41 frames × 20 steps in about 15 minutes on a 64 GB Apple Silicon Mac ([model card](https://huggingface.co/Anes1032/Wan2.2-TI2V-5B-mlx-q8)). ComfyUI runs on PyTorch, not MLX, at full precision, and a Pro clip has three times the frames, so plan for well over that per clip until it is measured. `./milestone2-pro.sh --samples` renders four clips and can take hours. Write the times down; they are the numbers to quote.
- **Memory.** A full-precision 5B text-to-video run peaked at 56 GB on a 64 GB MacBook Pro ([Modelfit](https://modelfit.io/video/wan-2-2-5b/)). The target 128 GB Mac has room; a 64 GB Mac should render drafts at 832×480.
- **The known Metal fault.** Color that drifts or bands from the middle of a clip is reported for Wan on Apple Silicon. The flows use `euler`, which avoids the `uni_pc` case, and `--test` checks every clip for it.
- **Quality ceiling.** 5B is Wan's middle tier. It is a clear step up from LTX 2B in motion and detail, not the best video model that exists. The A14B tier is better and impractical on this Mac today ([Modelfit on Wan 2.2 on Mac](https://modelfit.io/blog/wan-2-2-on-mac/)).
- **No sound.** Like all the video flows, the Pro clips are silent. Music comes from milestone 3 and is joined to a clip in a video editor.

## Found on the first run (2026-11-02)

The first Pro render on the owner's Mac stopped after 37 seconds with `Invalid buffer size: 133.07 GiB`. The cause was the clip length, not the Mac. ComfyUI splits Wan's attention into 2, 4, up to 64 pieces when memory is short, but only when the pieces divide the clip's token count evenly. Otherwise it silently tries the whole thing at once. 121 frames at 1280×704 is 27,280 tokens, which 32 and 64 do not divide, so on a busy Mac it asked Metal for one 133 GiB block.

The workflows now use 125 frames: 28,160 tokens, 64 × 440, so the worst case is 64 pieces of about 2 GiB each. `tools/build_workflows.py` refuses to build a Wan workflow whose token count is not a multiple of 64. The milestone 2 fallback, `D_wan_fallback`, had the same length and is fixed too. Run `./milestone2-pro.sh` again to install the corrected workflows; it downloads nothing new.

That render did load the models and start sampling, so the install itself works on the Mac.

## Install and test

Needs milestones 1 and 2.

```bash
./milestone2-pro.sh
```

```bash
./milestone2-pro.sh --test
```

```bash
./milestone2-pro.sh --samples
```

Then quit and reopen **Mac AI Studio**, press `W` on the canvas and open **Mac AI Studio > Pro**. The manual steps are in [MANUAL_TESTS.md](MANUAL_TESTS.md#milestone-2-pro-video-on-wan-22).

## Writing a prompt for Wan

Describe a shot, not a keyword list: what is in frame, where, in what light, how the camera moves, and how fast things move. Words such as "slowly", "gently" and "steady camera" set the pace. The **Avoid** box already holds Wan's own list; add anything else that should not appear. The prompts in [practice_prompts.md](../assets/practice_prompts.md) are a starting point.

## Files

- `milestone2-pro.sh`: install, `--verify`, `--test`, `--samples`
- `manifests/milestone2-pro.txt`: the three Wan 2.2 files, pinned by commit and checksum (formerly `milestone2-wan.txt`)
- `workflows/video-pro/`: the three workflows, generated by `tools/build_workflows.py` like all the others
- `tests/run_workflows.py`: `--size` and `--frames` for preview renders
