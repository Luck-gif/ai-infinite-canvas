"""工作流规划器（§10.3 多帧规划引擎）。

根据用户意图和实体注册表，自动生成 StoryDiffusion 分镜计划：
  1. 解析叙事结构（起承转合 / 用户指定的帧数）
  2. 为每帧分配角色、场景、道具、风格
  3. 输出 FramePlan 列表供 consistency_manager 消费
  4. 可选：生成工作流 JSON 直接提交 ComfyUI

Plan 生成过程：
  叙事意图 → 分镜划分 → 实体映射 → FrameContext[] → pipeline → workflows
"""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import entity_registry as er
import consistency_manager as cm
import intent_map as im


# ── 枚举 ────────────────────────────────────────────────────────────

class StoryStructure(str, Enum):
    """叙事结构模板。"""
    THREE_ACT = "three_act"       # 三幕式（开场-冲突-结局）
    FIVE_ACT = "five_act"         # 五幕式（起-承-转-合-结）
    LINEAR = "linear"             # 线性叙事（均匀划分）
    SINGLE = "single"             # 单帧


class FrameRole(str, Enum):
    """分镜角色标注。"""
    OPENING = "opening"           # 开场
    DEVELOPMENT = "development"   # 发展
    CONFLICT = "conflict"         # 冲突/转折
    CLIMAX = "climax"             # 高潮
    RESOLUTION = "resolution"     # 结局
    TRANSITION = "transition"     # 过渡


# ── 数据类 ──────────────────────────────────────────────────────────

@dataclass
class FramePlan:
    """单帧分镜计划。"""
    frame_index: int
    frame_role: FrameRole
    prompt_template: str           # 本帧 prompt 模板（{character} 等占位）
    character_ids: list[str] = field(default_factory=list)
    scene_id: str | None = None
    prop_ids: list[str] = field(default_factory=list)
    style_id: str | None = None
    duration_sec: float = 1.0      # 默认帧时长（视频模式）
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class StoryboardPlan:
    """完整分镜计划。"""
    plan_id: str
    story_structure: StoryStructure
    total_frames: int
    frames: list[FramePlan]
    global_style_id: str | None = None
    global_scene_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


# ── 工具函数 ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── 叙事结构 → 帧角色序列 ───────────────────────────────────────────

_STRUCTURE_ROLES: dict[StoryStructure, list[FrameRole]] = {
    StoryStructure.THREE_ACT: [
        FrameRole.OPENING,
        FrameRole.CONFLICT,
        FrameRole.RESOLUTION,
    ],
    StoryStructure.FIVE_ACT: [
        FrameRole.OPENING,
        FrameRole.DEVELOPMENT,
        FrameRole.CONFLICT,
        FrameRole.CLIMAX,
        FrameRole.RESOLUTION,
    ],
    StoryStructure.LINEAR: [],   # 动态生成
    StoryStructure.SINGLE: [FrameRole.OPENING],
}


def _role_to_prompt_template(role: FrameRole) -> str:
    """根据帧角色返回默认 prompt 模板。"""
    templates = {
        FrameRole.OPENING: "establishing shot, wide angle, {description}",
        FrameRole.DEVELOPMENT: "medium shot, narrative progression, {description}",
        FrameRole.CONFLICT: "dramatic tension, dynamic composition, {description}",
        FrameRole.CLIMAX: "epic scene, intense action, dramatic lighting, {description}",
        FrameRole.RESOLUTION: "peaceful resolution, warm atmosphere, {description}",
        FrameRole.TRANSITION: "smooth transition, motion blur, {description}",
    }
    return templates.get(role, "{description}")


# ── 主函数：生成分镜计划 ────────────────────────────────────────────

def plan_storyboard(
    intent: dict[str, Any],
    *,
    total_frames: int | None = None,
    structure: StoryStructure | None = None,
    character_ids: list[str] | None = None,
    scene_id: str | None = None,
    prop_ids: list[str] | None = None,
    style_id: str | None = None,
    description: str = "",
) -> StoryboardPlan:
    """根据用户意图生成分镜计划。

    Args:
        intent: 意图解析结果（来自 /api/intent 或 intent_map）
        total_frames: 总帧数（覆盖自动推断）
        structure: 叙事结构（覆盖自动推断）
        character_ids: 角色实体 ID 列表
        scene_id: 场景实体 ID
        prop_ids: 道具实体 ID 列表
        style_id: 风格实体 ID
        description: 叙事描述

    Returns:
        StoryboardPlan 包含每帧的 FramePlan
    """
    # 1. 确定结构
    story = structure or _infer_structure(intent)
    n_frames = total_frames or _infer_frame_count(intent, story)

    # 2. 生成帧角色序列
    roles = _generate_role_sequence(story, n_frames)

    # 3. 为每帧分配描述（简易版：按角色分配叙事标记）
    frame_descriptions = _generate_frame_descriptions(
        description, roles, n_frames)

    # 4. 构建 FramePlan 列表
    frames: list[FramePlan] = []
    chars = character_ids or []
    props = prop_ids or []
    scene = scene_id
    style = style_id

    for i, role in enumerate(roles):
        fp = FramePlan(
            frame_index=i,
            frame_role=role,
            prompt_template=_role_to_prompt_template(role).format(
                description=frame_descriptions[i]),
            character_ids=chars,
            scene_id=scene,
            prop_ids=props,
            style_id=style,
            duration_sec=1.0,
        )
        frames.append(fp)

    plan = StoryboardPlan(
        plan_id=uuid.uuid4().hex[:12],
        story_structure=story,
        total_frames=n_frames,
        frames=frames,
        global_style_id=style,
        global_scene_id=scene,
        metadata={"intent_action": intent.get("action", "")},
        created_at=_now_iso(),
    )
    return plan


