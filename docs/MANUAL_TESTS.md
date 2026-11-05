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
| 1 | Open the app, wait for **Images & Video (ComfyUI)** | A loading screen shows first: two turning rings, a clock counting up and a hint that changes every few seconds. Then the ComfyUI editor appears in the app's own window, with no browser or Terminal. If a Templates window appears, close it |
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

## Milestone 2 Pro: video on Wan 2.2

**Automatic check**

```bash
./milestone2-pro.sh --test
```

It renders each Pro workflow at preview size (832×480, 2 seconds) and runs the same checks for black frames and growing color corruption. These previews exist for the checks, not for judging the look. To judge the look, render full-size samples. This can take hours, and the Mac stays awake:

```bash
./milestone2-pro.sh --samples
```

**By hand**, in the **Mac AI Studio > Pro** workflow folder. Each workflow has a **Read me** note on its canvas.

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Open `A_text_to_video_pro`, press **Run** | A 5-second 1280×704 clip that moves at a natural pace |
| 2 | Open `B_sketch_folder_to_video_pro`, press **Run** | **One 5-second clip per sketch**, each starting from a picture that follows that sketch's lines, then moving gently |
| 3 | Open `C_sketch_and_fill_pro`, press **Run** | Blank paper, lines appear, color fills in and holds for a moment, then the finished picture comes alive. About 12 seconds |
| 4 | Watch video 3 from start to end, at full size | **No hands, pencils or drawing tools during the drawing part** |
| 5 | Change the **Prompt** in `A`, keeping words such as "slowly" and "steady camera", and press **Run** | A new clip at the same calm pace |

Note the render time of each clip. They are the numbers to quote.

**Pass:** the three Pro clips play at a natural pace, with no black frames and no color drift, and the join in video 3 is seamless.

## Milestone 3: music and stems

**Automatic check**

```bash
./milestone3.sh --test
```

It splits a generated tone offline, and confirms that both pages answer.

**By hand**

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Open the **Music (ACE-Step)** tab. The first start can take several minutes while models load | ACE-Step's page, with the model already initialized |
| 2 | Paste the lyrics and style from the practice prompts, then generate | A song with vocals plays in the page |
| 3 | At the top of the page, above the **Generation** tab, open **Settings**, then **LM Generation** | **LM Temperature** (default 0.85), **LM CFG Scale**, **LM Top-K** and **LM Top-P** are there |
| 4 | Generate the same song with very different Temperature values | The results audibly differ |
| 5 | Open the LoRA training page | Dataset and training settings are shown. See the note below |
| 6 | Download the song, open **Stems & Voices (Demucs) > Split Stems**, drop it in, press **Split** | Vocals, Instrumental, Drums, Bass and Other players appear |
| 6b | Choose **6 stems**, press **Split** again | Guitar and Piano players appear as well. Expect the piano stem to be weak: that is the model's limit |
| 7 | Press **My Files**, go to `stems`, and drag the WAV files into Logic Pro | They load as separate 32-bit float tracks and play in sync |
| 8 | Open **Voice Profiles**, make and save a voice | It stays in the list after you quit and reopen the app |
| 9 | Copy its description into the Music tab's caption, then generate | The vocal follows the description's style |

