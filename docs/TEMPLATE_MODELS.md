# Models for ComfyUI's templates

ComfyUI comes with hundreds of ready-made templates. Most need model files the studio does not install. `get-models.sh` downloads them into the right folders for you.

## 1. Find the template's name

In the **Images & Video (ComfyUI)** tab, open the **Templates** window (the **Templates** button in the left bar). The name to use is the **title on the card**, for example **Z-Image-Turbo: Text to Image**.

After you open a template, its tab at the top shows a short name instead, such as `image_z_image_turbo` or `utility-gan_upscaler`. That name works too.

You can also list every template, with how many model files it needs:

```bash
./get-models.sh --list
```

Add a word to shorten the list:

```bash
./get-models.sh --list flux
```

Templates marked **online service** use a paid cloud service and cannot run offline in the studio. Those marked **no model files needed** work as they are.

## 2. See what it needs

Open Terminal in the installer folder. This shows each file, its size and its folder, and downloads nothing:

```bash
./get-models.sh --check "Z-Image-Turbo: Text to Image"
```

Part of the title is enough, as long as only one template matches. If several match, the script lists them; copy one title exactly. A workflow you saved in the Workflows panel works too, by its name.

## 3. Download

```bash
./get-models.sh "Z-Image-Turbo: Text to Image"
```

It shows the same list, the total size and the free space, and asks. Type `yes`. Then, in ComfyUI, press `R` (or reopen the Images & Video tab) and open the template.

- **Files already there are skipped**, so running it again is safe. An interrupted download resumes.
- **Each file is checked** against the checksum Hugging Face reports for it. A damaged file is deleted, not kept.
- **Only Hugging Face is used.** A file from anywhere else is skipped and named, so you can decide yourself.
- **The Mac stays awake** while it downloads, and the run is logged in `~/MacAIStudio/logs`.

## Where the files go

| Kind of file | Folder |
| --- | --- |
| Checkpoints, LoRAs, VAEs, ControlNets, diffusion models, text encoders | `~/MacAIStudio/models`, shared with Stability Matrix |
| Everything else (upscalers, CLIP vision, audio encoders …) | `~/MacAIStudio/ComfyUI/models` |

## Good to know

- **Size.** Image templates often need 10 to 35 GB, video templates 20 to 60 GB. The script refuses to start without the space plus 5 GB to spare.
- **Gated models.** A few models (some Flux versions, for example) need a Hugging Face account and accepted terms. The script says so and skips them; download those from their Hugging Face page and paste them into the folder shown.
- **Not checked by the installer.** These files are yours: `--verify` and the updates do not check or change them. Delete them in Finder to free space.
- **Templates are newer than the studio's tests.** A template can need a node or setting that does not work on a Mac yet. If it fails after the models are in place, see Images in [Problems and fixes](TROUBLESHOOTING.md#images).
