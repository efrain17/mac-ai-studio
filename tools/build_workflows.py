#!/usr/bin/env python3
"""Generates every workflow, the single source of truth for both formats.

workflows/<group>/*.json      what you open in ComfyUI
workflows/<group>/api/*.json  what the test scripts send to ComfyUI
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "workflows"
AVOID = "blurry, low quality, watermark, text, signature, deformed hands, extra fingers"
# Generic placeholder subjects, so the test files use no private material.
PERSON = "a lighthouse keeper in a heavy raincoat standing on a stormy pier at dusk, holding a lantern"
SCENE = "a small paper sailboat drifting across a calm lake at sunrise, gentle ripples, slow camera push in"
FILL = "a colorful children's book illustration of a house with a garden under a bright sun, flat paint colors"

SDXL_VAE = "sdxl_vae_fp16_fix.safetensors"
LTX = "ltxv-2b-0.9.8-distilled.safetensors"
T5 = "t5xxl_fp16.safetensors"
SCRIBBLE = "xinsir-scribble-sdxl.safetensors"
WAN = "wan2.2_ti2v_5B_fp16.safetensors"
UMT5 = "umt5_xxl_fp16.safetensors"
WAN_VAE = "wan2.2_vae.safetensors"
# LTX's distilled schedule; distilled models run at cfg 1, so negative prompts have no effect.
LTX_SIGMAS = "1.0, 0.9937, 0.9875, 0.9812, 0.975, 0.9094, 0.725, 0.4219, 0.0"
WIDTH, HEIGHT, FRAMES, FPS = 1216, 704, 97, 24.0

# Pro flows run on Wan 2.2 at its native size and rate: 5 seconds of 1280x704 at 24 fps. Wan has a
# real negative prompt (cfg 5), so the list below works; it is the one Wan's authors publish, in
# English. Euler only: uni_pc corrupts across frames on Metal.
PRO_WIDTH, PRO_HEIGHT, PRO_FRAMES = 1280, 704, 121
PRO_STEPS, PRO_CFG, PRO_SHIFT = 25, 5.0, 8.0
FILL_FRAMES = 169  # 7 seconds of drawing and filling before the finished picture comes alive
WAN_AVOID = ("overexposed, static, blurred details, subtitles, style, artwork, painting, still image, "
             "overall gray, worst quality, low quality, JPEG compression artifacts, ugly, incomplete, "
             "extra fingers, poorly drawn hands, poorly drawn face, deformed, disfigured, malformed "
             "limbs, fused fingers, motionless frame, cluttered background, three legs, many people "
             "in the background, walking backwards")
# Wan follows a shot description: subject, setting, light, camera move and pace.
SCENE_PRO = ("Cinematic wide shot. A small paper sailboat drifts slowly across a calm mountain lake at "
             "sunrise. Golden light, thin mist over the water, gentle ripples. The camera pushes in "
             "slowly and steadily. Natural, unhurried motion. 35mm film look, shallow depth of field, "
             "soft film grain, rich detail.")
ALIVE = ("the finished illustration gently comes alive: leaves sway in a light breeze, soft sunlight "
         "moves across the scene, the camera stays still, slow natural motion")

NOTE_A = """Text to video (Pro): Wan 2.2, 1280 x 704, 5 seconds at 24 fps.

- Prompt: describe the subject, the setting, the light, the camera move and the pace. Add "slowly" or "steady camera" for calm footage.
- Avoid: already holds Wan's own list. Add anything else you do not want to see.
- Render video: 25 steps, CFG 5. 20 steps is faster, 30 is finer. Keep euler.
- Portrait video: set 704 x 1280 in Video size.
- Each clip takes a long time on this Mac, and the first one also loads the models."""
NOTE_B = """Sketch folder to video (Pro): one 5-second clip per sketch in input/sketches.

