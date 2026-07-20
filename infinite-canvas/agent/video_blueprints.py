"""无限画布 v4.50 · 视频生成蓝图库（Wan2.2 / LTX / CogVideo）。

设计要点（§4.2 / §9.3）：
- Wan2.2 fp8 为默认生产管线（24GB VRAM 可用，RTX 5080 16GB 需 GGUF）
- LTX 为轻量蒸馏方案（4 步推理），用于快速预览
- 蓝图产出的 ComfyUI JSON 经 validator 校验后再提交
- 所有模型路径指向共享库 `SHARED_MODEL_LIB`，不硬编码

蓝图注册表（§3.2 工作流组装时引用）：
- wan2.2_t2v_fp8    : Wan2.2 文生视频（fp8 量化，24GB）
- wan2.2_t2v_gguf   : Wan2.2 文生视频（GGUF Q5，16GB）
- wan2.2_i2v_fp8    : Wan2.2 图生视频（fp8 量化）
- ltx_t2v           : LTX 文生视频（4 步蒸馏）
- cogvideo_t2v      : CogVideoX（备用）
"""

from __future__ import annotations

from typing import Any

# ── 共享库模型路径（§4.1 模型选型表）──────────────────────────────
import os

_SHARED = os.environ.get("SHARED_MODEL_LIB", r"C:\ai_comfyui_dd\models")

# Wan2.2 模型（DiT 架构，MIT 许可证）
WAN22_T2V_FP8_UNET = "wan2.2_t2v_14B_fp8_e4m3fn.safetensors"
WAN22_T2V_GGUF_UNET = "wan2.2_t2v_14B_Q5_K_M.gguf"
WAN22_I2V_FP8_UNET = "wan2.2_i2v_14B_720P_fp8_e4m3fn.safetensors"
WAN22_CLIP = "umt5_xxl_fp8_e4m3fn_clip_l.safetensors"
WAN22_VAE = "wan_2.1_vae.safetensors"

# LTX 模型（Apache 2.0 许可证）
LTX_T2V_UNET = "ltx_video_2b_0.9.5.safetensors"
LTX_CLIP = "t5xxl_fp8_e4m3fn_clip_l.safetensors"
LTX_VAE = "ltx_video_vae.safetensors"

# CogVideoX 模型（Apache 2.0 许可证）
COGVIDEO_T2V_UNET = "cogvideox_5b.safetensors"
COGVIDEO_CLIP = "t5xxl_fp8_e4m3fn_clip_l.safetensors"
COGVIDEO_VAE = "cogvideox_vae.safetensors"


# ── 蓝图定义：每个蓝图是一个 node builder 函数 ────────────────────