**LoRA note:** run a real training job on the Mac before promising it. If it fails, see [Music](TROUBLESHOOTING.md#music). Turn off MLX DiT when using a trained LoRA.

**Pass:** a test track generated from provided lyrics, then split into vocal and instrument WAV stems.

## Milestone 3 Pro: a real song, split and checked

```bash
./milestone3-pro.sh
```

Quit Mac AI Studio first; the script stops the tools anyway, because the Music tab holds its own copy of the models. It renders a 2-minute indie folk song with vocals using the Music tab's own settings, splits it with the Stems & Voices page's own code, and checks both. Every line should say `PASS`. The folder opens at the end with `indie_folk_vocal.wav`, its `.json` (caption, lyrics, settings and render time) and a `stems` folder.

| Check | What it means |
| --- | --- |
| Song format, Song length, Song level, No clipping | Stereo at 48 kHz, within 15% of the asked length, at a normal level, without distortion |
| Real stereo, No dropouts, Music fills the file, Dynamics, Full bandwidth | Not mono in disguise, no silent gaps inside the song, music for most of the file, quieter and louder passages, highs present |
| Stem vocals, drums, bass, other, instrumental; Stems match | Five WAV files of the same length and rate |
| Stems add up to the song, Vocals were found, Drums and bass are separate | The split is real: the stems rebuild the song, and the voice landed in the vocal stem |
| Voice profiles | Describe, save, reload and delete work, in a temporary folder |

To judge the sound rather than the numbers:

```bash
./milestone3-pro.sh --samples
```

Three full songs: indie folk with vocals, a cinematic score, upbeat pop with vocals. Listen to each from start to end at full volume, and open the stems of the two vocal songs in Logic Pro. The render times are in the `.json` files; they are the numbers to quote. Each `.json` also holds the caption and lyrics, ready to paste into the Music tab.

**Pass:** every line says `PASS`, each song sounds like a finished track, and the vocal stems are clean voices.

## Milestone 4: chat assistant

**Automatic check**

```bash
./milestone4.sh --test
```

It checks the assistant's ComfyUI tools, the Analyze tool and the Chords tool against stand-ins, starts the Chat tab, asks the chat model for one word (the first answer loads 63 GB and can take up to 15 minutes), and confirms the workspace holds the documents. Each line should say `PASS`.

**First open, once**

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Open the app, open the **Chat (AnythingLLM)** tab. The first start takes a minute | The loading screen shows a clock while LM Studio and AnythingLLM open, then AnythingLLM's page appears inside the app |
| 2 | Open its settings (the wrench at the bottom left), then **AI Providers > LLM**. Choose **LM Studio**. The base URL is `http://127.0.0.1:1234/v1`; press the refresh button next to the model list and pick the model whose name contains `gpt-oss-120b`. Save | The provider is saved. AnythingLLM keeps this choice outside any file the installer may edit, so it is made once by hand |
| 3 | Go back to the workspaces and open **Studio Help** | A workspace with the studio's documents attached (the paperclip count is above 30) |

**By hand**

| # | Do this | Expect |
| --- | --- | --- |
| 1 | In **Studio Help**, ask: *How do I split a song into stems?* | An answer that names the **Stems & Voices (Demucs)** tab and the Split button, with short steps, a `Sources:` line at the end, and citations under it. The first answer takes a minute or two while the model loads |
| 2 | Ask: *Where are my finished files?* | `~/MacAIStudio/output` and the **My Files** button |
| 3 | Ask: *What does the cfg setting in a KSampler do?* | An explanation drawn from the ComfyUI documentation |
| 3b | Ask: *Which version of PyTorch does ComfyUI use?* and then *What does softness do on the Progressive Reveal Mask node?* | The version from the Python packages page, and the answer from the node's own guide, each with its source |
| 3c | Ask something the documents do not cover, such as *What is the capital of France?* | A short reply that the studio's documents do not cover it. The workspace answers only from the documents |
| 4 | Type `@agent` followed by: *Make a claymation image of a lighthouse in a storm.* Wait | The agent lists the workflows, runs `03_claymation`, and reports the file it saved. Press **My Files**: the image is there |
| 5 | Ask the agent: *What are the newest files I made?* | A list of the latest files, newest first |
| 6 | Open **Stems & Voices (Demucs) > Analyze**, drop in the test song, press **Analyze** | Tempo in BPM, the key, the length and the levels |
| 6b | Open **Chords**, drop in a song (a Suno or ACE-Step song works), leave **Separate guitar and keys** on, press **Read chords**. Wait for the split | A chart with three sections (main progression, guitar, keys), each a list of times and chord letters such as `0:12.4  Am`. A part the song does not have says so. The same chart is in **My Files > chords** as a text file. Play the song along the chart: most chords should match |
| 7 | Open **LM Studio** from Applications, pick the gpt-oss model, open its Integrations (the plug icon) | `mac-ai-studio-comfyui` is listed, with the same tools |

**Pass:** steps 1 to 3c answer from the documents with sources, step 4 produces an image, step 6 shows a tempo and key, and step 6b gives a chord chart.

To check that it works offline, turn Wi-Fi off before step 1. LM Studio shows a notice that it cannot check for updates; everything else works the same.

## Milestone 5: live session

```bash
./milestone5.sh
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
| 4 | Open the Chat tab and ask one question | It answers as before |

**Pass:** the tools update with one double-click and the studio still works. The owner's version of these steps is [UPDATING.md](UPDATING.md).

## How to show it

A short, reliable order. Render the slow items before the meeting, and start one fresh render live.

1. Quit everything, then open **Mac AI Studio** from the Dock, to show that it is one app.
2. Turn Wi-Fi off, to show that it is offline.
3. **Images:** show the three samples, then run one fresh prompt.
4. **Video:** play the Pro sketch-and-fill clip first, since it is the most striking, then show the folder batch.
5. **Music:** play a generated song.
6. **Stems:** split it, then drag the stems into Logic Pro.
7. **Chat:** ask the assistant how to do one of the steps above, then let it render one image with `@agent`.
8. Press **My Files**, to show that everything is ordinary files on the Mac.