- Each sketch becomes a picture that follows its lines, then Wan 2.2 sets it in motion.
- Picture prompt: the look of the finished picture. Keep it one sentence.
- Prompt (motion): what moves, and how slowly. Describe the scene again, then the motion.
- Dark lines on white paper work best."""
NOTE_C = """Sketch and fill (Pro): 7 seconds of drawing and filling, then 5 seconds of motion.

- Your sketch: choose a dark-on-white drawing. The example is in input.
- Lines appear, then Color fills: the start and end values are fractions of the 169 frames. Color ends at 0.88, so the finished picture holds still for a moment before it moves.
- The motion part is Wan 2.2 starting from the finished picture, so the join is seamless.
- No hands or tools can appear in the drawing part: no model paints those frames."""


class Graph:
    """Builds an API-format graph; add() returns the new node's id."""

    def __init__(self):
        self.nodes = {}

    def add(self, class_type, title, **inputs):
        node_id = str(len(self.nodes) + 1)
        self.nodes[node_id] = {"class_type": class_type, "_meta": {"title": title},
                               "inputs": inputs}
        return node_id


# ---- Images -----------------------------------------------------------------------------------

STYLES = {
    "01_gritty_graphic_novel": {
        "checkpoint": "sd_xl_base_1.0.safetensors",
        "lora": "Graphic_Novel_Illustration-000007.safetensors",
        "prompt": f"breathtaking graphic novel illustration of {PERSON}, dark and gritty, heavy ink shadows, high contrast",
        "avoid": f"{AVOID}, photograph, 3d render",
        "cfg": 7.0,
        "seed": 4101,
    },
    "02_photorealistic_human": {
        "checkpoint": "RealVisXL_V5.0_fp16.safetensors",
        "lora": None,
        "prompt": f"RAW photo, {PERSON}, natural skin texture, 85mm lens, shallow depth of field, film grain",
        "avoid": f"{AVOID}, illustration, painting, cartoon, 3d render, plastic skin",
        "cfg": 5.0,
        "seed": 4102,
    },
    "03_claymation": {
        "checkpoint": "sd_xl_base_1.0.safetensors",
        "lora": "ClayAnimationRedm.safetensors",
        "prompt": f"Clay Animation, Clay, {PERSON}, handmade stop motion set, soft studio lighting, visible fingerprints in the clay",
        "avoid": f"{AVOID}, photograph, realistic skin, 2d drawing",
        "cfg": 7.0,
        "seed": 4103,
    },
}


def style_graph(name, style):
    g = Graph()
    loader = g.add("CheckpointLoaderSimple", "Model", ckpt_name=style["checkpoint"])
    model, clip = [loader, 0], [loader, 1]
    if style["lora"]:
        lora = g.add("LoraLoader", "Style LoRA", lora_name=style["lora"], strength_model=0.9,
                     strength_clip=0.9, model=model, clip=clip)
        model, clip = [lora, 0], [lora, 1]
    prompt = g.add("CLIPTextEncode", "Prompt", text=style["prompt"], clip=clip)
    avoid = g.add("CLIPTextEncode", "Avoid", text=style["avoid"], clip=clip)
    size = g.add("EmptyLatentImage", "Image size", width=1024, height=1024, batch_size=1)
    sampler = g.add("KSampler", "Render", seed=style["seed"], steps=30, cfg=style["cfg"],
                    sampler_name="dpmpp_2m", scheduler="karras", denoise=1.0, model=model,
                    positive=[prompt, 0], negative=[avoid, 0], latent_image=[size, 0])
    vae = g.add("VAELoader", "VAE", vae_name=SDXL_VAE)
    decode = g.add("VAEDecode", "Decode", samples=[sampler, 0], vae=[vae, 0])
    g.add("SaveImage", "Save", filename_prefix=f"images/{name}", images=[decode, 0])
    return g.nodes


# ---- Video ------------------------------------------------------------------------------------


