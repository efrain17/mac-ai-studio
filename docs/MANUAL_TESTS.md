# Manual test steps

Use these to confirm each milestone and to show it working. Use only placeholder text and images, such as those in [practice_prompts.md](../assets/practice_prompts.md).

Render times are not listed because they have not been measured on the target Mac yet. Note them during your first run. They are the numbers to quote.

## Before every test

1. Close other heavy apps.
2. Plug in the Mac.
3. Open **Mac AI Studio** from Applications.

To check that it works offline, turn Wi-Fi off after the install. Everything below should still work.

## Milestone 1: images

**Automatic check**

```bash
./milestone1.sh --test
```

It renders three images at full size. Each line should say `PASS`, and the samples folder opens at the end.

**By hand**

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Open the app, wait for **Images & Video** | The ComfyUI editor appears in the app's own window, with no browser or Terminal. If a Templates window appears, close it |
| 2 | Open the Workflows panel (press `W` on the canvas) and the **Mac AI Studio** folder | The workflows are listed |
| 3 | Open `01_gritty_graphic_novel`, press **Run** | An inked, high-contrast comic image |
| 4 | Do the same with `02_photorealistic_human` | A photo-like person |
| 5 | Do the same with `03_claymation` | A clay figure on a model set |
| 6 | Change the text in the **Prompt** box, keeping the style words, and press **Run** | A new image in the same style |
| 7 | Press **My Files** | The folder with the images opens |
| 8 | Press **Models** | Stability Matrix opens. Finish its first-run screens and confirm its model list shows the SDXL files |

**Pass:** one image for each of the three styles, and step 8 shows the shared models.

## Milestone 2: video

**Automatic check**

```bash
./milestone2.sh --test
```

It renders short, small videos and checks them for black frames and growing color corruption. These are the silent failures known on Metal. A render that "finishes" can still be bad, so read both the render and check results.

**By hand**, in the **Mac AI Studio** workflow folder:

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Open `A_text_to_video`, press **Run** | A moving 4-second clip of the prompt |
| 2 | Add sketches to `~/MacAIStudio/input/sketches` | Two examples are already there |
| 3 | Open `B_sketch_folder_to_video`, press **Run** | **One video per sketch**, each starting from a picture that follows that sketch's lines |
| 4 | Open `C_sketch_and_fill`, press **Run** | Blank paper, lines appear, color fills in |
| 5 | Watch video 4 from start to end, at full size | **No hands, pencils or drawing tools at any point** |

To use a lineart model in place of scribble, choose `mistoLine_fp16.safetensors` in the **Sketch guide** box.

For sketch and fill with your own drawing, use dark lines on white paper, and choose it in the **Your sketch** box.

**Pass:** the folder batch makes one video per sketch, the style prompts give valid video, and sketch and fill shows no tools.

## Milestone 3: music and stems

**Automatic check**

```bash
./milestone3.sh --test
```

It splits a generated tone offline, and confirms that both pages answer.

**By hand**

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Open the **Music** tab. The first start can take several minutes while models load | ACE-Step's page, with the model already initialized |
| 2 | Paste the lyrics and style from the practice prompts, then generate | A song with vocals plays in the page |
| 3 | Open **Generation > Advanced > LM Parameters** | **LM Temperature**, **LM Top-K** and **LM Top-P** are there |
| 4 | Generate the same song with very different Temperature values | The results audibly differ |
| 5 | Open the LoRA training page | Dataset and training settings are shown. See the note below |
| 6 | Download the song, open **Stems & Voices > Split Stems**, drop it in, press **Split** | Vocal, Drums, Bass and Instrumental players appear |
| 7 | Press **My Files**, go to `stems`, and drag the WAV files into Logic Pro | They load as separate 32-bit float tracks and play in sync |
| 8 | Open **Voice Profiles**, make and save a voice | It stays in the list after you quit and reopen the app |
| 9 | Copy its description into the Music tab's caption, then generate | The vocal follows the description's style |

**LoRA note:** run a real training job on the Mac before promising it. If it fails, see [Music](TROUBLESHOOTING.md#music). Turn off MLX DiT when using a trained LoRA.

**Pass:** a test track generated from provided lyrics, then split into vocal and instrument WAV stems.

## Milestone 4: live session

```bash
./milestone4.sh
```

Every line should say `PASS`. Then follow [TRAINING_SESSION.md](TRAINING_SESSION.md).

**Pass:** the session is recorded, the video file is delivered, and the owner runs one custom prompt alone while you are still online.

## Updating

Test this on a spare Mac first, since new versions may break something.

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Quit Mac AI Studio, then double-click **Update Mac AI Studio.command** | A Terminal window lists each tool being checked |
| 2 | Wait for the end | Every check says `PASS`, then `All tools are up to date` |
| 3 | Open Mac AI Studio and run one image | It renders as before |

**Pass:** the tools update with one double-click and the studio still works.

## How to show it

A short, reliable order. Render the slow items before the meeting, and start one fresh render live.

1. Quit everything, then open **Mac AI Studio** from the Dock, to show that it is one app.
2. Turn Wi-Fi off, to show that it is offline.
3. **Images:** show the three samples, then run one fresh prompt.
4. **Video:** play the sketch-and-fill clip first, since it is the most striking, then show the folder batch.
5. **Music:** play a generated song.
6. **Stems:** split it, then drag the stems into Logic Pro.
7. Press **My Files**, to show that everything is ordinary files on the Mac.
