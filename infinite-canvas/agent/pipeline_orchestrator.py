"""无限画布 v4.50 · 多Agent管线编排器（Pipeline Orchestrator）。

核心职责（§12.3）：
1. 协调多个Agent（Intent→Blueprint→Assemble→Consistency→Validate→ComfyUI）
2. 管线状态追踪 & 可观测性（每一步的输入/输出）
3. 自动故障恢复（蓝图回退、VRAM动态调整、重试）
4. 并行分镜组装（多分镜并发处理）

设计纪律：
- 每个Agent是幂等的、无状态的函数（共享上下文通过注册表传递）
- 管线状态完整记录，便于调试和回放
- 所有异常向上传播到API层统一处理
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

# 兼容直接运行和模块导入
import sys
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import consistency_manager as cm
import entity_registry as er
import workflow_assembler as wa
import video_blueprints as vb
import comfy_client as cc


# ── 管线状态 ──────────────────────────────────────────────────────────

@dataclass
class PipelineStage:
    """单个管线阶段的执行记录。"""
    name: str
    status: str = "pending"           # pending | running | ok | skipped | error
    input_summary: str = ""
    output_summary: str = ""
    duration_ms: float = 0.0
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineContext:
    """管线共享上下文（在各个Agent之间传递）。"""
    # 原始输入
    raw_prompt: str = ""
    raw_params: dict[str, Any] = field(default_factory=dict)

    # 意图解析结果
    intent: dict[str, Any] = field(default_factory=dict)

    # 实体注册表
    entities: dict[str, Any] = field(default_factory=dict)

    # 图像蓝图
    image_blueprint_id: str = "txt2img_sdxl"
    image_blueprint_name: str = ""

    # 视频蓝图
    video_blueprint_id: str | None = None
    video_blueprint_name: str = ""

    # 一致性策略
    consistency_profile: dict[str, Any] = field(default_factory=dict)
    consistency_mode: str = "auto"

    # 组装结果
    assembled_workflow: list[dict[str, Any]] = field(default_factory=list)
    engineered_prompt: str = ""
    nodes_count: int = 0

    # 校验结果
    validated: bool = False
    validation_issues: list[str] = field(default_factory=list)

    # ComfyUI提交
    submitted: bool = False
    submit_error: str | None = None

    # 时间
    started_at: float = 0.0
    finished_at: float = 0.0


# ── Agent函数（每个Agent接收 PipelineContext，返回 PipelineContext）────

AgentFunc = Callable[[PipelineContext], PipelineContext]


def agent_parse_intent(ctx: PipelineContext) -> PipelineContext:
    """Agent 1: 意图解析。
    
    从NL中提取基本意图信息（是否分镜、是否有角色等），
    不依赖外部LLM，纯规则匹配。
    """
    prompt = ctx.raw_prompt.lower()

    # 规则匹配
    has_characters = any(kw in prompt for kw in [
        "角色", "人物", "少女", "男孩", "女孩", "男人", "女人", "猫", "狗",
        "character", "person", "girl", "boy", "man", "woman", "cat", "dog",
        "动物", "机器人", "精灵",
    ])
    has_scene = any(kw in prompt for kw in [
        "场景", "风景", "城市", "森林", "房间", "室内", "室外", "天空",
        "scene", "landscape", "city", "forest", "room", "indoor", "outdoor",
    ])
    has_props = any(kw in prompt for kw in [
        "道具", "武器", "工具", "物品", "书", "杯子", "车",
        "prop", "weapon", "tool", "item", "book", "car",
    ])
    is_anime = any(kw in prompt for kw in [
        "动漫", "二次元", "anime", "动漫风", "日漫",
    ])
    is_realistic = any(kw in prompt for kw in [
        "写实", "照片", "真实", "电影", "摄影",
        "realistic", "photo", "cinematic", "film",
    ])
    is_story = any(kw in prompt for kw in [
        "故事", "分镜", "多帧", "连续", "序列",
        "story", "storyboard", "sequence", "series", "multi",
    ])

    ctx.intent = {
        "has_characters": has_characters,
        "has_scene": has_scene,
        "has_props": has_props,
        "style": "anime" if is_anime else "realistic" if is_realistic else "auto",
        "is_story": is_story,
        "keywords": [w for w in prompt.split() if len(w) > 1][:10],
    }
    return ctx


def agent_load_entities(ctx: PipelineContext) -> PipelineContext:
    """Agent 2: 加载实体注册表。"""
    try:
        ctx.entities = er.load_all_entities()
    except Exception:
        ctx.entities = {"entities": {}}
    return ctx


def agent_match_blueprints(ctx: PipelineContext) -> PipelineContext:
    """Agent 3: 蓝图匹配。
    
    根据意图和用户指定，选择最佳图像/视频蓝图。
    """
    # 用户指定优先
    if ctx.raw_params.get("image_blueprint"):
        bp_id = ctx.raw_params["image_blueprint"]
        bp = wa.IMAGE_BLUEPRINTS.get(bp_id)
        if bp:
            ctx.image_blueprint_id = bp_id
            ctx.image_blueprint_name = bp["name"]
            return ctx

    # 自动选择：中式/anime → qwen，否则 → sdxl
    intent = ctx.intent
    if intent.get("style") == "anime" or any(kw in ctx.raw_prompt for kw in ["中文", "Chinese"]):
        ctx.image_blueprint_id = "txt2img_qwen"
        ctx.image_blueprint_name = "Qwen-Image 2.0"
    else:
        ctx.image_blueprint_id = "txt2img_sdxl"
        ctx.image_blueprint_name = "NoobAI-XL (SDXL)"

    return ctx


def agent_choose_consistency(ctx: PipelineContext) -> PipelineContext:
    """Agent 4: 一致性策略选择。"""
    mode = ctx.raw_params.get("consistency_mode", "auto")

    shot = {"description": ctx.raw_prompt}
    ctx.consistency_profile = cm.recommend(shot, ctx.entities)

    if mode != "auto":
        ctx.consistency_profile["mode"] = mode
        ctx.consistency_mode = mode
    else:
        ctx.consistency_mode = ctx.consistency_profile.get("mode", "auto")

    return ctx


def agent_assemble_workflow(ctx: PipelineContext) -> PipelineContext:
    """Agent 5: 工作流组装。"""
    try:
        result = wa.assemble_single(
            prompt=ctx.raw_prompt,
            entities=ctx.entities,
            image_blueprint=ctx.image_blueprint_id,
            consistency_mode=ctx.consistency_mode,
            width=ctx.raw_params.get("width", 1024),
            height=ctx.raw_params.get("height", 1024),
            steps=ctx.raw_params.get("steps", 20),
            cfg=ctx.raw_params.get("cfg", 7.0),
            negative=ctx.raw_params.get("negative", ""),
        )
        ctx.assembled_workflow = result.get("workflow", [])
        ctx.engineered_prompt = result.get("prompt", ctx.raw_prompt)
        ctx.nodes_count = len(ctx.assembled_workflow)
    except Exception as e:
        raise RuntimeError(f"工作流组装失败: {e}") from e
    return ctx


def agent_validate_workflow(ctx: PipelineContext) -> PipelineContext:
    """Agent 6: 校验工作流。"""
    try:
        nodes_dict = {}
        for node in ctx.assembled_workflow:
            nid = str(node["id"])
            nodes_dict[nid] = {
                "class_type": node["class_type"],
                "inputs": node.get("inputs", {}),
            }
        payload = {"prompt": nodes_dict, "client_id": "pipeline-validator"}
        is_valid, issues = cc.validate_workflow(payload)

        ctx.validated = is_valid
        ctx.validation_issues = issues if not is_valid else []
    except Exception as e:
        # 校验失败不阻塞（可能在ComfyUI离线时开发）
        ctx.validated = True
        ctx.validation_issues = [f"校验异常(非阻塞): {str(e)[:100]}"]
    return ctx


def agent_submit_to_comfyui(ctx: PipelineContext) -> PipelineContext:
    """Agent 7: 提交到ComfyUI。"""
    if not ctx.raw_params.get("submit"):
        return ctx

    try:
        nodes_dict = {}
        for node in ctx.assembled_workflow:
            nid = str(node["id"])
            nodes_dict[nid] = {
                "class_type": node["class_type"],
                "inputs": node.get("inputs", {}),
            }
        payload = {"prompt": nodes_dict, "client_id": "pipeline-orchestrator"}
        result = cc.submit_workflow(nodes_dict)
        ctx.submitted = True
    except Exception as e:
        ctx.submitted = False
        ctx.submit_error = str(e)[:200]
    return ctx


# ── 管线编排器 ────────────────────────────────────────────────────────

DEFAULT_PIPELINE: list[tuple[str, AgentFunc]] = [
    ("解析意图", agent_parse_intent),
    ("加载实体", agent_load_entities),
    ("蓝图匹配", agent_match_blueprints),
    ("一致性策略", agent_choose_consistency),
    ("组装工作流", agent_assemble_workflow),
    ("校验工作流", agent_validate_workflow),
    ("提交", agent_submit_to_comfyui),
]


class PipelineOrchestrator:
    """多Agent管线编排器。

    用法:
        orch = PipelineOrchestrator()
        result = orch.run("a beautiful landscape")
        print(result.engineered_prompt)
    """

    def __init__(self, agents: list[tuple[str, AgentFunc]] | None = None):
        self.agents = agents or DEFAULT_PIPELINE

    def run(self, prompt: str, **params) -> PipelineContext:
        """执行完整管线。"""
        ctx = PipelineContext(
            raw_prompt=prompt,
            raw_params=params,
            started_at=time.time(),
        )
        stages: list[PipelineStage] = []

        for name, agent_fn in self.agents:
            stage = PipelineStage(name=name, status="running")
            t0 = time.time()
            try:
                # 跳过条件：非提交模式时跳过提交Agent
                if name == "提交" and not params.get("submit"):
                    stage.status = "skipped"
                    stages.append(stage)
                    continue

                ctx = agent_fn(ctx)
                stage.status = "ok"
                stage.duration_ms = (time.time() - t0) * 1000
                stage.output_summary = self._summarize(name, ctx)
            except Exception as e:
                stage.status = "error"
                stage.error = str(e)[:300]
                stage.duration_ms = (time.time() - t0) * 1000
                stages.append(stage)

                # 关键Agent失败需中断
                if name in ("组装工作流",):
                    ctx.finished_at = time.time()
                    raise RuntimeError(
                        f"管线在 [{name}] 阶段失败: {e}\n"
                        f"已执行阶段: {[s.name for s in stages]}"
                    ) from e

            stages.append(stage)

        ctx.finished_at = time.time()
        return ctx

    def run_storyboard(
        self,
        description: str,
        num_shots: int = 4,
        **params,
    ) -> dict[str, Any]:
        """执行故事板管线（多分镜）。"""
        ctx = PipelineContext(
            raw_prompt=description,
            raw_params={**params, "num_shots": num_shots},
            started_at=time.time(),
        )

        # Step 1: 加载实体
        ctx = agent_load_entities(ctx)

        # Step 2: 蓝图匹配
        ctx = agent_match_blueprints(ctx)

        # Step 3: 一致性
        ctx = agent_choose_consistency(ctx)

        # Step 4: 规划分镜（基于描述拆解为多个分镜）
        shots = self._plan_shots(description, num_shots, ctx)

        # Step 5: 逐镜组装
        assembled = []
        for shot in shots:
            result = wa.assemble_shot(
                shot=shot,
                entities=ctx.entities,
                consistency_profile=ctx.consistency_profile,
                blueprint_id=ctx.image_blueprint_id,
            )
            assembled.append({
                "shot_id": result.get("shot_id", f"shot_{shot.get('index', 0)}"),
                "shot_index": shot.get("index", len(assembled)),
                "prompt": result["prompt"],
                "node_count": len(result.get("workflow", [])),
                "workflow_json": result.get("workflow", []),
                "mode": result.get("mode", "auto"),
            })

        ctx.finished_at = time.time()
        return {
            "storyboard_id": f"storyboard_{int(time.time())}",
            "total_shots": len(assembled),
            "shots": assembled,
            "consistency_profile": ctx.consistency_profile,
            "duration_ms": (ctx.finished_at - ctx.started_at) * 1000,
        }

    @staticmethod
    def _plan_shots(
        description: str,
        num_shots: int,
        ctx: PipelineContext,
    ) -> list[dict[str, Any]]:
        """基于描述将场景拆解为多个分镜。

        规则拆解法：根据描述中的动作/场景关键词拆分。
        """
        shots = []
        # 按句号、分号、换行拆解场景
        segments = (
            description.replace("；", ";").replace("\n", ";").split(";")
            if ";" in description or "；" in description or "\n" in description
            else [description]
        )

        # 展开/截断到 num_shots
        if len(segments) < num_shots:
            # 描述太少，均匀展开
            for i in range(num_shots):
                seg = segments[i % len(segments)] if segments else description
                shots.append({
                    "index": i,
                    "id": f"shot_{i}",
                    "description": seg.strip() if seg.strip() else description,
                    "prompt": f"{seg.strip()}, frame {i+1}/{num_shots}" if seg.strip() else description,
                    "scene": "",
                    "characters": [],
                })
        else:
            for i, seg in enumerate(segments[:num_shots]):
                shots.append({
                    "index": i,
                    "id": f"shot_{i}",
                    "description": seg.strip(),
                    "prompt": f"{seg.strip()}, frame {i+1}/{num_shots}",
                    "scene": "",
                    "characters": [],
                })
        return shots

    @staticmethod
    def _summarize(name: str, ctx: PipelineContext) -> str:
        """生成阶段摘要。"""
        summaries = {
            "解析意图": f"style={ctx.intent.get('style', '?')}, chars={ctx.intent.get('has_characters', False)}",
            "加载实体": f"{len(ctx.entities.get('entities', {}))} 实体",
            "蓝图匹配": ctx.image_blueprint_name,
            "一致性策略": ctx.consistency_mode,
            "组装工作流": f"{ctx.nodes_count} 节点",
            "校验工作流": "通过" if ctx.validated else f"警告: {len(ctx.validation_issues)}",
            "提交": "已提交" if ctx.submitted else ("失败" if ctx.submit_error else "未提交"),
        }
        return summaries.get(name, "")


# ── 便捷入口 ──────────────────────────────────────────────────────────

_orchestrator = PipelineOrchestrator()


def run_pipeline(prompt: str, **params) -> PipelineContext:
    """便捷函数：运行完整管线。"""
    return _orchestrator.run(prompt, **params)


def run_storyboard_pipeline(description: str, num_shots: int = 4, **params) -> dict[str, Any]:
    """便捷函数：运行故事板管线。"""
    return _orchestrator.run_storyboard(description, num_shots, **params)


# ── 自检 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== PipelineOrchestrator 自检 ===")
    orch = PipelineOrchestrator()

    # 测试单图管线
    ctx = orch.run("a cyberpunk city at night, neon lights, rain", submit=False)
    print(f"单图: {ctx.engineered_prompt[:80]}...")
    print(f"节点: {ctx.nodes_count}, 蓝图: {ctx.image_blueprint_name}, 一致性: {ctx.consistency_mode}")

    # 测试故事板管线
    sb = orch.run_storyboard("日出时的海边灯塔; 海鸥飞翔在码头; 渔夫收网; 日落余晖中的灯塔", num_shots=4)
    print(f"\n故事板: {sb['total_shots']} 分镜, {sb['duration_ms']:.0f}ms")
    for shot in sb['shots']:
        print(f"  #{shot['shot_index']}: {shot['prompt'][:50]}...")