def ltx_sampling(g, title, model, positive, negative, latent, seed):
    sampler = g.add("KSamplerSelect", "Sampler", sampler_name="euler")
    sigmas = g.add("ManualSigmas", "Schedule", sigmas=LTX_SIGMAS)
    return g.add("SamplerCustom", title, model=model, add_noise=True, noise_seed=seed, cfg=1.0,
                 positive=positive, negative=negative, sampler=[sampler, 0], sigmas=[sigmas, 0],
                 latent_image=latent)


def save_video(g, images, prefix):
    video = g.add("CreateVideo", "Make video", images=images, fps=FPS)
    g.add("SaveVideo", "Save video", video=[video, 0], filename_prefix=prefix, format="mp4",
          **{"format.codec": "auto"})


def sketch_render(g, sketch, prompt, width=WIDTH, height=HEIGHT):
    """Turns a dark-on-white sketch into a finished picture that follows its lines."""
    inverted = g.add("ImageInvert", "Sketch to white-on-black", image=sketch)
    loader = g.add("CheckpointLoaderSimple", "Picture model", ckpt_name="sd_xl_base_1.0.safetensors")
    vae = g.add("VAELoader", "Picture VAE", vae_name=SDXL_VAE)
    positive = g.add("CLIPTextEncode", "Picture prompt", text=prompt, clip=[loader, 1])
    negative = g.add("CLIPTextEncode", "Avoid", text=f"{AVOID}, hands, pencil, pen, drawing tools",
                     clip=[loader, 1])
    control = g.add("ControlNetLoader", "Sketch guide", control_net_name=SCRIBBLE)
    applied = g.add("ControlNetApplyAdvanced", "Follow the sketch", positive=[positive, 0],
                    negative=[negative, 0], control_net=[control, 0], image=[inverted, 0],
                    strength=0.8, start_percent=0.0, end_percent=0.9)
    size = g.add("EmptyLatentImage", "Picture size", width=width, height=height, batch_size=1)
    sampler = g.add("KSampler", "Render picture", seed=4201, steps=30, cfg=5.0,
                    sampler_name="dpmpp_2m", scheduler="karras", denoise=1.0, model=[loader, 0],
                    positive=[applied, 0], negative=[applied, 1], latent_image=[size, 0])
    return g.add("VAEDecode", "Decode picture", samples=[sampler, 0], vae=[vae, 0])


def text_to_video():
    g = Graph()
    loader = g.add("CheckpointLoaderSimple", "Video model", ckpt_name=LTX)
    encoder = g.add("CLIPLoader", "Text encoder", clip_name=T5, type="ltxv", device="default")
    prompt = g.add("CLIPTextEncode", "Prompt", text=SCENE, clip=[encoder, 0])
    empty = g.add("CLIPTextEncode", "Unused at cfg 1", text="", clip=[encoder, 0])
    conditioned = g.add("LTXVConditioning", "Frame rate", positive=[prompt, 0],
                        negative=[empty, 0], frame_rate=FPS)
    size = g.add("EmptyLTXVLatentVideo", "Video size", width=WIDTH, height=HEIGHT, length=FRAMES,
                 batch_size=1)
    sampled = ltx_sampling(g, "Render video", [loader, 0], [conditioned, 0], [conditioned, 1],
                           [size, 0], 4301)
    decode = g.add("VAEDecode", "Decode", samples=[sampled, 0], vae=[loader, 2])
    save_video(g, [decode, 0], "video/text_to_video")
    return g.nodes


