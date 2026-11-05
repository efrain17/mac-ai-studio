# The studio's own ComfyUI node: Progressive Reveal Mask

The studio adds one node to ComfyUI and no others: **Progressive Reveal Mask**. It is about 50 lines in `custom_nodes/reveal_mask.py`, written for this studio, and copied into `~/MacAIStudio/ComfyUI/custom_nodes` by `milestone2.sh`. It needs no model, no download and no internet.

## What it does

It makes the masks that let a sketch appear on blank paper as if drawn, then fill with color, frame by frame. It only calculates which pixels show in each frame, so no hand, pen or brush can appear in the video: no model paints these frames. Darker, inkier areas appear first, in soft organic patches.

## Where it is used

In the sketch-and-fill workflows, twice each:

| Workflow | Node title | Start | End |
| --- | --- | --- | --- |
| Sketch and fill | Lines appear | 0.0 | 0.55 |
| Sketch and fill | Color fills | 0.45 | 1.0 |
| Pro sketch and fill (Wan 2.2) | Lines appear | 0.0 | 0.5 |
| Pro sketch and fill (Wan 2.2) | Color fills | 0.45 | 0.88 |

In the Pro flow the picture then comes alive for the last part of the clip.

## Its settings

| Setting | What it changes |
| --- | --- |
| **sketch** | The picture to reveal. Its dark lines decide what appears first |
| **frames** | How many frames the animation has. Keep it equal to the video's frame count, or the reveal ends early or is cut off |
| **start** | When the reveal begins, as a share of the clip: 0 is the first frame, 0.5 the middle |
| **end** | When everything is visible. Must be later than start |
| **softness** | How soft the edge of each appearing patch is. Higher is a gentler fade; lower is a crisp wipe |
| **seed** | The pattern of the patches. Another number gives another order of appearing, with the same timing |

It has two outputs: **reveal** (what is visible so far) and **front** (only the edge that is appearing right now, used for the drawing line).

## Common changes

- **Slower drawing:** raise **end** on Lines appear, and raise **start** on Color fills by the same amount.
- **Color at the same time as the lines:** set both nodes to the same start and end.
- **A different look each render:** change the **seed** on both nodes.

## If it goes wrong

| Problem | Fix |
| --- | --- |
| The node shows red, or ComfyUI says `ProgressiveRevealMask` is missing | The file is not in ComfyUI's custom_nodes folder. Run `./milestone2.sh` again, then restart the Images & Video tab |
| The reveal finishes too early or never finishes | **frames** differs from the video's frame count. Set it to the same number as the video nodes |
| Nothing appears for a long time | **start** is set high. Lower it |