def _infer_structure(intent: dict[str, Any]) -> StoryStructure:
    """从意图推断叙事结构。"""
    action = intent.get("action", "")
    params = intent.get("params", {})
    frames = params.get("frames", 1)

    if isinstance(frames, (int, float)) and frames == 1:
        return StoryStructure.SINGLE
    if action in ("story", "narrative", "sequence"):
        return StoryStructure.THREE_ACT
    if action in ("movie", "film", "video"):
        return StoryStructure.FIVE_ACT
    return StoryStructure.LINEAR


def _infer_frame_count(intent: dict[str, Any], structure: StoryStructure) -> int:
    """推断帧数。"""
    params = intent.get("params", {})
    frames = params.get("frames", 0)
    if isinstance(frames, (int, float)) and frames > 0:
        return int(frames)

    # 默认值
    defaults = {
        StoryStructure.SINGLE: 1,
        StoryStructure.THREE_ACT: 3,
        StoryStructure.FIVE_ACT: 5,
        StoryStructure.LINEAR: 4,
    }
    return defaults.get(structure, 4)


def _generate_role_sequence(
    structure: StoryStructure,
    n_frames: int,
) -> list[FrameRole]:
    """为指定帧数生成角色序列。"""
    if structure in _STRUCTURE_ROLES and len(_STRUCTURE_ROLES[structure]) == n_frames:
        return list(_STRUCTURE_ROLES[structure])

    base = _STRUCTURE_ROLES.get(structure, [])
    if not base:
        # LINEAR: 等分
        all_roles = [
            FrameRole.OPENING,
            FrameRole.DEVELOPMENT,
            FrameRole.CONFLICT,
            FrameRole.CLIMAX,
            FrameRole.RESOLUTION,
        ]
        result: list[FrameRole] = []
        for i in range(n_frames):
            idx = int(i / max(n_frames - 1, 1) * (len(all_roles) - 1))
            result.append(all_roles[min(idx, len(all_roles) - 1)])
        return result

    # 在基础角色序列中均匀插入
    if n_frames <= len(base):
        return base[:n_frames]
    # 扩展：在角色间插入 TRANSITION
    expanded: list[FrameRole] = []
    for i, role in enumerate(base):
        expanded.append(role)
        if i < len(base) - 1:
            expanded.append(FrameRole.TRANSITION)
    # 截断或填充到 n_frames
    while len(expanded) < n_frames:
        expanded.append(FrameRole.DEVELOPMENT)
    return expanded[:n_frames]


def _generate_frame_descriptions(
    description: str,
    roles: list[FrameRole],
    n_frames: int,
) -> list[str]:
    """为每帧生成简要描述。"""
    if not description:
        return [_role_to_prompt_template(r) for r in roles]

    # 简易拆分：将描述按句号分给各帧
    sentences = [s.strip() for s in description.replace("。", ".").split(".") if s.strip()]
    if not sentences:
        sentences = [description]

    result: list[str] = []
    for i in range(n_frames):
        # 轮询分配句子
        sidx = int(i / max(n_frames - 1, 1) * (len(sentences) - 1))
        result.append(sentences[min(sidx, len(sentences) - 1)])
    return result


# ── 便捷：从 plan 生成一致性上下文 ──────────────────────────────────

def plan_to_frame_contexts(
    plan: StoryboardPlan,
    pipeline: list[cm.ConstraintFunc] | None = None,
) -> list[cm.FrameContext]:
    """将 StoryboardPlan 转换为已应用一致性管道的 FrameContext 列表。"""
    contexts: list[cm.FrameContext] = []
    for fp in plan.frames:
        ctx = cm.FrameContext(
            frame_index=fp.frame_index,
            total_frames=plan.total_frames,
            prompt=fp.prompt_template,
            character_ids=fp.character_ids,
            scene_id=fp.scene_id,
            prop_ids=fp.prop_ids,
            style_id=fp.style_id or plan.global_style_id,
            params=dict(fp.params),
        )
        contexts.append(ctx)

    if pipeline is not None:
        contexts = cm.apply_pipeline_to_frames(contexts, pipeline)

    return contexts


# ── 辅助：意图驱动的自动分镜（全自动链路）───────────────────────────

def auto_plan_from_intent(
    intent: dict[str, Any],
    entity_ids: dict[str, list[str]] | None = None,
) -> StoryboardPlan:
    """全自动：意图 → 分镜计划。

    entity_ids 格式: {"character": [...], "scene": "...", "prop": [...], "style": "..."}
    """
    entity_ids = entity_ids or {}
    chars = entity_ids.get("character", [])
    scene = entity_ids.get("scene")
    props = entity_ids.get("prop", [])
    style = entity_ids.get("style")

    desc = intent.get("subject", "") or intent.get("description", "")
    if intent.get("style"):
        desc = f"{desc} in {intent['style']} style"

    return plan_storyboard(
        intent,
        character_ids=chars if isinstance(chars, list) else [chars],
        scene_id=scene,
        prop_ids=props if isinstance(props, list) else [props],
        style_id=style,
        description=desc,
    )