def sketch_folder_to_video():
    g = Graph()
    folder = g.add("LoadImageDataSetFromFolder", "Sketch folder (input/sketches)", folder="sketches")
    scaled = g.add("ImageScale", "Fit", image=[folder, 0], upscale_method="lanczos", width=WIDTH,
                   height=HEIGHT, crop="center")
    picture = sketch_render(g, [scaled, 0], FILL)
    prepared = g.add("LTXVPreprocess", "Prepare first frame", image=[picture, 0], img_compression=35)
    loader = g.add("CheckpointLoaderSimple", "Video model", ckpt_name=LTX)
    encoder = g.add("CLIPLoader", "Text encoder", clip_name=T5, type="ltxv", device="default")
    prompt = g.add("CLIPTextEncode", "Motion prompt",
                   text="the scene gently comes alive, leaves sway, soft light moves, static camera",
                   clip=[encoder, 0])
    empty = g.add("CLIPTextEncode", "Unused at cfg 1", text="", clip=[encoder, 0])
    start = g.add("LTXVImgToVideo", "Start from the picture", positive=[prompt, 0],
                  negative=[empty, 0], vae=[loader, 2], image=[prepared, 0], width=WIDTH,
                  height=HEIGHT, length=FRAMES, batch_size=1, strength=1.0)
    conditioned = g.add("LTXVConditioning", "Frame rate", positive=[start, 0], negative=[start, 1],
                        frame_rate=FPS)
    sampled = ltx_sampling(g, "Render video", [loader, 0], [conditioned, 0], [conditioned, 1],
                           [start, 2], 4302)
    decode = g.add("VAEDecode", "Decode", samples=[sampled, 0], vae=[loader, 2])
    save_video(g, [decode, 0], "video/sketch_to_video")
    return g.nodes


def sketch_and_fill():
    g = Graph()
    loaded = g.add("LoadImage", "Your sketch", image="sketch_and_fill_example.png")
    sketch = g.add("ImageScale", "Fit", image=[loaded, 0], upscale_method="lanczos", width=WIDTH,
                   height=HEIGHT, crop="center")
    picture = sketch_render(g, [sketch, 0], FILL)
    lines = g.add("ProgressiveRevealMask", "Lines appear", sketch=[sketch, 0], frames=FRAMES,
                  start=0.0, end=0.55, softness=0.05, seed=7)
    color = g.add("ProgressiveRevealMask", "Color fills", sketch=[sketch, 0], frames=FRAMES,
                  start=0.45, end=1.0, softness=0.05, seed=8)
    paper = g.add("EmptyImage", "Blank paper", width=WIDTH, height=HEIGHT, batch_size=FRAMES,
                  color=16777215)
    drawn = g.add("ImageCompositeMasked", "Draw the lines", destination=[paper, 0],
                  source=[sketch, 0], x=0, y=0, resize_source=False, mask=[lines, 0])
    filled = g.add("ImageCompositeMasked", "Fill the color", destination=[drawn, 0],
                   source=[picture, 0], x=0, y=0, resize_source=False, mask=[color, 0])
    save_video(g, [filled, 0], "video/sketch_and_fill")
    return g.nodes


def wan_fallback():
    """Used only if LTX renders badly on a given chip. Wan needs euler: uni_pc corrupts on Metal."""
    g = Graph()
    unet = g.add("UNETLoader", "Video model", unet_name="wan2.2_ti2v_5B_fp16.safetensors",
                 weight_dtype="default")
    model = g.add("ModelSamplingSD3", "Timing", model=[unet, 0], shift=8.0)
    encoder = g.add("CLIPLoader", "Text encoder", clip_name="umt5_xxl_fp16.safetensors", type="wan",
                    device="default")
    vae = g.add("VAELoader", "VAE", vae_name="wan2.2_vae.safetensors")
    prompt = g.add("CLIPTextEncode", "Prompt", text=SCENE, clip=[encoder, 0])
    negative = g.add("CLIPTextEncode", "Avoid", text=AVOID, clip=[encoder, 0])
    size = g.add("Wan22ImageToVideoLatent", "Video size", vae=[vae, 0], width=1280, height=704,
                 length=121, batch_size=1)
    sampler = g.add("KSampler", "Render video", seed=4401, steps=20, cfg=5.0, sampler_name="euler",
                    scheduler="simple", denoise=1.0, model=[model, 0], positive=[prompt, 0],
                    negative=[negative, 0], latent_image=[size, 0])
    decode = g.add("VAEDecode", "Decode", samples=[sampler, 0], vae=[vae, 0])
    save_video(g, [decode, 0], "video/wan_fallback")
    return g.nodes


