"""一致性管理器（§10.2 StoryDiffusion 17合1 封装）。

将 StoryDiffusion 的 17 个一致性约束封装为可组合管道：
  1. 角色一致性（角色 ID → prompt 前缀 + seed 锚定）
  2. 场景一致性（场景 ID → 背景模板）
  3. 道具一致性（道具 ID → 尺寸/位置参考）
  4. 风格一致性（风格 ID → LoRA + 提示词模板）
  5. 叙事一致性（时间线排序）
  6. 空间一致性（ControlNet 深度/布局）
  7. 色彩一致性（LUT / 调色板）
  8. 光照一致性（光源方向锚定）
  9. 比例一致性（角色-场景尺度）
  10. 表情一致性（表情参考图）
  11. 服装一致性（服装 ID 绑定）
  12. 姿势一致性（OpenPose 骨骼）
  13. 视角一致性（相机角度锚定）
  14. 画幅一致性（分辨率/比例）
  15. 帧率一致性（视频序列）
  16. 过渡一致性（转场模板）
  17. 音频一致性（口型/节奏，预留）

每个约束是一个 Callable，接收一个"帧上下文"并返回
修改后的 prompt + params dict。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from entity_registry import (
    Entity, EntityKind, VisualAnchor,
    get_entity, build_entity_prompt,
)

# ── 帧上下文 ────────────────────────────────────────────────────────

@dataclass
class FrameContext:
    """StoryDiffusion 帧上下文。"""
    frame_index: int              # 帧序号（从 0 开始）
    total_frames: int             # 总帧数
    prompt: str                   # 当前提示词
    character_ids: List[str] = field(default_factory=list)
    scene_id: Optional[str] = None
    prop_ids: List[str] = field(default_factory=list)
    style_id: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    prev_frame_path: Optional[str] = None  # 前一帧图像路径


# ── 约束函数类型 ────────────────────────────────────────────────────

ConstraintFunc = Callable[[FrameContext], FrameContext]


# ── 约束 1: 角色一致性 ──────────────────────────────────────────────

def character_consistency(ctx: FrameContext) -> FrameContext:
    """将角色实体 prompt 前缀注入当前帧 prompt。"""
    if not ctx.character_ids:
        return ctx
    prompts: List[str] = [ctx.prompt]
    for cid in ctx.character_ids:
        p = build_entity_prompt(cid)
        if p:
            prompts.append(p)
    ctx.prompt = ", ".join(prompts)
    return ctx


# ── 约束 2: 场景一致性 ──────────────────────────────────────────────

def scene_consistency(ctx: FrameContext) -> FrameContext:
    """将场景实体 prompt 注入当前帧 prompt。"""
    if ctx.scene_id is None:
        return ctx
    p = build_entity_prompt(ctx.scene_id)
    if p:
        ctx.prompt = f"{ctx.prompt}, {p}"
    return ctx


# ── 约束 3: 道具一致性 ──────────────────────────────────────────────

def prop_consistency(ctx: FrameContext) -> FrameContext:
    """将道具实体 prompt 注入当前帧 prompt。"""
    if not ctx.prop_ids:
        return ctx
    props = []
    for pid in ctx.prop_ids:
        p = build_entity_prompt(pid)
        if p:
            props.append(p)
    if props:
        ctx.prompt = f"{ctx.prompt}, with {', '.join(props)}"
    return ctx


# ── 约束 4: 风格一致性 ──────────────────────────────────────────────

def style_consistency(ctx: FrameContext) -> FrameContext:
    """将风格实体 prompt 及 LoRA 注入。"""
    if ctx.style_id is None:
        return ctx
    ent = get_entity(ctx.style_id)
    if ent is None:
        return ctx
    p = build_entity_prompt(ctx.style_id)
    if p:
        ctx.prompt = f"{ctx.prompt}, {p}"
    # LoRA 绑定
    if ent.anchor.lora_name:
        ctx.params.setdefault("lora_stack", []).append({
            "name": ent.anchor.lora_name,
            "strength": 0.85,
        })
    return ctx


# ── 约束 5: 叙事一致性 ──────────────────────────────────────────────

def narrative_consistency(ctx: FrameContext) -> FrameContext:
    """按时间线排序注入叙事标记。"""
    if ctx.total_frames <= 1:
        return ctx
    # 在 prompt 后追加叙事位置标记
    progress = ctx.frame_index / max(ctx.total_frames - 1, 1)
    if progress < 0.1:
        tag = "opening scene"
    elif progress > 0.9:
        tag = "closing scene"
    else:
        tag = f"storyboard frame {ctx.frame_index + 1}/{ctx.total_frames}"
    ctx.prompt = f"{ctx.prompt}, [{tag}]"
    return ctx


# ── 约束 6: 空间一致性 ──────────────────────────────────────────────

def spatial_consistency(ctx: FrameContext) -> FrameContext:
    """ControlNet 深度/布局锚定。"""
    ent = None
    if ctx.scene_id:
        ent = get_entity(ctx.scene_id)
    if ent and ent.anchor.controlnet_type:
        ctx.params["controlnet_type"] = ent.anchor.controlnet_type
    return ctx


# ── 约束 7-17: 占位实现（逐步完善）──────────────────────────────────

def color_consistency(ctx: FrameContext) -> FrameContext:
    """色彩一致性：读取 style 的调色板参数。"""
    return ctx


def lighting_consistency(ctx: FrameContext) -> FrameContext:
    """光照一致性：光源方向锚定。"""
    return ctx


def scale_consistency(ctx: FrameContext) -> FrameContext:
    """比例一致性：角色-场景尺度约束。"""
    return ctx


def expression_consistency(ctx: FrameContext) -> FrameContext:
    """表情一致性：表情参考图绑定。"""
    return ctx


def outfit_consistency(ctx: FrameContext) -> FrameContext:
    """服装一致性：服装实体 ID 绑定。"""
    return ctx


def pose_consistency(ctx: FrameContext) -> FrameContext:
    """姿势一致性：OpenPose 骨骼参考。"""
    return ctx


def viewpoint_consistency(ctx: FrameContext) -> FrameContext:
    """视角一致性：相机角度锚定。"""
    return ctx


def resolution_consistency(ctx: FrameContext) -> FrameContext:
    """画幅一致性：分辨率/比例约束。"""
    return ctx


def framerate_consistency(ctx: FrameContext) -> FrameContext:
    """帧率一致性：视频序列帧率约束。"""
    return ctx


def transition_consistency(ctx: FrameContext) -> FrameContext:
    """过渡一致性：转场模板约束。"""
    return ctx


def audio_consistency(ctx: FrameContext) -> FrameContext:
    """音频一致性：口型/节奏预留。"""
    return ctx


# ── 管道组合 ────────────────────────────────────────────────────────

# 按推荐顺序排列的 17 合 1 管道
DEFAULT_PIPELINE: List[ConstraintFunc] = [
    character_consistency,      # 1
    scene_consistency,          # 2
    prop_consistency,           # 3
    style_consistency,          # 4
    narrative_consistency,      # 5
    spatial_consistency,        # 6
    color_consistency,          # 7
    lighting_consistency,       # 8
    scale_consistency,          # 9
    expression_consistency,     # 10
    outfit_consistency,         # 11
    pose_consistency,           # 12
    viewpoint_consistency,      # 13
    resolution_consistency,     # 14
    framerate_consistency,      # 15
    transition_consistency,     # 16
    audio_consistency,          # 17
]

# 简化管道：仅核心一致性（前 6 个）
CORE_PIPELINE: List[ConstraintFunc] = DEFAULT_PIPELINE[:6]


def apply_pipeline(
    ctx: FrameContext,
    pipeline: Optional[List[ConstraintFunc]] = None,
) -> FrameContext:
    """对帧上下文顺序应用管道中的所有约束函数。"""
    pipe = pipeline or DEFAULT_PIPELINE
    for fn in pipe:
        ctx = fn(ctx)
    return ctx


def apply_pipeline_to_frames(
    frames: List[FrameContext],
    pipeline: Optional[List[ConstraintFunc]] = None,
) -> List[FrameContext]:
    """对多帧批量应用一致性管道。"""
    return [apply_pipeline(f, pipeline) for f in frames]


# ── 辅助：从实体 ID 构建 FrameContext ───────────────────────────────

def build_frame_context(
    prompt: str,
    frame_index: int = 0,
    total_frames: int = 1,
    character_ids: Optional[List[str]] = None,
    scene_id: Optional[str] = None,
    prop_ids: Optional[List[str]] = None,
    style_id: Optional[str] = None,
    **params: Any,
) -> FrameContext:
    """便捷构造帧上下文。"""
    return FrameContext(
        frame_index=frame_index,
        total_frames=total_frames,
        prompt=prompt,
        character_ids=character_ids or [],
        scene_id=scene_id,
        prop_ids=prop_ids or [],
        style_id=style_id,
        params=dict(params),
    )