def _node(id: int, class_type: str, inputs: dict[str, Any], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """便捷构造一个 ComfyUI 节点对象。"""
    return {"id": id, "class_type": class_type, "inputs": inputs, "_meta": meta or {}}


def wan22_t2v_fp8(
    positive: str,
    negative: str = "",
    width: int = 1280,
    height: int = 720,
    frames: int = 81,
    steps: int = 20,
    cfg: float = 5.0,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Wan2.2 文生视频（fp8 量化）。24GB VRAM 推荐。"""
    import random
    s = seed if seed > 0 else random.randint(0, 2**32 - 1)
    fps = 16
    return [
        _node(1, "WanVideoCLIPLoader", {
            "clip_name": WAN22_CLIP,
            "type": "wan",
            "device": "default",
        }),
        _node(2, "WanVideoVAELoader", {
            "vae_name": WAN22_VAE,
            "device": "default",
        }),
        _node(3, "WanVideoUNETLoaderV2", {
            "unet_name": WAN22_T2V_FP8_UNET,
            "weight_dtype": "fp8_e4m3fn",
        }),
        _node(4, "CLIPTextEncode", {
            "clip": [1, 0],
            "text": positive,
        }),
        _node(5, "CLIPTextEncode", {
            "clip": [1, 0],
            "text": negative,
        }),
        _node(6, "EmptyHunyuanLatentVideo", {
            "width": width,
            "height": height,
            "length": frames,
            "batch_size": 1,
        }),
        _node(7, "WanVideoSampler", {
            "unet": [3, 0],
            "clip": [1, 0],
            "vae": [2, 0],
            "positive": [4, 0],
            "negative": [5, 0],
            "latent_image": [6, 0],
            "steps": steps,
            "cfg": cfg,
            "seed": s,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "tiled_vae": True,
        }),
        _node(8, "VAEDecode", {
            "samples": [7, 0],
            "vae": [2, 0],
        }),
        _node(9, f"VHS_VideoCombine_WAN_{width}x{height}", {
            "images": [8, 0],
            "frame_rate": fps,
            "format": "video/h264-mp4",
            "pix_fmt": "yuv420p",
        }),
        _node(10, "SaveVideo", {
            "filenames": [9, 0],
            "filename_prefix": f"wan22_t2v_{width}x{height}",
        }),
    ]


def wan22_t2v_gguf(
    positive: str,
    negative: str = "",
    width: int = 832,
    height: int = 480,
    frames: int = 49,
    steps: int = 20,
    cfg: float = 5.0,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Wan2.2 文生视频（GGUF Q5）。16GB VRAM 可用。"""
    import random
    s = seed if seed > 0 else random.randint(0, 2**32 - 1)
    fps = 16
    return [
        _node(1, "WanVideoCLIPLoader", {
            "clip_name": WAN22_CLIP,
            "type": "wan",
            "device": "default",
        }),
        _node(2, "WanVideoVAELoader", {
            "vae_name": WAN22_VAE,
            "device": "default",
        }),
        _node(3, "WanVideoUNETLoaderGGUF", {
            "unet_name": WAN22_T2V_GGUF_UNET,
        }),
        _node(4, "CLIPTextEncode", {
            "clip": [1, 0],
            "text": positive,
        }),
        _node(5, "CLIPTextEncode", {
            "clip": [1, 0],
            "text": negative,
        }),
        _node(6, "EmptyHunyuanLatentVideo", {
            "width": width,
            "height": height,
            "length": frames,
            "batch_size": 1,
        }),
        _node(7, "WanVideoSampler", {
            "unet": [3, 0],
            "clip": [1, 0],
            "vae": [2, 0],
            "positive": [4, 0],
            "negative": [5, 0],
            "latent_image": [6, 0],
            "steps": steps,
            "cfg": cfg,
            "seed": s,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
        }),
        _node(8, "VAEDecode", {
            "samples": [7, 0],
            "vae": [2, 0],
        }),
        _node(9, "VHS_VideoCombine_WAN_GGUF", {
            "images": [8, 0],
            "frame_rate": fps,
            "format": "video/h264-mp4",
            "pix_fmt": "yuv420p",
        }),
        _node(10, "SaveVideo", {
            "filenames": [9, 0],
            "filename_prefix": f"wan22_t2v_gguf_{width}x{height}",
        }),
    ]


def wan22_i2v_fp8(
    positive: str,
    image_ref: str,
    negative: str = "",
    width: int = 1280,
    height: int = 720,
    frames: int = 81,
    steps: int = 20,
    cfg: float = 5.0,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Wan2.2 图生视频（fp8 量化）。需要一张起始帧参考图。"""
    import random
    s = seed if seed > 0 else random.randint(0, 2**32 - 1)
    fps = 16
    return [
        _node(1, "WanVideoCLIPLoader", {
            "clip_name": WAN22_CLIP,
            "type": "wan",
            "device": "default",
        }),
        _node(2, "WanVideoVAELoader", {
            "vae_name": WAN22_VAE,
            "device": "default",
        }),
        _node(3, "WanVideoUNETLoaderV2", {
            "unet_name": WAN22_I2V_FP8_UNET,
            "weight_dtype": "fp8_e4m3fn",
        }),
        _node(4, "LoadImage", {
            "image": image_ref,
        }),
        _node(5, "CLIPTextEncode", {
            "clip": [1, 0],
            "text": positive,
        }),
        _node(6, "CLIPTextEncode", {
            "clip": [1, 0],
            "text": negative,
        }),
        _node(7, "EmptyHunyuanLatentVideo", {
            "width": width,
            "height": height,
            "length": frames,
            "batch_size": 1,
        }),
        _node(8, "WanVideoSampler", {
            "unet": [3, 0],
            "clip": [1, 0],
            "vae": [2, 0],
            "positive": [5, 0],
            "negative": [6, 0],
            "latent_image": [7, 0],
            "start_image": [4, 0],
            "steps": steps,
            "cfg": cfg,
            "seed": s,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
        }),
        _node(9, "VAEDecode", {
            "samples": [8, 0],
            "vae": [2, 0],
        }),
        _node(10, "VHS_VideoCombine_WAN_I2V", {
            "images": [9, 0],
            "frame_rate": fps,
            "format": "video/h264-mp4",
            "pix_fmt": "yuv420p",
        }),
        _node(11, "SaveVideo", {
            "filenames": [10, 0],
            "filename_prefix": f"wan22_i2v_{width}x{height}",
        }),
    ]


def ltx_t2v(
    positive: str,
    negative: str = "",
    width: int = 768,
    height: int = 512,
    frames: int = 49,
    steps: int = 4,
    cfg: float = 3.0,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """LTX 文生视频（4 步蒸馏，Apache 2.0）。轻量快速预览。"""
    import random
    s = seed if seed > 0 else random.randint(0, 2**32 - 1)
    fps = 24
    return [
        _node(1, "CLIPLoader", {
            "clip_name": LTX_CLIP,
            "type": "ltx",
        }),
        _node(2, "VAELoader", {
            "vae_name": LTX_VAE,
        }),
        _node(3, "UNETLoader", {
            "unet_name": LTX_T2V_UNET,
            "weight_dtype": "default",
        }),
        _node(4, "CLIPTextEncode", {
            "clip": [1, 0],
            "text": positive,
        }),
        _node(5, "CLIPTextEncode", {
            "clip": [1, 0],
            "text": negative,
        }),
        _node(6, "EmptyLTXLatentVideo", {
            "width": width,
            "height": height,
            "length": frames,
            "batch_size": 1,
        }),
        _node(7, "LTXVideoSampler", {
            "model": [3, 0],
            "positive": [4, 0],
            "negative": [5, 0],
            "latent_image": [6, 0],
            "steps": steps,
            "cfg": cfg,
            "seed": s,
            "sampler_name": "euler",
            "scheduler": "simple",
        }),
        _node(8, "VAEDecode", {
            "samples": [7, 0],
            "vae": [2, 0],
        }),
        _node(9, "VHS_VideoCombine_LTX", {
            "images": [8, 0],
            "frame_rate": fps,
            "format": "video/h264-mp4",
            "pix_fmt": "yuv420p",
        }),
        _node(10, "SaveVideo", {
            "filenames": [9, 0],
            "filename_prefix": f"ltx_t2v_{width}x{height}",
        }),
    ]


# ── 蓝图注册表（workflow_assembler 调用入口）─────────────────

BLUEPRINT_REGISTRY: dict[str, dict[str, Any]] = {
    "wan2.2_t2v_fp8": {
        "id": "wan2.2_t2v_fp8",
        "name": "Wan2.2 文生视频 (fp8 · 24GB)",
        "category": "video",
        "builder": wan22_t2v_fp8,
        "license": "MIT",
        "vram": "24GB",
        "resolution": "1280x720",
        "params": {
            "steps": 20,
            "cfg": 5.0,
            "frames": 81,
            "width": 1280,
            "height": 720,
        },
    },
    "wan2.2_t2v_gguf": {
        "id": "wan2.2_t2v_gguf",
        "name": "Wan2.2 文生视频 (GGUF Q5 · 16GB)",
        "category": "video",
        "builder": wan22_t2v_gguf,
        "license": "MIT",
        "vram": "16GB",
        "resolution": "832x480",
        "params": {
            "steps": 20,
            "cfg": 5.0,
            "frames": 49,
            "width": 832,
            "height": 480,
        },
    },
    "wan2.2_i2v_fp8": {
        "id": "wan2.2_i2v_fp8",
        "name": "Wan2.2 图生视频 (fp8 · 24GB)",
        "category": "video",
        "builder": wan22_i2v_fp8,
        "license": "MIT",
        "vram": "24GB",
        "resolution": "1280x720",
        "params": {
            "steps": 20,
            "cfg": 5.0,
            "frames": 81,
            "width": 1280,
            "height": 720,
        },
    },
    "ltx_t2v": {
        "id": "ltx_t2v",
        "name": "LTX 文生视频 (4步蒸馏 · 轻量)",
        "category": "video",
        "builder": ltx_t2v,
        "license": "Apache 2.0",
        "vram": "12GB",
        "resolution": "768x512",
        "params": {
            "steps": 4,
            "cfg": 3.0,
            "frames": 49,
            "width": 768,
            "height": 512,
        },
    },
}


def get_blueprint(blueprint_id: str) -> dict[str, Any] | None:
    """按 ID 查询蓝图。"""
    return BLUEPRINT_REGISTRY.get(blueprint_id)


def list_blueprints(category: str | None = None) -> list[dict[str, Any]]:
    """列出所有蓝图，可按类别过滤。"""
    result = []
    for bp in BLUEPRINT_REGISTRY.values():
        if category is None or bp["category"] == category:
            result.append({
                "id": bp["id"],
                "name": bp["name"],
                "category": bp["category"],
                "license": bp["license"],
                "vram": bp["vram"],
                "resolution": bp["resolution"],
                "params": bp["params"],
            })
    return result


def recommend_blueprint(vram_gb: float = 16.0, mode: str = "t2v", prefer_quality: bool = False) -> str:
    """根据 VRAM 和模式自动推荐最优蓝图。

    推荐逻辑（§4.2 量化策略）：
    - ≥ 24 GB + 质量优先 → wan2.2_t2v_fp8
    - ≥ 16 GB + 质量优先 → wan2.2_t2v_gguf
    - < 16 GB → ltx_t2v
    """
    if mode == "i2v" and vram_gb >= 24:
        return "wan2.2_i2v_fp8"
    if vram_gb >= 24 and prefer_quality:
        return "wan2.2_t2v_fp8"
    if vram_gb >= 16:
        return "wan2.2_t2v_gguf"
    return "ltx_t2v"