# ---- Video Pro (Wan 2.2) ----------------------------------------------------------------------


def wan_model(g):
    """Loads Wan 2.2 with its text encoder and VAE."""
    unet = g.add("UNETLoader", "Video model", unet_name=WAN, weight_dtype="default")
    model = g.add("ModelSamplingSD3", "Timing", model=[unet, 0], shift=PRO_SHIFT)
    encoder = g.add("CLIPLoader", "Text encoder", clip_name=UMT5, type="wan", device="default")
    vae = g.add("VAELoader", "Video VAE", vae_name=WAN_VAE)
    return [model, 0], [encoder, 0], [vae, 0]


def wan_render(g, model, encoder, vae, prompt, seed, start_image=None, length=PRO_FRAMES):
    """Renders one clip; with start_image, the clip begins on that picture."""
    positive = g.add("CLIPTextEncode", "Prompt", text=prompt, clip=encoder)
    negative = g.add("CLIPTextEncode", "Avoid", text=WAN_AVOID, clip=encoder)
    size = dict(vae=vae, width=PRO_WIDTH, height=PRO_HEIGHT, length=length, batch_size=1)
    if start_image is None:
        latent = g.add("Wan22ImageToVideoLatent", "Video size", **size)
    else:
        latent = g.add("Wan22ImageToVideoLatent", "Start from the picture", **size,
                       start_image=start_image)
    sampler = g.add("KSampler", "Render video", seed=seed, steps=PRO_STEPS, cfg=PRO_CFG,
                    sampler_name="euler", scheduler="simple", denoise=1.0, model=model,
                    positive=[positive, 0], negative=[negative, 0], latent_image=[latent, 0])
    return g.add("VAEDecode", "Decode", samples=[sampler, 0], vae=vae)


def text_to_video_pro():
    g = Graph()
    model, encoder, vae = wan_model(g)
    decoded = wan_render(g, model, encoder, vae, SCENE_PRO, 4501)
    save_video(g, [decoded, 0], "video/text_to_video_pro")
    return g.nodes


def sketch_folder_to_video_pro():
    g = Graph()
    folder = g.add("LoadImageDataSetFromFolder", "Sketch folder (input/sketches)", folder="sketches")
    scaled = g.add("ImageScale", "Fit", image=[folder, 0], upscale_method="lanczos",
                   width=PRO_WIDTH, height=PRO_HEIGHT, crop="center")
    picture = sketch_render(g, [scaled, 0], FILL, PRO_WIDTH, PRO_HEIGHT)
    model, encoder, vae = wan_model(g)
    decoded = wan_render(g, model, encoder, vae, f"{FILL}. {ALIVE}", 4502, start_image=[picture, 0])
    save_video(g, [decoded, 0], "video/sketch_to_video_pro")
    return g.nodes


def sketch_and_fill_pro():
    g = Graph()
    loaded = g.add("LoadImage", "Your sketch", image="sketch_and_fill_example.png")
    sketch = g.add("ImageScale", "Fit", image=[loaded, 0], upscale_method="lanczos",
                   width=PRO_WIDTH, height=PRO_HEIGHT, crop="center")
    picture = sketch_render(g, [sketch, 0], FILL, PRO_WIDTH, PRO_HEIGHT)
    lines = g.add("ProgressiveRevealMask", "Lines appear", sketch=[sketch, 0], frames=FILL_FRAMES,
                  start=0.0, end=0.5, softness=0.05, seed=7)
    color = g.add("ProgressiveRevealMask", "Color fills", sketch=[sketch, 0], frames=FILL_FRAMES,
                  start=0.45, end=0.88, softness=0.05, seed=8)
    paper = g.add("EmptyImage", "Blank paper", width=PRO_WIDTH, height=PRO_HEIGHT,
                  batch_size=FILL_FRAMES, color=16777215)
    drawn = g.add("ImageCompositeMasked", "Draw the lines", destination=[paper, 0],
                  source=[sketch, 0], x=0, y=0, resize_source=False, mask=[lines, 0])
    filled = g.add("ImageCompositeMasked", "Fill the color", destination=[drawn, 0],
                   source=[picture, 0], x=0, y=0, resize_source=False, mask=[color, 0])
    model, encoder, vae = wan_model(g)
    alive = wan_render(g, model, encoder, vae, f"{FILL}. {ALIVE}", 4503, start_image=[picture, 0])
    # ImageBatch is marked deprecated in v0.43.0 but still runs; its replacement needs the new
    # auto-growing input format, which has not been checked from source.
    joined = g.add("ImageBatch", "Drawing, then motion", image1=[filled, 0], image2=[alive, 0])
    save_video(g, [joined, 0], "video/sketch_and_fill_pro")
    return g.nodes


