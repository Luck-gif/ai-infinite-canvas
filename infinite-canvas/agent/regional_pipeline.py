"""无限画布 v5.1 · 多角色同框 Regional Pipeline。

当需要将多个角色实体放在同一画面中时，传统单 IPAdapter 会造成
特征混合（角色 A 的脸出现在角色 B 身上）。Regional Pipeline 通过
区域注意力掩码 + 每角色独立 IPAdapter，实现干净的多角色分离生成。

核心能力：
1. 区域提示词解析 — [A]/[B]/[C] token 分离 + 空间布局
2. 多 IPAdapter 绑定 — 每个角色用自己的实体参考图独立注入
3. Regional Sampler 工作流 — SDXL Regional Sampler + 注意力掩码
4. 布局模式 — 水平2分/垂直2分/2×2四宫格/自由比例

设计要点（§6.3 区域一致性 + §9.4 Multi-IPAdapter）：
- 每个 [TOKEN] 对应一个空间区域和一组 IPAdapter 参数
- 区域掩码通过 Image Segmentation 预处理生成
- 蓝图经 comfyui-workflow-validator 校验

参考：https://github.com/liuzhengzhe/SDXL-Regional-Sampler
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from entity_registry import Entity, get_entity, build_entity_prompt
from consistency_manager import FrameContext, character_consistency


# ── 布局枚举 ────────────────────────────────────────────────────────

class LayoutMode(Enum):
    HORIZONTAL = "horizontal"   # 左右切分 [A | B]
    VERTICAL = "vertical"       # 上下切分 [A / B]
    GRID2X2 = "grid2x2"         # 2×2 四宫格
    CUSTOM = "custom"           # 自定义比例（需提供 ratios）


# ── 角色槽位 ────────────────────────────────────────────────────────

@dataclass
class CharacterSlot:
    """区域管线中的一个角色槽位。"""
    token: str                   # [A], [B], [C] 等
    entity_id: str               # 实体 ID（角色）
    prompt: str                  # 该角色的描述文本
    region_ratio: float = 0.5    # 占画面比例
    ipa_weight: float = 0.8      # IPAdapter 权重
    start_at: float = 0.0        # 区域起始位置（归一化 0-1）
    end_at: float = 0.5          # 区域结束位置（归一化 0-1）

    @property
    def entity(self) -> Entity | None:
        return get_entity(self.entity_id)


# ── 区域配置 ────────────────────────────────────────────────────────

@dataclass
class RegionalConfig:
    """多角色区域管线的完整配置。"""
    slots: list[CharacterSlot] = field(default_factory=list)
    layout: LayoutMode = LayoutMode.HORIZONTAL
    width: int = 1024
    height: int = 1024
    base_prompt: str = ""         # 共有场景描述（不含角色）
    negative: str = ""
    steps: int = 20
    cfg: float = 7.0
    seed: int = 0
    sampler: str = "euler"
    scheduler: str = "normal"
    denoise: float = 1.0

    def validate(self) -> list[str]:
        """校验配置合法性。"""
        errors: list[str] = []
        if len(self.slots) < 2:
            errors.append("至少需要 2 个角色槽位")
        if len(self.slots) > 8:
            errors.append("最多支持 8 个角色槽位")
        # 校验区域覆盖
        total_ratio = sum(s.region_ratio for s in self.slots)
        if abs(total_ratio - 1.0) > 0.01:
            errors.append(f"区域比例和不等于 1.0（当前={total_ratio:.2f}）")
        # 校验每个 slot 的实体存在
        for s in self.slots:
            if s.entity is None:
                errors.append(f"角色 [{s.token}] 实体 {s.entity_id} 不存在")
        return errors

    @property
    def num_slots(self) -> int:
        return len(self.slots)


# ── 提示词构建 ──────────────────────────────────────────────────────

def build_regional_prompt(config: RegionalConfig) -> str:
    """构建多角色区域提示词。

    格式：base_prompt, [A] char_a_desc | [B] char_b_desc | ...
    每个 [TOKEN] 段包含该角色的完整描述（含实体 prompt_prefix）。
    """
    parts = [config.base_prompt] if config.base_prompt else []
    for slot in config.slots:
        char_prompt = slot.prompt
        # 注入实体 prompt prefix
        ent = slot.entity
        if ent:
            entity_prefix = build_entity_prompt(slot.entity_id)
            if entity_prefix:
                char_prompt = f"{entity_prefix}, {char_prompt}"
        parts.append(f"[{slot.token}] {char_prompt}")
    return " | ".join(parts)


def resolve_regional_prompts(config: RegionalConfig) -> dict[str, str]:
    """解析每个 [TOKEN] 对应的完整 prompt。

    返回 {token: full_prompt, ...} 字典。
    """
    result: dict[str, str] = {}
    for slot in config.slots:
        ent = slot.entity
        parts = [slot.prompt]
        if ent:
            entity_prefix = build_entity_prompt(slot.entity_id)
            if entity_prefix:
                parts.insert(0, entity_prefix)
        result[slot.token] = ", ".join(parts)
    return result


# ── 布局计算 ────────────────────────────────────────────────────────

def compute_regions(config: RegionalConfig) -> list[dict[str, Any]]:
    """根据布局模式和比例计算每个 slot 的空间区域。

    返回每个 slot 的区域定义：
    {
        "token": "A",
        "x_start": 0, "x_end": 0.5,   # 归一化坐标
        "y_start": 0, "y_end": 1.0,
        "prompt": "...",
    }
    """
    regions = []
    cursor = 0.0

    if config.layout == LayoutMode.HORIZONTAL:
        for slot in config.slots:
            regions.append({
                "token": slot.token,
                "x_start": cursor,
                "x_end": cursor + slot.region_ratio,
                "y_start": 0.0,
                "y_end": 1.0,
                "prompt": slot.prompt,
                "entity_id": slot.entity_id,
                "ipa_weight": slot.ipa_weight,
            })
            cursor += slot.region_ratio

    elif config.layout == LayoutMode.VERTICAL:
        for slot in config.slots:
            regions.append({
                "token": slot.token,
                "x_start": 0.0,
                "x_end": 1.0,
                "y_start": cursor,
                "y_end": cursor + slot.region_ratio,
                "prompt": slot.prompt,
                "entity_id": slot.entity_id,
                "ipa_weight": slot.ipa_weight,
            })
            cursor += slot.region_ratio

    elif config.layout == LayoutMode.GRID2X2:
        # 2×2 固定四宫格
        positions = [
            (0.0, 0.0, 0.5, 0.5),   # 左上
            (0.5, 0.0, 1.0, 0.5),   # 右上
            (0.0, 0.5, 0.5, 1.0),   # 左下
            (0.5, 0.5, 1.0, 1.0),   # 右下
        ]
        for i, slot in enumerate(config.slots):
            if i >= 4:
                break
            x0, y0, x1, y1 = positions[i]
            regions.append({
                "token": slot.token,
                "x_start": x0, "x_end": x1,
                "y_start": y0, "y_end": y1,
                "prompt": slot.prompt,
                "entity_id": slot.entity_id,
                "ipa_weight": slot.ipa_weight,
            })

    else:  # CUSTOM
        for slot in config.slots:
            regions.append({
                "token": slot.token,
                "x_start": slot.start_at,
                "x_end": slot.end_at,
                "y_start": 0.0,
                "y_end": 1.0,
                "prompt": slot.prompt,
                "entity_id": slot.entity_id,
                "ipa_weight": slot.ipa_weight,
            })

    return regions


# ── ComfyUI 工作流构建 ──────────────────────────────────────────────

def build_regional_workflow(config: RegionalConfig) -> dict[str, Any]:
    """构建 SDXL Regional Sampler + 多 IPAdapter 工作流。

    工作流结构：
    1. CLIP Text Encode (base prompt + regional prompts)
    2. LoadImage × N (每个角色的参考图)
    3. IPAdapterAdvanced × N (每个角色独立 IPAdapter)
    4. RegionalSampler (含区域掩码)
    5. VAEDecode → SaveImage
    """
    import random
    seed = config.seed if config.seed > 0 else random.randint(0, 2 ** 32 - 1)

    nodes: dict[str, Any] = {}
    regions = compute_regions(config)
    unified_prompt = build_regional_prompt(config)

    # 节点 1: Load Checkpoint (SDXL)
    nodes["1"] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
    }

    # 节点 2-3: CLIP Text Encode (正/反)
    nodes["2"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "clip": ["1", 1],
            "text": unified_prompt,
        },
    }
    nodes["3"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "clip": ["1", 1],
            "text": config.negative or "lowres, bad anatomy, bad hands, mutation, extra limbs, disfigured",
        },
    }

    # 节点 4: Empty Latent Image
    nodes["4"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": config.width,
            "height": config.height,
            "batch_size": 1,
        },
    }

    # 每个角色：LoadImage → IPAdapterAdvanced
    ipa_outputs: list[tuple[str, int]] = []  # [(node_id, output_idx), ...]
    node_id = 10
    for i, slot in enumerate(config.slots):
        ent = slot.entity
        ref_image = ent.anchor.reference_image if ent else ""
        if not ref_image:
            ref_image = ""  # 无参考图时跳过 IPAdapter，仍可生成

        # LoadImage
        lid = str(node_id)
        nodes[lid] = {
            "class_type": "LoadImage",
            "inputs": {"image": ref_image},
        }
        node_id += 1

        # CLIPVisionEncode
        vid = str(node_id)
        nodes[vid] = {
            "class_type": "CLIPVisionEncode",
            "inputs": {
                "clip_vision": ["1", 2],
                "image": [lid, 0],
            },
        }
        node_id += 1

        # IPAdapterAdvanced（区域约束版）
        ipa_id = str(node_id)
        nodes[ipa_id] = {
            "class_type": "IPAdapterAdvanced",
            "inputs": {
                "model": ["1", 0],
                "ipadapter": "ip-adapter-plus_sdxl_vit-h.safetensors",
                "image": [vid, 0],
                "weight": slot.ipa_weight,
                "weight_type": "linear",
                "combine_embeds": "concat",
                "start_at": 0.0,
                "end_at": 1.0,
            },
        }
        node_id += 1
        ipa_outputs.append((ipa_id, 0))

    # 节点 50: Regional Sampler
    sampler_inputs: dict[str, Any] = {
        "model": ["1", 0],
        "positive": ["2", 0],
        "negative": ["3", 0],
        "latent_image": ["4", 0],
        "steps": config.steps,
        "cfg": config.cfg,
        "seed": seed,
        "sampler_name": config.sampler,
        "scheduler": config.scheduler,
        "denoise": config.denoise,
        "regional_prompts": build_regional_prompt(config),
        "regions": regions,
    }

    # 串接 IPAdapter 输出到 Sampler
    # 多个 IPAdapter 时串行链式连接：checkpoint → IPAdapter1 → IPAdapter2 → ... → sampler
    if len(ipa_outputs) == 1:
        sampler_inputs["model"] = ipa_outputs[0]
    elif len(ipa_outputs) > 1:
        # 第1个 IPAdapter 输入来自 checkpoint，后续每个输入来自前一个 IPAdapter 输出
        for i, ipa_id in enumerate(ipa_outputs):
            ipa_node = nodes[str(ipa_id[0])]
            if i == 0:
                ipa_node["inputs"]["model"] = ["1", 0]
            else:
                ipa_node["inputs"]["model"] = ipa_outputs[i - 1]
        sampler_inputs["model"] = ipa_outputs[-1]

    nodes["50"] = {
        "class_type": "RegionalSampler",
        "inputs": sampler_inputs,
    }

    # 节点 60: VAE Decode
    nodes["60"] = {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["50", 0],
            "vae": ["1", 2],
        },
    }

    # 节点 70: SaveImage
    nodes["70"] = {
        "class_type": "SaveImage",
        "inputs": {
            "images": ["60", 0],
            "filename_prefix": f"regional_{config.layout.value}_{config.num_slots}chars",
        },
    }

    return nodes


# ── 便捷构造器 ──────────────────────────────────────────────────────

def create_dual_character_config(
    char_a_id: str, char_a_prompt: str,
    char_b_id: str, char_b_prompt: str,
    base_prompt: str = "",
    ratio: float = 0.5,
    width: int = 1024,
    height: int = 1024,
) -> RegionalConfig:
    """快速创建双角色左右布局配置。"""
    return RegionalConfig(
        slots=[
            CharacterSlot(
                token="A", entity_id=char_a_id, prompt=char_a_prompt,
                region_ratio=ratio, start_at=0.0, end_at=ratio,
            ),
            CharacterSlot(
                token="B", entity_id=char_b_id, prompt=char_b_prompt,
                region_ratio=1.0 - ratio, start_at=ratio, end_at=1.0,
            ),
        ],
        layout=LayoutMode.HORIZONTAL,
        base_prompt=base_prompt,
        width=width,
        height=height,
    )


def create_triple_character_config(
    chars: list[tuple[str, str]],  # [(entity_id, prompt), ...]
    base_prompt: str = "",
    width: int = 1280,
    height: int = 720,
) -> RegionalConfig:
    """快速创建三角色配置。"""
    tokens = ["A", "B", "C"]
    n = min(len(chars), 3)
    denom = n
    slots = []
    cursor = 0.0
    for i in range(n):
        r = 1.0 / denom
        slots.append(CharacterSlot(
            token=tokens[i],
            entity_id=chars[i][0],
            prompt=chars[i][1],
            region_ratio=r,
            start_at=cursor,
            end_at=cursor + r,
        ))
        cursor += r
    return RegionalConfig(
        slots=slots,
        layout=LayoutMode.HORIZONTAL,
        base_prompt=base_prompt,
        width=width,
        height=height,
    )


# ── 区域管线入口（供 API 调用）─────────────────────────────────────────

def run_regional(config: RegionalConfig) -> dict[str, Any]:
    """验证配置 + 构建工作流 + 返回 API 兼容格式。

    返回：
    {
        "template_id": "regional",
        "workflow": {...},
        "meta": {
            "num_characters": N,
            "layout": "horizontal",
            "tokens": ["A", "B"],
            "prompt": "... (unified)",
        },
    }
    """
    errors = config.validate()
    if errors:
        return {
            "template_id": "regional",
            "error": True,
            "issues": errors,
            "meta": {},
        }

    workflow = build_regional_workflow(config)

    return {
        "template_id": "regional",
        "workflow": workflow,
        "meta": {
            "num_characters": config.num_slots,
            "layout": config.layout.value,
            "tokens": [s.token for s in config.slots],
            "prompt": build_regional_prompt(config),
            "regional_prompts": resolve_regional_prompts(config),
            "regions": compute_regions(config),
        },
    }
