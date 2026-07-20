"""无限画布 v5.0 · 视频生成蓝图库（Wan2.2 / LTX / CogVideo）。

v5.0 模型定型（对齐 comfy_client.py 统一选型）：
  - 主力 T2V: Wan2.2 Bernini R (双 UNET 蒸馏，Apache 2.0)
  - 主力 I2V: Wan2.2 I2V 14B fp8 (双 UNET 蒸馏，Apache 2.0)
  - 预览/速度: LTX LightX2V (2-4 步蒸馏，Apache 2.0)
  - 备用: CogVideoX 5B (Apache 2.0)

所有模型常量从 comfy_client.py 导入，此文件为蓝图层（已废弃直接定义，
后续统一到 comfy_client.VIDEO_T2V_HIGH/LOW 和 VIDEO_I2V_HIGH/LOW）。
"""

from __future__ import annotations

from typing import Any

import os

_SHARED = os.environ.get("SHARED_MODEL_LIB", "")

# ── v5.0 模型常量（从 comfy_client.py 统一导入，此处保留向后兼容别名）──
# 所有新蓝图应直接引用 comfy_client.VIDEO_T2V_HIGH 等常量，此处仅作过渡。
try:
    from comfy_client import (
        VIDEO_T2V_HIGH, VIDEO_T2V_LOW,
        VIDEO_I2V_HIGH, VIDEO_I2V_LOW,
        VIDEO_CLIP, VIDEO_VAE,
    )
    WAN22_T2V_FP8_UNET = VIDEO_T2V_LOW   # 向后兼容（低噪 UNET）
    WAN22_T2V_GGUF_UNET = "wan2.2_t2v_14B_Q5_K_M.gguf"  # GGUF 无 Barnini 版本，保留
    WAN22_I2V_FP8_UNET = VIDEO_I2V_LOW   # 向后兼容
    WAN22_CLIP = VIDEO_CLIP
    WAN22_VAE = VIDEO_VAE
    _CANONICAL_IMPORT_OK = True
except ImportError:
    # 降级：直接定义（comfy_client.py 不可用时）
    WAN22_T2V_FP8_UNET = "wan2.2_bernini_r_low_noise_mxfp8.safetensors"
    WAN22_T2V_GGUF_UNET = "wan2.2_t2v_14B_Q5_K_M.gguf"
    WAN22_I2V_FP8_UNET = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
    WAN22_CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    WAN22_VAE = "wan_2.1_vae.safetensors"
    _CANONICAL_IMPORT_OK = False

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



def recommend_blueprint(vram_gb: float = 16.0, mode: str = "t2v",
                        prefer_quality: bool = False, speed_mode: bool = False) -> str:
    """根据 VRAM 和模式自动推荐最优蓝图。

    推荐逻辑（§4.2 量化策略）：
    - speed_mode=True → 优先 LightX2V 4步蒸馏（v5.0）
    - ≥ 24 GB + 质量优先 → wan2.2_t2v_fp8
    - ≥ 24 GB + i2v → wan2.2_i2v_fp8
    - ≥ 16 GB → wan2.2_t2v_gguf
    - < 16 GB → ltx_t2v

    v5.0 新增 speed_mode：当 speed_mode=True 时自动切换到 LightX2V 蓝图。
    """
    # v5.0: 速度模式优先 LightX2V
    if speed_mode:
        try:
            from lightx2v_blueprints import recommend_lightx2v_blueprint
            return recommend_lightx2v_blueprint(vram_gb, mode)
        except ImportError:
            pass  # 降级到标准蓝图
    if mode == "i2v" and vram_gb >= 24:
        return "wan2.2_i2v_fp8"
    if vram_gb >= 24 and prefer_quality:
        return "wan2.2_t2v_fp8"
    if vram_gb >= 16:
        return "wan2.2_t2v_gguf"
    return "ltx_t2v"


def get_blueprint(blueprint_id: str) -> dict[str, Any] | None:
    """按 ID 查询蓝图（含 LightX2V 加速蓝图 v5.0）。"""
    bp = BLUEPRINT_REGISTRY.get(blueprint_id)
    if bp is not None:
        return bp
    # v5.0: fallback 到 LightX2V 注册表
    try:
        from lightx2v_blueprints import get_lightx2v_blueprint
        return get_lightx2v_blueprint(blueprint_id)
    except ImportError:
        return None


def list_blueprints(category: str | None = None) -> list[dict[str, Any]]:
    """列出所有蓝图，可按类别过滤（含 LightX2V v5.0）。"""
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
                "speed_mode": bp.get("speed_mode", False),
            })
    # v5.0: 追加 LightX2V 蓝图
    try:
        from lightx2v_blueprints import list_lightx2v_blueprints
        for lbp in list_lightx2v_blueprints():
            if category is None or lbp["category"] == category:
                result.append(lbp)
    except ImportError:
        pass
    return result