# ---- Conversion to the format ComfyUI's editor opens ------------------------------------------

OUTPUTS = {
    "CheckpointLoaderSimple": ["MODEL", "CLIP", "VAE"],
    "LoraLoader": ["MODEL", "CLIP"],
    "CLIPTextEncode": ["CONDITIONING"],
    "CLIPLoader": ["CLIP"],
    "EmptyLatentImage": ["LATENT"],
    "EmptyLTXVLatentVideo": ["LATENT"],
    "EmptyImage": ["IMAGE"],
    "KSampler": ["LATENT"],
    "KSamplerSelect": ["SAMPLER"],
    "ManualSigmas": ["SIGMAS"],
    "SamplerCustom": ["LATENT", "LATENT"],
    "VAELoader": ["VAE"],
    "VAEDecode": ["IMAGE"],
    "SaveImage": [],
    "ControlNetLoader": ["CONTROL_NET"],
    "ControlNetApplyAdvanced": ["CONDITIONING", "CONDITIONING"],
    "ImageInvert": ["IMAGE"],
    "ImageScale": ["IMAGE"],
    "ImageCompositeMasked": ["IMAGE"],
    "LoadImage": ["IMAGE", "MASK"],
    "LoadImageDataSetFromFolder": ["IMAGE"],
    "LTXVConditioning": ["CONDITIONING", "CONDITIONING"],
    "LTXVPreprocess": ["IMAGE"],
    "LTXVImgToVideo": ["CONDITIONING", "CONDITIONING", "LATENT"],
    "CreateVideo": ["VIDEO"],
    "SaveVideo": [],
    "ProgressiveRevealMask": ["MASK", "MASK"],
    "UNETLoader": ["MODEL"],
    "ModelSamplingSD3": ["MODEL"],
    "Wan22ImageToVideoLatent": ["LATENT"],
    "ImageBatch": ["IMAGE"],
}
# Socket input types by name; everything else on a node is a widget.
SOCKETS = {
    "model": "MODEL", "clip": "CLIP", "vae": "VAE", "positive": "CONDITIONING",
    "negative": "CONDITIONING", "latent_image": "LATENT", "samples": "LATENT", "images": "IMAGE",
    "image": "IMAGE", "destination": "IMAGE", "source": "IMAGE", "sketch": "IMAGE",
    "mask": "MASK", "sampler": "SAMPLER", "sigmas": "SIGMAS", "control_net": "CONTROL_NET",
    "video": "VIDEO", "start_image": "IMAGE", "image1": "IMAGE", "image2": "IMAGE",
}
# Widget order as ComfyUI's editor stores it for each node, where it differs from the graph's.
WIDGETS = {
    "KSampler": lambda i: [i["seed"], "randomize", i["steps"], i["cfg"], i["sampler_name"],
                           i["scheduler"], i["denoise"]],
    "SamplerCustom": lambda i: [i["add_noise"], i["noise_seed"], "randomize", i["cfg"]],
    "SaveVideo": lambda i: [i["filename_prefix"], i["format"], i["format.codec"]],
    "LoadImage": lambda i: [i["image"], "image"],
    "ProgressiveRevealMask": lambda i: [i["frames"], i["start"], i["end"], i["softness"], i["seed"],
                                        "fixed"],
}


