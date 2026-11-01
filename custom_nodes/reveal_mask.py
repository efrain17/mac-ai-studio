# A ComfyUI node that makes the masks for the sketch-and-fill animation. It only computes a mask
# per frame, on the CPU, so no drawing tool or hand can appear: no model paints these frames.
import torch
import torch.nn.functional as F
from typing_extensions import override

from comfy_api.latest import ComfyExtension, io


class ProgressiveRevealMask(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="ProgressiveRevealMask",
            display_name="Progressive Reveal Mask",
            category="mask/animation",
            inputs=[
                io.Image.Input("sketch"),
                io.Int.Input("frames", default=97, min=1, max=4096),
                io.Float.Input("start", default=0.0, min=0.0, max=1.0, step=0.01),
                io.Float.Input("end", default=1.0, min=0.0, max=1.0, step=0.01),
                io.Float.Input("softness", default=0.05, min=0.001, max=0.5, step=0.001),
                io.Int.Input("seed", default=0, min=0, max=0xffffffffffffffff),
            ],
            outputs=[io.Mask.Output(display_name="reveal"), io.Mask.Output(display_name="front")],
        )

    @classmethod
    def execute(cls, sketch, frames, start, end, softness, seed):
        gray = sketch[0, ..., :3].cpu().mean(-1)
        height, width = gray.shape
        ink = F.avg_pool2d((1 - gray)[None, None], 31, 1, 15)[0, 0]
        generator = torch.Generator().manual_seed(seed)
        noise = F.interpolate(
            torch.rand(1, 1, height // 64 + 2, width // 64 + 2, generator=generator),
            (height, width), mode="bicubic",
        )[0, 0]
        # Each pixel gets a moment to appear: areas with more ink come first, in organic patches.
        order = 0.7 * noise + 0.3 * (1 - ink / (ink.max() + 1e-6))
        order = (order - order.min()) / (order.max() - order.min() + 1e-6)
        time = torch.linspace(0, 1, frames).view(-1, 1, 1)
        time = ((time - start) / max(end - start, 1e-6)).clamp(0, 1) * (1 + softness)
        reveal = ((time - order) / softness).clamp(0, 1)
        return io.NodeOutput(reveal, 4 * reveal * (1 - reveal))


class RevealExtension(ComfyExtension):
    @override
    async def get_node_list(self):
        return [ProgressiveRevealMask]


async def comfy_entrypoint():
    return RevealExtension()
