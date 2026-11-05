# Dependencies, versions and sources

Checked on 2026-11-01, and on 2026-11-04 for milestone 4, against official documentation, release pages and source. Homebrew tools follow Homebrew's current releases, and Homebrew verifies what it downloads. Everything else is pinned, and checked against a SHA-256 or a commit.

## System requirements

- Apple Silicon, macOS 15 or newer. Homebrew's ready-made Apple Silicon packages for these tools start at macOS 15; [Homebrew's top support tier](https://docs.brew.sh/Installation) needs the same.
- An administrator account, for the first Homebrew install.
- Internet during installation only.

## Tools from Homebrew

`update.sh` updates these. Versions are what Homebrew offered on 2026-11-01.

| Tool | Homebrew name | Version then | Used for |
| --- | --- | --- | --- |
| Git | [`git`](https://formulae.brew.sh/formula/git) | 2.56.0 | Getting ComfyUI and ACE-Step |
| Python | [`python@3.12`](https://formulae.brew.sh/formula/python@3.12) | 3.12.16 | Every tool's environment |
| uv | [`uv`](https://formulae.brew.sh/formula/uv) | 0.13.6 | Installing ACE-Step's packages |
| FFmpeg | [`ffmpeg@8`](https://formulae.brew.sh/formula/ffmpeg@8) | 8.1.3 | Audio in ACE-Step and Demucs |
| Miniconda | [`miniconda`](https://formulae.brew.sh/cask/miniconda) | 26.9.4 | Installed as a requested base tool; the studio does not use it |
| Stability Matrix | [`stability-matrix`](https://formulae.brew.sh/cask/stability-matrix) | 2.16.5 | Model manager |
| LM Studio | [`lm-studio`](https://formulae.brew.sh/cask/lm-studio) | 0.4.28 | Runs the chat model, serves it to AnythingLLM, has the ComfyUI tools too |
| AnythingLLM | [`anythingllm`](https://formulae.brew.sh/cask/anythingllm) | 1.19.0 | The Chat tab: documents, workspace, agent with the ComfyUI tools |

Homebrew's FFmpeg includes GPL-licensed codecs such as x264 and x265.

## Other tools

These are not in Homebrew in a usable form for this setup, so they keep their pins.

| Tool | Version | Installed by | Source |
| --- | --- | --- | --- |
| Apple Command Line Tools | Current | Homebrew's installer, or the script | Apple |
| Homebrew | Installer commit `8c82c08` | `milestone1.sh` | [docs](https://docs.brew.sh/Installation) |
| ComfyUI | v0.43.0, commit `426f5ee` | `milestone1.sh` | [repo](https://github.com/Comfy-Org/ComfyUI/tree/v0.43.0), [docs](https://docs.comfy.org/installation/manual_install) |
| PyTorch for ComfyUI | 2.15.0 with torchvision 0.29.2 | `locks/comfyui-macos-arm64.lock` | [PyPI](https://pypi.org/project/torch/2.15.0/) |
| ACE-Step 1.5 | Commit `ca1e85f` | `milestone3.sh` | [repo](https://github.com/ace-step/ACE-Step-1.5/tree/ca1e85fe9430179831e6bc6be790c332190a3866) |
| Demucs | 4.1.0 | `locks/stems-voices-macos-arm64.lock` | [repo](https://github.com/adefossez/demucs/tree/v4.1.0) |
| Gradio, for the stems page | 6.30.0 | Same lock | [PyPI](https://pypi.org/project/gradio/6.30.0/) |
| librosa, for the Analyze tool | 1.0.0 | Same lock | [PyPI](https://pypi.org/project/librosa/1.0.0/) |
| PyTorch for stems | 2.10.0 | Same lock | [PyPI](https://pypi.org/project/torch/2.10.0/) |
| Swift compiler, WebKit | From Command Line Tools | Used to build the app | Apple |

ACE-Step's own packages come from its `uv.lock`, including torch 2.10.0, MLX 0.30.6 and Gradio 6.2.0.

Each tool has its own environment, so ComfyUI's torch 2.15 and ACE-Step's torch 2.10 never clash.

## Decisions worth knowing

- **Homebrew's PyTorch is not used,** although it offers [`pytorch`](https://formulae.brew.sh/formula/pytorch) 2.15.0 and `torchvision` 0.29.2. It serves Homebrew's default Python rather than the 3.12 environments here, and ACE-Step and Demucs need torch 2.10.0. An update could also move it away from the version ComfyUI was locked with.
- **FFmpeg uses `ffmpeg@8`, not `ffmpeg`.** The main formula is on 9, which torchcodec 0.10 cannot load.
- **Updating Miniconda and Stability Matrix needs `--greedy-auto-updates`.** Both are marked as updating themselves, so a [plain `brew upgrade`](https://docs.brew.sh/Manpage) can skip them. `update.sh` passes it.
- **Stability Matrix can also update itself,** since it checks for new versions by default. That could happen outside `update.sh`.
- **ACE-Step is pinned to a commit, not its last tag.** Tag `v0.1.8` lacks fixes for garbled XL output on Apple Silicon, MP3 export and `--precision fp32` on Metal.
- **LTX-Video 0.9.8, 2B distilled, is the video model.** It is ungated, runs on ComfyUI's built-in nodes, and has a positive Metal report. Evidence is thin, so the install includes a pixel check and an optional Wan 2.2 fallback.
- **Wan 2.2 TI2V 5B is the Pro video model.** It takes a real negative prompt and guidance, moves at a natural pace, is Apache-2.0, and is the same file as the milestone 2 fallback, so the Pro install adds no new pin. Rejected for Pro on this Mac: Wan 2.2 A14B (two 28 GB files, hours per clip at half precision on Metal), HunyuanVideo 1.5 (no Metal report found), LTX-Video 13B (the same hurried motion as 2B, and its upscaler needs third-party nodes).
- **Rejected for video:** AnimateDiff (pickled motion modules), LTX-2.5 (gated, about 70 GB), any `fp8` or `int8` file.
- **No third-party custom nodes.** The only added node is `custom_nodes/reveal_mask.py`, about 50 lines in this repository. Read it in full before trusting it. It computes masks only, and touches neither files nor the network.
- **Comfy Desktop was not used.** The [official desktop app](https://docs.comfy.org/installation/desktop/macos) exists for Apple Silicon, but it updates itself, is set up by hand, and covers only ComfyUI. A small native wrapper, `app/MacAIStudio.swift`, shows all the tools in one window while keeping versions pinned.
- **`--highvram` is not used.** ComfyUI [forces shared memory on Metal](https://github.com/Comfy-Org/ComfyUI/blob/v0.43.0/comfy/model_management.py#L595), so the flag does nothing there.
- **`--use-split-cross-attention` is set** because of a [reported black-video fix](https://github.com/Comfy-Org/ComfyUI/issues/15818). This is community evidence, not official documentation.
- **`PYTORCH_ENABLE_MPS_FALLBACK` is not set,** so that unsupported operations fail visibly.
- **Demucs weights use the safetensors files from Hugging Face.** The older pickled weights on another host are avoided, and the install fails if they are ever used.
- **Instrumental stem.** Demucs's `other` stem is not an instrumental, so the page adds every non-vocal stem together. It also shows `other` on its own.
- **gpt-oss-120b is the chat model,** as `mlx-community/gpt-oss-120b-MXFP4-Q8` (63 GB, Apache-2.0). Its weights are MXFP4 upstream, so this build loses nothing; the `lmstudio-community` MLX build is the same model stored at 8 bits, 124 GB, which does not fit a 128 GB Mac next to the other models. It calls tools well, which the agent needs. Considered: `Qwen3.6-35B-A3B` (newer, faster, but 3 billion active parameters and weaker on long documents) and `Qwen3.5-122B-A10B` 4-bit (70 GB, less proven for tool calls). The files are downloaded by the installer with checksums and linked into LM Studio's model folder, so LM Studio downloads nothing.
- **The ComfyUI tools are about 300 lines in `runtime/comfy_mcp.py`,** standard library only, speaking the Model Context Protocol over stdin and stdout. No third-party MCP package, and no ComfyUI node: it uses ComfyUI's own HTTP API, the same one `tests/run_workflows.py` uses. Read it in full before trusting it. It renders only the studio's workflows, with a new prompt and seed.
- **The documentation is fetched as git partial clones at fixed commits,** only the named folders, so no file can change under the pin and no images are downloaded. Hugging Face model cards are pinned by commit and checksum in `manifests/milestone4.txt`. AnythingLLM's embedding model (`Xenova/all-MiniLM-L6-v2`) is pinned the same way and placed in its folder, so the import works offline.
- **The Chat tab opens AnythingLLM's own window.** AnythingLLM's [desktop app has no browser-accessible interface](https://docs.anythingllm.com/installation-desktop/overview): its backend on port 3001 answers the API only and returns 404 to a page request. The tab therefore runs `runtime/chat_launcher.py` (standard library, about 150 lines), a status page with an Open AnythingLLM button. Considered: the Docker edition, which has a web page, but needs Docker Desktop and a second copy of the documents; and a chat page of the studio's own on AnythingLLM's API, which would duplicate AnythingLLM's window and need its agent mode rebuilt.
- **AnythingLLM's model choice is made by hand once.** The desktop app keeps the LLM provider in its own environment, which no documented file or API sets, so the installer writes only what it can: the MCP settings file, the embedding model, the workspace (through the REST API, with a key it adds to AnythingLLM's own SQLite database) and the documents.
- **librosa over Essentia** for the Analyze and Chords tools: ISC license, plain wheels for Apple Silicon, same numpy as the stems page. Essentia is AGPL and its Apple Silicon builds are less dependable.
- **Chords by template matching, in about 170 lines of the stems page.** The note mix of each beat (librosa's chroma, on the harmonic part) is compared with the 24 major and minor chords and smoothed with a Viterbi pass, the textbook method. No ComfyUI node exists for this, and a ComfyUI node would mean audio inside an image tool, so it lives on the stems page next to the split it uses. Considered: Chordino (better, but a compiled Vamp plugin plus a host program, outside the pinned Python setup), madmom (no release since 2018; that release fails on current Python) and BTC and other neural chord models (research code with no packaged, versioned release). Template matching gets most chords of a clear pop song right and misses sevenths and fast changes; it adds no download.
- **The assistant answers only from its documents** (AnythingLLM's query mode), and its instructions ask it to end with a `Sources:` line, besides AnythingLLM's own citations under each answer. The Python packages page is read from each environment's own installed package data, so it lists the versions actually installed, offline.
- **Two Demucs models.** `htdemucs_ft` (4 stems) is the default and the better one. `htdemucs_6s` adds guitar and piano at lower quality, from the same account, 55 MB, pinned by commit and checksum like the first. Both are tested offline at install.

## Model licenses

Read the original license before commercial use. This is a summary, not legal advice.

| Model | License | Note |
| --- | --- | --- |
| [SDXL base 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) | OpenRAIL++-M | |
| [RealVisXL V5.0](https://huggingface.co/SG161222/RealVisXL_V5.0) | OpenRAIL++-M | |
| [SDXL VAE fp16 fix](https://huggingface.co/madebyollin/sdxl-vae-fp16-fix) | MIT | |
| [ClayAnimation.Redmond](https://huggingface.co/artificialguybr/ClayAnimationRedmond) | CreativeML OpenRAIL-M | |
| [Graphic Novel Illustration](https://huggingface.co/blink7630/graphic-novel-illustration) | "other" | **No terms found on its page. Confirm with the author** |
| [LTX-Video 0.9.8](https://huggingface.co/Lightricks/LTX-Video) | LTX-Video Open Weights | **Read its terms** |
| [T5 XXL encoder](https://huggingface.co/Comfy-Org/mochi_preview_repackaged) | Apache-2.0 | |
| [Scribble SDXL ControlNet](https://huggingface.co/xinsir/controlnet-scribble-sdxl-1.0) | Apache-2.0 | |
| [MistoLine](https://huggingface.co/TheMistoAI/MistoLine) | OpenRAIL++ | |
| [ACE-Step 1.5 models](https://huggingface.co/ACE-Step) | MIT | |
| [gpt-oss-120b, MXFP4 MLX build](https://huggingface.co/mlx-community/gpt-oss-120b-MXFP4-Q8) | Apache-2.0 | |
| [all-MiniLM-L6-v2 for AnythingLLM](https://huggingface.co/Xenova/all-MiniLM-L6-v2) | Apache-2.0 | |
| [Demucs htdemucs_ft](https://huggingface.co/adefossez/HTDemucs-ft) and [htdemucs_6s](https://huggingface.co/adefossez/HTDemucs-6s) | Unclear | **[Upstream says](https://github.com/adefossez/demucs/commit/829d21890023800713e5dd231c67e43ecc06069b) the code is MIT but the weights' license is not clear** |
| [Wan 2.2](https://huggingface.co/Comfy-Org/Wan-2.2) (Pro flows, optional) | Apache-2.0 | |

## Updating versions

`update.sh` handles the Homebrew tools. Change everything else deliberately, one tool at a time, and test on a spare Mac. Those pins are in `versions.env`, `manifests/` and `locks/`.

To regenerate a lock with [uv](https://docs.astral.sh/uv/) from its `.in` file:

```bash
cd locks && MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile comfyui-v0.43.0.in --python-platform aarch64-apple-darwin --python-version 3.12 --generate-hashes --no-header -o comfyui-macos-arm64.lock
```

The workflow files come from one script, so edit that rather than the JSON:

```bash
python3 tools/build_workflows.py
```
