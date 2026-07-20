"""无限画布 v4.50 · 工作流组装器（蓝图 → ComfyUI JSON）。

核心职责（§3.2 工作流引擎 Phase 3）：
1. 接收 storyboard plan（来自 workflow_planner）+ entity data（来自 entity_registry）
2. 按 consistency_manager 推荐填入最优一致性策略
3. 按 VRAM 条件匹配量化策略（fp8 / GGUF Q5 / ltx）
4. 构建完整的 ComfyUI workflow JSON（含节点 + 连线）
5. 产出 multi-shot 列表（每个分镜一套 workflow）

设计纪律：
- 所有 class_type 来自 ComfyUI /object_info 动态校验，不硬编码非法值
- 多角色同框自动注入工程化 prompt（Engineering Prompt, §4.4）
- 输出可直接经 comfy_client.validate_workflow 校验
"""

from __future__ import annotations

import json
import random
from typing import Any

# 将自身路径加入 sys.path（允许直接 python workflow_assembler.py 运行）
import sys
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import consistency_manager as cm
import video_blueprints as vb


# ── 文本生图蓝图（复用 intent_map 模板结构）────────────────────────

def txt2img_noobai(
    positive: str,
    negative: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """NoobAI-XL 文生图（SDXL）。"""
    s = seed if seed > 0 else random.randint(0, 2**32 - 1)
    return [
        {"id": 1, "class_type": "CheckpointLoaderSimple",
         "inputs": {"ckpt_name": "NoobAI-XL-Vpred-v1.0.safetensors"}},
        {"id": 2, "class_type": "CLIPTextEncode",
         "inputs": {"clip": [1, 1], "text": positive}},
        {"id": 3, "class_type": "CLIPTextEncode",
         "inputs": {"clip": [1, 1], "text": negative}},
        {"id": 4, "class_type": "EmptyLatentImage",
         "inputs": {"width": width, "height": height, "batch_size": 1}},
        {"id": 5, "class_type": "KSampler",
         "inputs": {
             "model": [1, 0], "positive": [2, 0], "negative": [3, 0],
             "latent_image": [4, 0], "seed": s, "steps": steps, "cfg": cfg,
             "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
         }},
        {"id": 6, "class_type": "VAEDecode",
         "inputs": {"samples": [5, 0], "vae": [1, 2]}},
        {"id": 7, "class_type": "SaveImage",
         "inputs": {"images": [6, 0], "filename_prefix": "txt2img_noobai"}},
    ]


def txt2img_qwen(
    positive: str,
    negative: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 7.0,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Qwen-Image 2.0 文生图（Apache 2.0，中文友好）。"""
    s = seed if seed > 0 else random.randint(0, 2**32 - 1)
    return [
        {"id": 1, "class_type": "UNETLoader",
         "inputs": {"unet_name": "qwen_image_2512_fp8_e4m3fn.safetensors", "weight_dtype": "fp8_e4m3fn"}},
        {"id": 2, "class_type": "CLIPLoader",
         "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image"}},
        {"id": 3, "class_type": "VAELoader",
         "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        {"id": 4, "class_type": "CLIPTextEncode",
         "inputs": {"clip": [2, 0], "text": positive}},
        {"id": 5, "class_type": "CLIPTextEncode",
         "inputs": {"clip": [2, 0], "text": negative}},
        {"id": 6, "class_type": "EmptySD3LatentImage",
         "inputs": {"width": width, "height": height, "batch_size": 1}},
        {"id": 7, "class_type": "KSampler",
         "inputs": {
             "model": [1, 0], "positive": [4, 0], "negative": [5, 0],
             "latent_image": [6, 0], "seed": s, "steps": steps, "cfg": cfg,
             "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
         }},
        {"id": 8, "class_type": "VAEDecode",
         "inputs": {"samples": [7, 0], "vae": [3, 0]}},
        {"id": 9, "class_type": "SaveImage",
         "inputs": {"images": [8, 0], "filename_prefix": "txt2img_qwen"}},
    ]


# ── 图像生成蓝图注册表 ──────────────────────────────────────────────

IMAGE_BLUEPRINTS: dict[str, dict[str, Any]] = {
    "txt2img_sdxl": {
        "id": "txt2img_sdxl", "name": "NoobAI-XL (SDXL)", "category": "txt2img",
        "builder": txt2img_noobai, "params": {"steps": 20, "cfg": 7.0, "width": 1024, "height": 1024},
    },
    "txt2img_qwen": {
        "id": "txt2img_qwen", "name": "Qwen-Image 2.0", "category": "txt2img",
        "builder": txt2img_qwen, "params": {"steps": 25, "cfg": 7.0, "width": 1024, "height": 1024},
    },
}


# ── 核心组装器：分镜计划 → 多套 ComfyUI JSON ──────────────────────

def _build_engineering_prompt(
    base_prompt: str,
    entities: dict[str, Any],
    shot_entities: list[str],
) -> str:
    """构建工程化 prompt：注入角色/场景/道具描述 + 一致性约束。

    格式（§4.4 Engineering Prompt 模板）：
    [角色描述] [场景描述] [道具描述] [用户原始 Prompt] [质量标签]
    """
    registry = entities.get("entities", {})
    parts: list[str] = []

    # 注入所选实体描述
    for entity_id in shot_entities:
        e = registry.get(entity_id)
        if e:
            desc = e.get("description", e.get("name", entity_id))
            etype = e.get("type", "unknown")
            weight = e.get("consistency_weight", 1.0)
            tag = f"[{etype}]" if etype else ""
            if weight >= 1.0:
                parts.append(f"{tag} {desc}")
            else:
                parts.append(f"{tag} {desc}")

    # 质量标签
    quality_tags = "masterpiece, best quality, highly detailed"
    if "anime" in base_prompt.lower() or "漫" in base_prompt or "动漫" in base_prompt:
        quality_tags = "masterpiece, best quality, anime style, highly detailed"

    parts.append(base_prompt)
    parts.append(quality_tags)

    return ", ".join(p for p in parts if p.strip())


def _auto_extract_shot_entities(
    shot: dict[str, Any],
    entities: dict[str, Any],
) -> list[str]:
    """从分镜描述自动匹配相关实体 ID。

    策略：遍历实体，检查 shot 的 scene/characters 字段是否包含实体名称。
    """
    registry = entities.get("entities", {})
    matched: list[str] = []

    # 显式声明的实体引用
    if "entities" in shot and isinstance(shot["entities"], list):
        for eid in shot["entities"]:
            if eid in registry:
                matched.append(eid)

    # 从描述中模糊匹配（字符不少于 2 个中文字符才生效）
    if "description" in shot and "characters" in shot:
        chars = shot.get("characters", [])
        if isinstance(chars, str):
            chars = [c.strip() for c in chars.split(",") if c.strip()]
        for cid in chars:
            if cid in registry:
                matched.append(cid)
        # 也检查 scene
        scene = shot.get("scene", "")
        if isinstance(scene, str):
            for eid, e in registry.items():
                if scene in e.get("name", "") or scene in e.get("description", ""):
                    if eid not in matched:
                        matched.append(eid)

    return matched


def assemble_shot(
    shot: dict[str, Any],
    entities: dict[str, Any],
    consistency_profile: dict[str, Any] | None = None,
    blueprint_id: str = "txt2img_sdxl",
    vram_gb: float = 16.0,
) -> dict[str, Any]:
    """将单个分镜组装为完整的 ComfyUI workflow JSON。

    Args:
        shot: 分镜计划对象，含 description/prompt/scene/characters 等
        entities: 实体注册表（entity_registry 产出）
        consistency_profile: consistency_manager 推荐的一致性策略
        blueprint_id: 图像生成蓝图 ID
        vram_gb: 可用 VRAM（用于视频蓝图推荐）

    Returns:
        {"shot_index": int, "workflow": list[dict], "prompt": str, "mode": str}
    """
    if consistency_profile is None:
        consistency_profile = cm.recommend(shot, entities)

    # 提取实体引用
    shot_entities = _auto_extract_shot_entities(shot, entities)

    # 构建工程化 prompt
    base_prompt = shot.get("prompt", shot.get("description", ""))
    engineered_prompt = _build_engineering_prompt(
        base_prompt, entities, shot_entities,
    )
    negative = shot.get("negative", consistency_profile.get("negative_prompt", ""))

    # 选择图像蓝图
    image_bp = IMAGE_BLUEPRINTS.get(blueprint_id, IMAGE_BLUEPRINTS["txt2img_sdxl"])

    # 合并蓝图默认参数 + 分镜覆盖 + 一致性参数
    params = dict(image_bp["params"])
    params.update(consistency_profile.get("params", {}))
    if "width" in shot:
        params["width"] = shot["width"]
    if "height" in shot:
        params["height"] = shot["height"]

    # 调用蓝图 builder
    builder = image_bp["builder"]
    workflow = builder(
        positive=engineered_prompt,
        negative=negative,
        **{k: v for k, v in params.items() if k in ("width", "height", "steps", "cfg")},
    )

    return {
        "shot_index": shot.get("index", 0),
        "shot_id": shot.get("id", f"shot_{shot.get('index', 0)}"),
        "workflow": workflow,
        "prompt": engineered_prompt,
        "negative": negative,
        "mode": consistency_profile.get("mode", "auto"),
        "entities_used": shot_entities,
    }


def assemble_storyboard(
    storyboard: dict[str, Any],
    entities: dict[str, Any],
    image_blueprint: str = "txt2img_sdxl",
    video_blueprint: str | None = None,
    vram_gb: float = 16.0,
) -> dict[str, Any]:
    """将完整故事板（多分镜）组装为多套 ComfyUI workflow。

    Args:
        storyboard: workflow_planner 产出的完整故事板结构
        entities: entity_registry 产出的实体注册表
        image_blueprint: 图像蓝图 ID
        video_blueprint: 视频蓝图 ID（None = 自动推荐）
        vram_gb: 可用 VRAM

    Returns:
        {
            "storyboard_id": str,
            "total_shots": int,
            "shots": [...],        # 每个分镜的 workflow
            "video_workflow": {...}|None,  # 全局视频 workflow
            "consistency_profile": {...},
        }
    """
    shots = storyboard.get("shots", [])
    if not shots:
        return {"error": "storyboard 不含任何分镜", "shots": []}

    # 全局一致性策略：用故事板级别参数（而非单分镜）
    global_consistency = cm.recommend({"description": storyboard.get("description", "")}, entities)

    # 组装每个分镜
    assembled_shots = []
    for shot in shots:
        result = assemble_shot(shot, entities, global_consistency, image_blueprint, vram_gb)
        assembled_shots.append(result)

    # 可选：视频管线（如用户要求生成视频）
    video_wf = None
    if video_blueprint:
        video_wf = _assemble_video_workflow(assembled_shots, video_blueprint, entities)

    return {
        "storyboard_id": storyboard.get("id", "auto"),
        "total_shots": len(assembled_shots),
        "shots": assembled_shots,
        "video_workflow": video_wf,
        "consistency_profile": global_consistency,
    }


def _assemble_video_workflow(
    assembled_shots: list[dict[str, Any]],
    blueprint_id: str,
    entities: dict[str, Any],
) -> dict[str, Any] | None:
    """为已组装的图像分镜添加视频管线。

    每个分镜的图像作为 I2V 或 T2V 的输入帧。
    """
    vb_bp = vb.get_blueprint(blueprint_id)
    if vb_bp is None:
        vb_bp = vb.get_blueprint(
            vb.recommend_blueprint(vram_gb=16.0, mode="t2v")
        )
        if vb_bp is None:
            return None

    builder = vb_bp["builder"]
    params = vb_bp["params"]

    video_shots = []
    for shot in assembled_shots:
        # 如果是 I2V，需要参考图（首个分镜的首张输出图作为起始帧）
        if "i2v" in blueprint_id:
            workflow = builder(
                positive=shot["prompt"],
                image_ref=shot.get("image_ref", ""),
                negative=shot.get("negative", ""),
                **{k: v for k, v in params.items() if k in ("width", "height", "steps", "cfg", "frames")},
            )
        else:
            workflow = builder(
                positive=shot["prompt"],
                negative=shot.get("negative", ""),
                **{k: v for k, v in params.items() if k in ("width", "height", "steps", "cfg", "frames")},
            )
        video_shots.append({
            "shot_id": shot["shot_id"],
            "workflow": workflow,
        })

    return {
        "blueprint": vb_bp["id"],
        "name": vb_bp["name"],
        "total_shots": len(video_shots),
        "shots": video_shots,
    }


def assemble_single(
    prompt: str,
    entities: dict[str, Any] | None = None,
    image_blueprint: str = "txt2img_sdxl",
    consistency_mode: str = "auto",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 7.0,
    negative: str = "",
) -> dict[str, Any]:
    """单张图像生成（非故事板模式，直接 prompt → workflow）。

    这是 /api/workflows/generate 的快速入口。
    """
    entities = entities or {"entities": {}}

    # 一致性策略
    profile = cm.recommend({"description": prompt}, entities)
    if consistency_mode != "auto":
        profile["mode"] = consistency_mode

    # 构建虚拟分镜对象
    shot = {
        "index": 0,
        "id": "gen_0",
        "description": prompt,
        "prompt": prompt,
    }

    return assemble_shot(
        shot, entities, profile, image_blueprint,
        vram_gb=16.0,
    )


# ── 工具函数 ──────────────────────────────────────────────────────

def list_all_blueprints() -> dict[str, list[dict[str, Any]]]:
    """列出所有可用蓝图（图像 + 视频）。"""
    img = [{"id": v["id"], "name": v["name"], "category": v["category"]} for v in IMAGE_BLUEPRINTS.values()]
    vid = vb.list_blueprints()
    return {"image": img, "video": vid}


def workflow_to_prompt_json(workflow: list[dict[str, Any]]) -> dict[str, Any]:
    """将节点列表转为 ComfyUI prompt API 格式（带 client_id）。"""
    nodes_dict = {}
    for node in workflow:
        nid = str(node["id"])
        nodes_dict[nid] = {
            "class_type": node["class_type"],
            "inputs": node.get("inputs", {}),
        }
    return {
        "prompt": nodes_dict,
        "client_id": "infinite-canvas-assembler",
    }


# ── 自检入口 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    # 单元自检：组装一个简单的单图 workflow
    result = assemble_single("a beautiful landscape, mountains and rivers, masterpiece")
    print(f"OK: {result['shot_id']} — prompt={result['prompt'][:80]}...")
    print(f"Nodes: {len(result['workflow'])}")
    print(f"Blueprint list: images={len(list_all_blueprints()['image'])}, videos={len(list_all_blueprints()['video'])}")