def is_link(value):
    return isinstance(value, list)


def note_node(node_id, order, text):
    return {
        "id": node_id, "type": "Note", "title": "Read me", "pos": [60, -260], "size": [620, 230],
        "flags": {}, "order": order, "mode": 0, "inputs": [], "outputs": [],
        "properties": {"text": ""}, "widgets_values": [text], "color": "#432", "bgcolor": "#653",
    }


def ui_graph(api, note=None):
    links = []
    nodes = {}
    for node_id, node in api.items():
        kind = node["class_type"]
        inputs = node["inputs"]
        linked = [name for name, value in inputs.items() if is_link(value)]
        if kind in WIDGETS:
            widgets = WIDGETS[kind](inputs)
        else:
            widgets = [value for value in inputs.values() if not is_link(value)]
        nodes[node_id] = {
            "id": int(node_id),
            "type": kind,
            "title": node["_meta"]["title"],
            "pos": [0, 0],
            "size": [340, 90 + 34 * len(widgets)],
            "flags": {},
            "order": int(node_id) - 1,
            "mode": 0,
            "inputs": [{"name": name, "type": SOCKETS[name], "link": None} for name in linked],
            "outputs": [
                {"name": slot_type, "type": slot_type, "slot_index": index, "links": []}
                for index, slot_type in enumerate(OUTPUTS[kind])
            ],
            "properties": {"Node name for S&R": kind},
            "widgets_values": widgets,
        }
    for node_id, node in api.items():
        slot = 0
        for name, value in node["inputs"].items():
            if not is_link(value):
                continue
            source_id, source_slot = value
            link_id = len(links) + 1
            links.append([link_id, int(source_id), source_slot, int(node_id), slot, SOCKETS[name]])
            nodes[node_id]["inputs"][slot]["link"] = link_id
            nodes[source_id]["outputs"][source_slot]["links"].append(link_id)
            slot += 1
    place(api, nodes)
    last_node_id = max(int(node_id) for node_id in api)
    if note:
        last_node_id += 1
        nodes["note"] = note_node(last_node_id, len(nodes), note)
    return {
        "last_node_id": last_node_id,
        "last_link_id": len(links),
        "nodes": list(nodes.values()),
        "links": links,
        "groups": [],
        "config": {},
        "extra": {},
        "version": 0.4,
    }


def place(api, nodes):
    """Lays nodes out left to right by how many steps they are from the start."""
    depth = {}

    def depth_of(node_id):
        if node_id not in depth:
            parents = [v[0] for v in api[node_id]["inputs"].values() if is_link(v)]
            depth[node_id] = 1 + max((depth_of(p) for p in parents), default=-1)
        return depth[node_id]

    used = {}
    for node_id in api:
        column = depth_of(node_id)
        nodes[node_id]["pos"] = [60 + column * 400, used.get(column, 60)]
        used[column] = used.get(column, 60) + nodes[node_id]["size"][1] + 70


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def emit(group, name, api, note=None):
    write(ROOT / group / "api" / f"{name}.json", api)
    write(ROOT / group / f"{name}.json", ui_graph(api, note))


def main():
    for name, style in STYLES.items():
        emit("images", name, style_graph(name, style))
    emit("video", "A_text_to_video", text_to_video())
    emit("video", "B_sketch_folder_to_video", sketch_folder_to_video())
    emit("video", "C_sketch_and_fill", sketch_and_fill())
    emit("video-wan", "D_wan_fallback", wan_fallback())
    emit("video-pro", "A_text_to_video_pro", text_to_video_pro(), NOTE_A)
    emit("video-pro", "B_sketch_folder_to_video_pro", sketch_folder_to_video_pro(), NOTE_B)
    emit("video-pro", "C_sketch_and_fill_pro", sketch_and_fill_pro(), NOTE_C)


if __name__ == "__main__":
    main()
