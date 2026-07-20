"""无限画布 · 后端 API（§8.1 / §6.0 工作流自动生成引擎）。

对接**原生 ComfyUI Desktop @ 8188 + 共享模型库**（comfyui 0.28.0 / torch 2.10.0+cu130 / sm_120）。

完整链路（§6.0.1）：
  自然语言 → /api/intent（DeepSeek v4 解析意图 → §8.1.4 schema）
           → /api/generate（意图→模板映射 §6.0.2 → 参数填充 → 校验 → 提交 ComfyUI）
           → 可选 wait 轮询 /history 返回真实出图

契约：
  /api/intent    { user_input } → intent{action,subject,style,elements,params}
  /api/generate   { intent? , prompt?, checkpoint?, wait? } → { template_id, validated, prompt_id, status, images?, meta? }
  /api/templates  → 模板注册表（§6.7）
  /api/models     → 共享库 checkpoints
  /api/status     → 健康（comfyui 连接态）
  /health         → { status }
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field


def _load_dotenv(path: str = ".env") -> None:
    """在导入依赖模块前加载 .env（密钥不入 git，§12.1）。

    仅在环境变量未设置时填充，避免覆盖已存在的环境值。
    """
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass


_load_dotenv()

import comfy_client as cc
import deepseek as ds
import entity_registry as er
import intent_map as im
import workflow_assembler as wa
import video_blueprints as vb
import audio_blueprints as ab

app = FastAPI(title="Infinite Canvas Agent", version="0.5.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:4173", "http://localhost:4173",  # vite preview
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求/响应模型 ──────────────────────────────────────────────
class IntentRequest(BaseModel):
    user_input: str = Field(..., description="用户自然语言输入（§8.1.4）")


class StoryboardShot(BaseModel):
    shot_id: str
    description: str = ""
    action: str = "txt2img"
    prompt: str = ""


class IntentResponse(BaseModel):
    action: str
    subject: str
    style: str
    elements: list[str] = []
    params: dict = {}
    shots: list[StoryboardShot] = []  # v5.3: storyboard 动作时 LLM 分解的分镜镜头


class GenerateRequest(BaseModel):
    intent: dict[str, Any] | None = None
    prompt: str | None = None
    negative: str = ""
    checkpoint: str | None = None
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg: float = 7.0
    seed: int = 0
    batch_size: int = 1  # 一次生成张数（1~8，前端散布为多个节点）
    input_image: str | None = None  # 图生图/局部重绘底图（已上传到 ComfyUI input/ 的文件名）
    denoise: float = 0.6  # 图生图重绘幅度（0.3~0.8 常用）；inpaint 常用 1.0
    mask_image: str | None = None  # 局部重绘蒙版（黑底白区，已上传到 input/）
    grow_mask_by: int = 6  # 局部重绘蒙版外扩像素（默认 6，接缝更自然）
    outpaint_direction: str = "right"  # 扩图方向：left/right/up/down/all
    outpaint_pixels: int = 256        # 扩图扩展像素（原图像素空间）
    loras: list[dict[str, Any]] | None = None  # LoRA 应用：[{name, strength}]，图生图时注入
    controlnets: list[dict[str, Any]] | None = None  # ControlNet 应用：[{model, type?, strength, image, preprocessor?}]（§6.23）
    frames: int = 33          # 视频帧数（Phase 9）
    fps: int = 16             # 视频帧率（Phase 9）
    video_quality: str | None = None  # 视频质量 v5.0: 'speed' | 'quality'（LightX2V）
    face_image: str | None = None   # 角色一致性：人脸参考图（已上传 ComfyUI input/ 的文件名，v4.33）
    face_weight: float = 0.8        # 角色一致性：面部影响权重（v4.33）
    blend_image_b: str | None = None  # 多图融合：图片 B（v4.34）
    blend_mode: str = "normal"        # 多图融合：混合模式（v4.34）
    blend_factor: float = 0.5         # 多图融合：混合强度（v4.34）
    style_image: str | None = None    # 风格一致性：风格参考图（v4.35）
    style_weight: float = 0.8         # 风格一致性：风格影响权重（v4.35）
    composition_weight: float = 0.3   # 风格一致性：构图影响权重（v4.35）
    scene_image: str | None = None     # 场景一致性：场景参考图（v4.36）
    scene_weight: float = 0.7          # 场景一致性：场景保持力（v4.36）
    prop_image: str | None = None      # 道具一致性：道具参考图（v4.37）
    prop_weight: float = 0.7           # 道具一致性：道具保持力（v4.37）
    wait: bool = False  # 为 True 时同步轮询 /history 返回真实出图（端到端）


class UploadRequest(BaseModel):
    filename: str = Field(..., description="原始文件名（仅取 basename）")
    data_base64: str = Field(..., description="图片 base64（可含 data:URL 前缀）")


class UploadResponse(BaseModel):
    name: str  # ComfyUI input/ 中的存储文件名，供 img2img input_image 使用


class GenerateResponse(BaseModel):
    template_id: str
    validated: bool
    prompt_id: str
    status: str
    images: list[str] = []
    issues: list[str] = []
    meta: dict = {}
    workflow: dict | None = None  # 前端无限画布内节点图（comfy_client.workflow_to_graph）


# ── v4.38 分镜编排 ─────────────────────────────────────────────
class StoryboardRequest(BaseModel):
    prompts: list[str] = Field(..., min_length=1, max_length=25,
                                description="分镜提示词列表，每项为一个镜头描述")
    checkpoint: str | None = None
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg: float = 7.0
    seed: int = 0


class StoryboardFrame(BaseModel):
    index: int
    prompt: str
    prompt_id: str
    image: str | None = None  # ComfyUI output 文件名
    status: str = "queued"


class StoryboardResponse(BaseModel):
    validated: bool
    frames: list[StoryboardFrame] = []
    issues: list[str] = []
    template_id: str = "storyboard_sdxl"


# ── v5.1 多角色同框 Regional Pipeline ──────────────────────────
class CharacterSlotModel(BaseModel):
    token: str                                    # [A], [B], [C]
    entity_id: str                                # 角色实体 ID
    prompt: str                                   # 角色描述
    region_ratio: float = 0.5                     # 占画面比例
    ipa_weight: float = 0.8                       # IPAdapter 权重
    start_at: float = 0.0
    end_at: float = 0.5


class RegionalRequest(BaseModel):
    characters: list[CharacterSlotModel] = Field(..., min_length=2, max_length=8)
    base_prompt: str = ""                         # 共有场景描述
    negative: str = ""
    layout: str = "horizontal"                    # horizontal | vertical | grid2x2 | custom
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg: float = 7.0
    seed: int = 0


class RegionalResponse(BaseModel):
    validated: bool
    template_id: str = "regional"
    prompt_id: str = ""
    status: str = ""
    issues: list[str] = []
    meta: dict = {}
    workflow: dict | None = None


@app.post("/api/regional/generate")
async def regional_generate(req: RegionalRequest) -> RegionalResponse:
    """多角色同框区域生成（v5.1）。

    将多个角色实体在同一画面中分离生成，使用 SDXL Regional Sampler
    + 每角色独立 IPAdapter + 区域注意力掩码。

    输入：N 个角色槽位（entity_id + prompt），布局模式，基础场景提示词
    输出：ComfyUI workflow，可直接提交到 /prompt
    """
    from regional_pipeline import (
        RegionalConfig, CharacterSlot, LayoutMode, run_regional,
    )
    layout_map = {
        "horizontal": LayoutMode.HORIZONTAL,
        "vertical": LayoutMode.VERTICAL,
        "grid2x2": LayoutMode.GRID2X2,
        "custom": LayoutMode.CUSTOM,
    }
    layout = layout_map.get(req.layout, LayoutMode.HORIZONTAL)

    slots = [
        CharacterSlot(
            token=c.token,
            entity_id=c.entity_id,
            prompt=c.prompt,
            region_ratio=c.region_ratio,
            ipa_weight=c.ipa_weight,
            start_at=c.start_at,
            end_at=c.end_at,
        )
        for c in req.characters
    ]

    config = RegionalConfig(
        slots=slots,
        layout=layout,
        width=req.width,
        height=req.height,
        base_prompt=req.base_prompt,
        negative=req.negative,
        steps=req.steps,
        cfg=req.cfg,
        seed=req.seed,
    )

    result = run_regional(config)

    if result.get("error"):
        return RegionalResponse(
            validated=False,
            status="error",
            issues=result.get("issues", []),
        )

    return RegionalResponse(
        validated=True,
        status="built",
        meta=result.get("meta", {}),
        workflow=result.get("workflow"),
    )


# ── v5.2 一致性审查 + IP 相似度预警 ──────────────────────────────

class ConsistencyReviewRequest(BaseModel):
    nodes: list[dict[str, Any]] = Field(..., min_length=1, max_length=50,
        description="节点列表：[{node_id, reference_image, generated_image, mode}, ...]")
    threshold: float = 0.75


class ConsistencyReviewResponse(BaseModel):
    validated: bool
    total_nodes: int = 0
    passed_nodes: int = 0
    failed_nodes: int = 0
    pass_rate: float = 0.0
    avg_similarity: float = 0.0
    grade_distribution: dict[str, int] = {}
    issues: list[str] = []
    reports: list[dict[str, Any]] = []


@app.post("/api/review/consistency")
async def review_consistency(req: ConsistencyReviewRequest) -> ConsistencyReviewResponse:
    """跨节点一致性自动审查（v5.2 #17）。

    使用 CLIP embedding 对比参考图和生成图的相似度，
    按模型（face/style/scene）分类评分。

    阈值：≥ 0.75 通过，< 0.75 标记为降级。
    """
    from embedding_service import cross_node_consistency, batch_consistency_summary
    reports = cross_node_consistency(req.nodes, threshold=req.threshold)
    summary = batch_consistency_summary(reports)
    return ConsistencyReviewResponse(
        validated=True,
        total_nodes=summary["total_nodes"],
        passed_nodes=summary["passed_nodes"],
        failed_nodes=summary["failed_nodes"],
        pass_rate=summary["pass_rate"],
        avg_similarity=summary["avg_similarity"],
        grade_distribution=summary["grade_distribution"],
        issues=summary["issues"],
        reports=[
            {
                "node_id": r.node_id,
                "mode": r.mode,
                "similarity_score": r.similarity_score,
                "grade": r.grade,
                "passed": r.passed,
                "issues": r.issues,
            }
            for r in reports
        ],
    )


class IPCheckRequest(BaseModel):
    entity_id: str
    generated_image: str
    entity_name: str = ""


class IPCheckResponse(BaseModel):
    validated: bool
    entity_id: str
    entity_name: str
    similarity: float
    passed: bool
    warning: str
    action: str


@app.post("/api/guard/ip-check")
async def ip_check(req: IPCheckRequest) -> IPCheckResponse:
    """IP 角色相似度预警（v5.2 #18）。

    对比生成图与角色 IP 参考库的 CLIP 嵌入相似度。
    相似度 < 0.65 时给出预警。
    """
    from embedding_service import check_ip_similarity
    result = check_ip_similarity(req.entity_id, req.generated_image, req.entity_name)
    return IPCheckResponse(
        validated=True,
        entity_id=result.entity_id,
        entity_name=result.entity_name,
        similarity=result.generated_similarity,
        passed=result.passed,
        warning=result.warning,
        action=result.suggested_action,
    )


class IPRegisterRequest(BaseModel):
    entity_id: str
    reference_image: str  # 参考图本地路径


class IPRegisterResponse(BaseModel):
    validated: bool
    entity_id: str
    registered: bool
    message: str


@app.post("/api/guard/ip-register")
async def ip_register(req: IPRegisterRequest) -> IPRegisterResponse:
    """注册实体参考嵌入到 IP 库（v5.2 #18）。"""
    from embedding_service import store_entity_embedding
    ok = store_entity_embedding(req.entity_id, req.reference_image)
    return IPRegisterResponse(
        validated=True,
        entity_id=req.entity_id,
        registered=ok,
        message="注册成功" if ok else f"注册失败：无法提取 {req.reference_image} 的 CLIP 嵌入",
    )


@app.get("/api/guard/ip-library")
async def ip_library() -> dict:
    """IP 嵌入库状态查询（v5.2 #18）。"""
    from embedding_service import ip_library_status
    return ip_library_status()


# ── v5.3 基础审核（#19）· 节点质量标记 ──────────────────────────

# 内存中的节点质量标记（生产环境应持久化到数据库）
_node_quality_store: dict[str, dict[str, str]] = {}


class QualityMarkRequest(BaseModel):
    node_id: str
    status: str = "approved"  # approved | rejected | needs_regeneration | unreviewed
    note: str | None = None


class BatchQualityMarkRequest(BaseModel):
    node_ids: list[str] = Field(..., min_length=1, max_length=200)
    status: str = "approved"
    note: str | None = None


@app.post("/api/review/quality")
async def quality_mark(req: QualityMarkRequest) -> dict:
    """标记单个画布节点的质量审核状态（v5.3 #19）。"""
    valid_statuses = {"approved", "rejected", "needs_regeneration", "unreviewed"}
    if req.status not in valid_statuses:
        return {"validated": False, "error": f"无效状态：{req.status}，可用值：{valid_statuses}"}
    _node_quality_store[req.node_id] = {
        "status": req.status,
        "note": req.note or "",
    }
    return {"validated": True, "node_id": req.node_id, "status": req.status}


@app.post("/api/review/batch-quality")
async def batch_quality_mark(req: BatchQualityMarkRequest) -> dict:
    """批量标记节点质量审核状态（v5.3 #19）。"""
    valid_statuses = {"approved", "rejected", "needs_regeneration", "unreviewed"}
    if req.status not in valid_statuses:
        return {"validated": False, "error": f"无效状态：{req.status}"}
    for nid in req.node_ids:
        _node_quality_store[nid] = {
            "status": req.status,
            "note": req.note or "",
        }
    return {"validated": True, "count": len(req.node_ids)}


@app.get("/api/review/quality-stats")
async def quality_stats() -> dict:
    """获取审核统计（v5.3 #19）。"""
    stats = {"total": 0, "unreviewed": 0, "approved": 0, "rejected": 0, "needs_regeneration": 0}
    for v in _node_quality_store.values():
        s = v.get("status", "unreviewed")
        stats["total"] += 1
        stats[s] = stats.get(s, 0) + 1
    return stats


# ── v4.39 视频拼接 ─────────────────────────────────────────────
_COMFYUI_OUTPUT_DIR = os.environ.get(
    "COMFYUI_OUTPUT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "..", "..", "ComfyUI", "output"),
)


class ConcatVideosRequest(BaseModel):
    video_names: list[str] = Field(..., min_length=1, max_length=50,
                                    description="要拼接的视频文件名列表（ComfyUI output 下的 mp4）")
    output_name: str | None = None


class ConcatVideosResponse(BaseModel):
    validated: bool
    filename: str | None = None  # 拼接后的输出文件名
    issues: list[str] = []


# ── 用户模板管理（v4.31）─────────────────────────────────────────
_USER_TEMPLATES_DIR = Path(__file__).parent / "templates" / "user"
_USER_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

SANITIZE_TABLE = str.maketrans({"\\": "_", "/": "_", ":": "_", "*": "_",
                                "?": "_", "\"": "_", "<": "_", ">": "_", "|": "_"})


class SaveTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64,
                      description="模板名称（仅用于 UI 列表）")
    nodes: list[dict[str, Any]] = Field(..., description="画布节点列表")
    links: list[dict[str, Any]] = Field([], description="画布连线列表")


class UserTemplateMeta(BaseModel):
    name: str
    saved_at: float  # Unix 时间戳
    node_count: int

# ── 端点 ────────────────────────────────────────────────────────
@app.post("/api/intent", response_model=IntentResponse)
async def parse_intent(req: IntentRequest) -> IntentResponse:
    """LLM 意图解析：DeepSeek v4 主路线，失败自动降级 Ollama（§8.1.6 / §14.3 自愈）。"""
    intent = await asyncio.to_thread(ds.parse_intent, req.user_input)
    shots_raw = intent.get("shots", []) or []
    return IntentResponse(
        action=intent.get("action", "txt2img"),
        subject=intent.get("subject", ""),
        style=intent.get("style", ""),
        elements=intent.get("elements", []),
        params=intent.get("params", {}),
        shots=[StoryboardShot(
            shot_id=s.get("shot_id", str(i+1)),
            description=s.get("description", ""),
            action=s.get("action", "txt2img"),
            prompt=s.get("prompt", ""),
        ) for i, s in enumerate(shots_raw)],
    )


@app.get("/api/templates")
async def list_templates() -> list[dict]:
    """模板注册表（§6.7 / §6.0.2）。"""
    return im.list_templates()


@app.get("/api/models")
async def list_models() -> dict:
    """共享模型库 checkpoints/ 已装模型（§6.10）。"""
    checkpoints = await asyncio.to_thread(cc.list_checkpoints)
    return {"shared_model_lib": cc.SHARED_MODEL_LIB, "checkpoints": checkpoints}


@app.get("/api/status")
async def status() -> dict:
    """健康：comfyui 连接态（§8.1 /status）。"""
    try:
        await asyncio.to_thread(cc.get_object_info)
        return {"status": "ok", "comfyui": "connected", "comfyui_url": cc.COMFYUI_URL}
    except Exception as e:  # noqa: BLE001
        return {"status": "ok", "comfyui": "disconnected", "error": str(e)[:200]}


@app.get("/api/loras")
async def list_loras() -> dict:
    """共享模型库 loras/ 已装 LoRA（§6.22，控制节点化）。"""
    loras = await asyncio.to_thread(cc.list_loras)
    return {"loras": loras}


@app.get("/api/controlnets")
async def list_controlnets() -> dict:
    """共享模型库 controlnet/ 已装 ControlNet（§6.23，控制节点化）。"""
    controlnets = await asyncio.to_thread(cc.list_controlnets)
    return {"controlnets": controlnets, "union_types": cc.CONTROLNET_UNION_TYPES}


# ── v4.31 用户工作流模板保存/加载/删除 ────────────────────────────
def _safe_name(name: str) -> str:
    """过滤路径不安全字符，保留可读性。"""
    return name.translate(SANITIZE_TABLE).strip() or "unnamed"


@app.post("/api/templates/save")
async def save_user_template(req: SaveTemplateRequest) -> dict:
    """保存当前画布为可重用用户模板。"""
    safe = _safe_name(req.name)
    path = _USER_TEMPLATES_DIR / f"{safe}.json"
    data = {
        "name": req.name,
        "saved_at": time.time(),
        "nodes": req.nodes,
        "links": req.links,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"name": safe, "node_count": len(req.nodes)}


@app.get("/api/templates/user")
async def list_user_templates() -> list[UserTemplateMeta]:
    """列出所有用户保存的画布模板。"""
    result: list[UserTemplateMeta] = []
    for path in sorted(_USER_TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append(UserTemplateMeta(
                name=data.get("name", path.stem),
                saved_at=data.get("saved_at", 0),
                node_count=len(data.get("nodes", [])),
            ))
        except Exception:
            continue
    return result


@app.get("/api/templates/user/{name}")
async def load_user_template(name: str) -> dict:
    """加载单个用户模板的完整数据。"""
    safe = _safe_name(name)
    path = _USER_TEMPLATES_DIR / f"{safe}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"模板 '{name}' 不存在")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取模板失败: {e}")


@app.delete("/api/templates/user/{name}")
async def delete_user_template(name: str) -> dict:
    """删除指定用户模板。"""
    safe = _safe_name(name)
    path = _USER_TEMPLATES_DIR / f"{safe}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"模板 '{name}' 不存在")
    path.unlink()
    return {"deleted": safe}


# ── v4.42 自定义 ComfyUI 工作流库 + GPT 辅助创建 ────────────────
_WORKFLOWS_DIR = Path(__file__).parent / "workflows"
_WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)


class SaveWorkflowRequest(BaseModel):
    name: str
    description: str = ""
    workflow_json: dict


class WorkflowMeta(BaseModel):
    name: str
    description: str
    node_count: int
    saved_at: float


class GptWorkflowRequest(BaseModel):
    description: str


# ── v4.50 工作流生成（自然语言→完整 ComfyUI JSON）────────────────
class WorkflowGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="自然语言描述（分镜/故事板描述）")
    blueprint: str = Field("txt2img_sdxl", description="图像蓝图 ID")
    image_blueprint: str = Field("txt2img_sdxl", description="图像蓝图 ID（兼容旧参数名）")
    video_blueprint: str | None = Field(None, description="视频蓝图 ID（可选，None=不生成视频）")
    consistency_mode: str = Field("auto", description="一致性模式: auto/character/scene/style")
    width: int = Field(1024, ge=64, le=4096)
    height: int = Field(1024, ge=64, le=4096)
    steps: int = Field(20, ge=1, le=100)
    cfg: float = Field(7.0, ge=1.0, le=30.0)
    negative: str = ""
    submit: bool = Field(False, description="是否直接提交 ComfyUI 执行（否则仅返回 JSON）")


class StoryboardPlanRequest(BaseModel):
    description: str = Field(..., min_length=1, description="剧情/故事板描述")
    num_shots: int = Field(4, ge=1, le=36, description="期望分镜数")
    style: str = Field("", description="画风描述")
    characters: list[str] = Field([], description="角色名称列表")
    blueprint: str = Field("txt2img_sdxl", description="图像蓝图 ID")
    video_blueprint: str | None = Field(None, description="视频蓝图 ID（可选）")
    consistency_mode: str | None = Field("auto", description="一致性模式: auto/face_consistency/style_consistency/...")


class PipelineRunRequest(BaseModel):
    """v4.50 PipelineOrchestrator 请求。"""
    prompt: str = Field(..., min_length=1, description="自然语言描述")
    image_blueprint: str | None = Field(None, description="图像蓝图 ID（None=自动匹配）")
    consistency_mode: str | None = Field("auto", description="一致性模式")
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    cfg: float | None = None
    negative: str | None = None
    submit: bool = Field(False, description="是否同时提交到ComfyUI")


@app.post("/api/workflows/save")
async def save_workflow(req: SaveWorkflowRequest) -> dict:
    """保存自定义 ComfyUI 工作流 JSON。"""
    safe = _safe_name(req.name)
    path = _WORKFLOWS_DIR / f"{safe}.json"
    data = {
        "name": req.name,
        "description": req.description,
        "saved_at": time.time(),
        "workflow_json": req.workflow_json,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    nc = len(req.workflow_json) if isinstance(req.workflow_json, dict) else 0
    return {"name": safe, "node_count": nc}


@app.get("/api/workflows")
async def list_workflows() -> list[WorkflowMeta]:
    """列出所有已保存的自定义工作流。"""
    result: list[WorkflowMeta] = []
    for path in sorted(_WORKFLOWS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            wf = data.get("workflow_json", {})
            nc = len(wf) if isinstance(wf, dict) else 0
            result.append(WorkflowMeta(
                name=data.get("name", path.stem),
                description=data.get("description", ""),
                node_count=nc,
                saved_at=data.get("saved_at", 0),
            ))
        except Exception:
            continue
    return result


@app.get("/api/workflows/{name}")
async def load_workflow(name: str) -> dict:
    """加载单个自定义工作流完整数据（含可视化图）。"""
    safe = _safe_name(name)
    path = _WORKFLOWS_DIR / f"{safe}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"工作流 '{name}' 不存在")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        wf = data.get("workflow_json", {})
        if isinstance(wf, dict) and wf:
            graph = cc.workflow_to_graph(wf)
            data["workflow_graph"] = graph
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取工作流失败: {e}")


@app.delete("/api/workflows/{name}")
async def delete_workflow(name: str) -> dict:
    """删除指定工作流。"""
    safe = _safe_name(name)
    path = _WORKFLOWS_DIR / f"{safe}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"工作流 '{name}' 不存在")
    path.unlink()
    return {"deleted": safe}


@app.post("/api/workflows/gpt")
async def gpt_create_workflow(req: GptWorkflowRequest) -> dict:
    """GPT 辅助：从自然语言描述生成 ComfyUI 工作流 JSON。

    流程：用户描述 → LLM 解析意图 → 模板映射 → 构建工作流 → 返回 JSON + 图。
    """
    intent = await asyncio.to_thread(ds.parse_intent, req.description)
    tid, wf, meta = await asyncio.to_thread(im.build_workflow, intent, None, 1, None)
    graph = cc.workflow_to_graph(wf)
    nc = len(wf) if isinstance(wf, dict) else 0
    return {
        "template_id": tid,
        "node_count": nc,
        "intent": intent,
        "workflow_json": wf,
        "workflow_graph": graph,
    }


# ── v4.50 工作流生成（自然语言→组装→校验→可选提交）──────────────
@app.post("/api/workflows/generate")
async def generate_workflow(req: WorkflowGenerateRequest) -> dict:
    """自然语言描述 → 完整 ComfyUI 工作流 JSON。

    流程（§3.2 工作流引擎 Phase 1-4）：
    1. DeepSeek v4 意图解析（已有）
    2. 一致性策略推荐（consistency_manager）
    3. 蓝图组装（workflow_assembler）
    4. 节点校验（comfy_client validator）
    5. 可选：提交 ComfyUI 执行（submit=True）
    """
    # Phase 1: 意图解析
    intent = await asyncio.to_thread(ds.parse_intent, req.prompt)

    # Phase 2-3: 组装工作流（使用 v4.50 新 pipeline）
    entities_dict = await asyncio.to_thread(er.load_all_entities)
    bp = req.blueprint or req.image_blueprint
    result = await asyncio.to_thread(
        wa.assemble_single,
        prompt=req.prompt,
        entities=entities_dict,
        image_blueprint=bp,
        consistency_mode=req.consistency_mode,
        width=req.width,
        height=req.height,
        steps=req.steps,
        cfg=req.cfg,
        negative=req.negative,
    )

    workflow_nodes = result["workflow"]

    # 将 list→dict（comfy_client 期望 {node_id: {...}} 格式）
    nodes_dict = {str(n["id"]): {"class_type": n["class_type"], "inputs": n.get("inputs", {})} for n in workflow_nodes}

    # Phase 4: 校验（返回值是 tuple: (valid: bool, issues: list[str])）
    valid_flag, issues = await asyncio.to_thread(cc.validate_workflow, nodes_dict)

    # 生成工作流图（前端可视化）
    graph = cc.workflow_to_graph(nodes_dict)

    response_data: dict[str, Any] = {
        "validated": valid_flag,
        "issues": issues,
        "node_count": len(workflow_nodes),
        "shot_id": result["shot_id"],
        "prompt_engineered": result["prompt"],
        "consistency_mode": result["mode"],
        "entities_used": result.get("entities_used", []),
        "intent": intent,
        "workflow_json": wa.workflow_to_prompt_json(workflow_nodes),
        "workflow_graph": graph,
    }

    # Phase 5: 可选提交执行
    if req.submit:
        try:
            prompt_id = cc.submit_workflow(nodes_dict)
            response_data["prompt_id"] = prompt_id
            response_data["submitted"] = True
        except Exception as e:
            response_data["submitted"] = False
            response_data["submit_error"] = str(e)

    return response_data


@app.post("/api/storyboard/plan")
async def plan_storyboard(req: StoryboardPlanRequest) -> dict:
    """自动故事板规划：自然语言描述 → 多分镜计划 + 每个分镜的 ComfyUI 工作流。

    流程（§3.2 完整管线）：
    描述 → workflow_planner（分镜分解）
         → entity_registry（角色/场景匹配）
         → consistency_manager（策略推荐）
         → workflow_assembler（逐分镜组装）
         → 返回全部工作流 JSON
    """
    import workflow_planner as wp

    # 加载已注册实体
    entities_dict = await asyncio.to_thread(er.load_all_entities)

    # 查找匹配的角色实体
    character_ids = []
    for cname in req.characters:
        found = await asyncio.to_thread(er.search_entities, cname)
        if found:
            character_ids.extend([e.entity_id for e in found])

    # Phase 1: 故事板规划（需要先生成 intent dict）
    intent = await asyncio.to_thread(ds.parse_intent, req.description)
    storyboard_plan = await asyncio.to_thread(
        wp.plan_storyboard,
        intent=intent,
        total_frames=req.num_shots,
        character_ids=character_ids,
        description=req.description,
    )

    # 将 StoryboardPlan 转为 assemble_storyboard 期望的 dict
    storyboard = {
        "id": storyboard_plan.plan_id,
        "description": req.description,
        "style": storyboard_plan.global_style_id or req.style,
        "shots": [
            {
                "index": f.frame_index,
                "id": f"shot_{f.frame_index}",
                "description": f.prompt_template.format(description=req.description),
                "prompt": f.prompt_template.format(description=req.description),
                "role": f.frame_role.value if hasattr(f.frame_role, 'value') else str(f.frame_role),
                "characters": f.character_ids,
                "scene": f.scene_id,
                "scene_id": f.scene_id,
                "props": f.prop_ids,
                "style_id": f.style_id,
                "duration_sec": f.duration_sec,
            }
            for f in storyboard_plan.frames
        ],
    }

    # Phase 2-4: 逐分镜组装
    result = await asyncio.to_thread(
        wa.assemble_storyboard,
        storyboard=storyboard,
        entities=entities_dict,
        image_blueprint=req.blueprint,
        video_blueprint=req.video_blueprint,
    )

    # 汇总所有工作流 JSON
    all_workflows = []
    for shot in result["shots"]:
        all_workflows.append({
            "shot_id": shot["shot_id"],
            "shot_index": shot["shot_index"],
            "prompt": shot["prompt"],
            "node_count": len(shot["workflow"]),
            "workflow_json": wa.workflow_to_prompt_json(shot["workflow"]),
        })

    return {
        "validated": True,
        "storyboard_id": result["storyboard_id"],
        "total_shots": result["total_shots"],
        "consistency_profile": result["consistency_profile"],
        "shots": all_workflows,
    }


@app.get("/api/blueprints")
async def list_blueprints() -> dict:
    """列出所有可用蓝图（图像 + 视频）。"""
    return wa.list_all_blueprints()


# ── v4.50 Pipeline Orchestrator API ─────────────────────────────────

@app.post("/api/pipeline/run")
async def run_pipeline_endpoint(req: PipelineRunRequest) -> dict:
    """通过 PipelineOrchestrator 运行完整多Agent管线。

    与 /api/workflows/generate 的区别：
    - 更完整的管线追踪（每阶段状态可视化）
    - 自动意图解析 + 蓝图匹配（无需手动指定蓝图）
    - 统一管线上下文传递
    """
    import pipeline_orchestrator as po

    orch = po.PipelineOrchestrator()
    ctx = await asyncio.to_thread(
        orch.run,
        req.prompt,
        image_blueprint=req.image_blueprint,
        consistency_mode=req.consistency_mode or "auto",
        width=req.width or 1024,
        height=req.height or 1024,
        steps=req.steps or 20,
        cfg=req.cfg or 7.0,
        negative=req.negative or "",
        submit=req.submit,
    )

    # 构建响应
    nodes_dict = {str(n["id"]): {"class_type": n["class_type"], "inputs": n.get("inputs", {})}
                  for n in ctx.assembled_workflow}

    graph = cc.workflow_to_graph(nodes_dict) if ctx.assembled_workflow else {}

    return {
        "validated": ctx.validated,
        "issues": ctx.validation_issues,
        "node_count": ctx.nodes_count,
        "prompt_engineered": ctx.engineered_prompt,
        "consistency_mode": ctx.consistency_mode,
        "intent": ctx.intent,
        "blueprint": ctx.image_blueprint_name,
        "blueprint_id": ctx.image_blueprint_id,
        "submitted": ctx.submitted,
        "submit_error": ctx.submit_error,
        "workflow_json": wa.workflow_to_prompt_json(ctx.assembled_workflow) if ctx.assembled_workflow else {},
        "workflow_graph": graph,
        "duration_ms": (ctx.finished_at - ctx.started_at) * 1000 if ctx.finished_at else 0,
        "pipeline_version": "4.50",
    }


@app.post("/api/pipeline/storyboard")
async def run_storyboard_pipeline_endpoint(req: StoryboardPlanRequest) -> dict:
    """通过 PipelineOrchestrator 运行故事板管线。

    比 /api/storyboard/plan 更完整，包含：
    - 意图解析 → 蓝图匹配 → 一致性策略 → 分镜规划 → 逐镜组装
    """
    import pipeline_orchestrator as po

    orch = po.PipelineOrchestrator()
    result = await asyncio.to_thread(
        orch.run_storyboard,
        req.description,
        num_shots=req.num_shots or 4,
        blueprint=req.blueprint,
        consistency_mode=req.consistency_mode or "auto",
    )

    return result


# ── v4.53 Text Production API ─────────────────────────────────────

class TextProductionRequest(BaseModel):
    """v4.53 多Agent写作管线请求。"""
    title: str = Field(..., min_length=1, description="故事标题")
    logline: str = Field(..., min_length=1, description="一句话概要")
    genre: str = Field("default", description="类型: fantasy/scifi/horror/anime/...")
    tone: str = Field("epic", description="调性: epic/dark/light/whimsical")
    setting: str = Field("", description="世界观设定")
    num_beats: int = Field(8, ge=3, le=16, description="节拍数")
    style: str = Field("realistic", description="视觉风格: anime/realistic/fantasy/scifi/...")


@app.post("/api/text/produce")
async def text_production_endpoint(req: TextProductionRequest) -> dict:
    """多Agent写作管线：概念 → 大纲 → 角色 → 剧本 → 提示词 → 分镜。"""
    import text_production as tp

    pipeline = tp.TextProductionPipeline()
    doc = await asyncio.to_thread(
        pipeline.run,
        req.title,
        req.logline,
        genre=req.genre,
        tone=req.tone,
        setting=req.setting,
        num_beats=req.num_beats,
        style=req.style,
    )

    return {
        "title": doc.concept.title,
        "logline": doc.concept.logline,
        "genre": doc.concept.genre,
        "beats": [
            {"id": b.id, "index": b.index, "name": b.name,
             "description": b.description, "emotion": b.emotion, "location": b.location}
            for b in doc.beats
        ],
        "characters": [
            {"id": c.id, "name": c.name, "archetype": c.archetype,
             "appearance": c.appearance, "personality": c.personality,
             "motivation": c.motivation, "relationship": c.relationship,
             "consistent_prompt": c.consistent_prompt}
            for c in doc.characters
        ],
        "scenes": [
            {"id": s.id, "scene_index": s.scene_index, "beat_id": s.beat_id,
             "location": s.location, "time_of_day": s.time_of_day,
             "description": s.description, "camera_direction": s.camera_direction,
             "lighting": s.lighting, "characters_present": s.characters_present}
            for s in doc.scenes
        ],
        "prompts": [
            {"id": p.id, "index": p.index, "scene_id": p.scene_id,
             "english_prompt": p.english_prompt, "chinese_prompt": p.chinese_prompt,
             "shot_type": p.shot_type, "negative": p.negative,
             "consistency_hint": p.consistency_hint}
            for p in doc.prompts
        ],
        "storyboard": doc.metadata.get("storyboard", {}),
        "metadata": doc.metadata,
    }


async def _build(req: GenerateRequest) -> tuple[str, dict, dict]:
    """构造工作流（意图/兼容两条链路），返回 (template_id, wf, meta)。"""
    if req.intent:
        # 图生图/局部重绘/批量/种子经请求透传（前端参数面板控制）
        intent = dict(req.intent)
        if req.input_image:
            intent.setdefault("params", {})
            if req.mask_image:
                intent["action"] = "inpaint"
                if isinstance(intent["params"], dict):
                    intent["params"].setdefault("denoise", req.denoise)
                    intent["params"].setdefault("grow_mask_by", req.grow_mask_by)
            else:
                intent["action"] = "img2img"
                if isinstance(intent["params"], dict):
                    intent["params"].setdefault("denoise", req.denoise)
        return await asyncio.to_thread(
            im.build_workflow, intent, req.input_image,
            req.batch_size, req.seed or None, req.mask_image,
            req.outpaint_direction, req.outpaint_pixels,
            req.loras, req.controlnets, req.frames, req.fps,
            req.face_image, req.face_weight,
            req.blend_image_b, req.blend_mode, req.blend_factor,
            req.style_image, req.style_weight, req.composition_weight,
            req.scene_image, req.scene_weight,
            req.prop_image, req.prop_weight,
            req.video_quality or "speed")  # v5.0 LightX2V

    # 兼容旧链路：用 checkpoint（缺省自动选共享库首个）
    template_id = "txt2img_sdxl"
    meta: dict = {}
    checkpoint = req.checkpoint
    if not checkpoint:
        checkpoints = await asyncio.to_thread(cc.list_checkpoints)
        if not checkpoints:
            return template_id, {}, meta
        checkpoint = checkpoints[0]
    if req.input_image and req.mask_image:
        template_id = "inpaint_sdxl"
        wf = cc.build_inpaint(
            checkpoint=checkpoint, image_name=req.input_image, mask_name=req.mask_image,
            prompt=req.prompt or "a beautiful scenery", negative=req.negative,
            denoise=req.denoise if req.denoise else 1.0, steps=req.steps,
            cfg=req.cfg, seed=req.seed, grow_mask_by=req.grow_mask_by)
    elif req.input_image:
        template_id = "img2img_sdxl"
        wf = cc.build_img2img(
            checkpoint=checkpoint, image_name=req.input_image,
            prompt=req.prompt or "a beautiful scenery", negative=req.negative,
            denoise=req.denoise, steps=req.steps, cfg=req.cfg, seed=req.seed)
    else:
        wf = cc.build_txt2img(
            checkpoint=checkpoint, prompt=req.prompt or "a beautiful scenery",
            negative=req.negative, width=req.width, height=req.height,
            steps=req.steps, cfg=req.cfg, seed=req.seed,
            batch_size=req.batch_size)
    return template_id, wf, meta


@app.post("/api/preview")
async def preview(req: GenerateRequest) -> dict:
    """生成前预览工作流图（不提交 ComfyUI）：返回校验态 + 前端节点图。

    前端在「生成」前调用，先于出图把工作流显示在无限画布内（参考商业级 UI）。
    """
    template_id, wf, meta = await _build(req)
    if not wf:
        return {"validated": False, "issues": ["共享库 checkpoints/ 无可用模型"], "workflow": None}
    ok, val_issues = await asyncio.to_thread(cc.validate_workflow, wf)
    graph = meta.get("workflow_graph") or cc.workflow_to_graph(wf)
    return {"validated": ok, "issues": val_issues, "workflow": graph, "template_id": template_id}


@app.post("/api/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    """意图→模板映射→参数填充→校验→提交（§6.0）。

    - 有 intent：经 intent_map.build_workflow 解析（Qwen-Image / NoobAI）。
    - 无 intent：兼容旧链路，用 checkpoint（缺省自动选共享库首个）。
    """
    template_id, wf, meta = await _build(req)
    if not wf:
        return GenerateResponse(
            template_id=template_id, validated=False, prompt_id="",
            status="no_checkpoint", issues=["共享库 checkpoints/ 无可用模型"])

    # 2) 动态校验（§6.7.1：节点不硬编码）
    ok, val_issues = await asyncio.to_thread(cc.validate_workflow, wf)
    if not ok:
        graph = meta.get("workflow_graph") or cc.workflow_to_graph(wf)
        return GenerateResponse(
            template_id=template_id, validated=False, prompt_id="",
            status="validation_failed", issues=val_issues, meta=meta, workflow=graph)

    # 3) 提交
    prompt_id = await asyncio.to_thread(cc.submit_workflow, wf)

    # 4) 可选：轮询出图（端到端）
    images: list[str] = []
    status = "queued"
    if req.wait:
        try:
            result = await asyncio.to_thread(cc.wait_for_result, prompt_id, timeout=600)
            outs = result.get("outputs", {})
            for node_out in outs.values():
                for img in node_out.get("images", []):
                    images.append(img.get("filename", ""))
                for g in node_out.get("gifs", []):
                    images.append(g.get("filename", ""))
            status = "success"
        except Exception as e:  # noqa: BLE001
            status = "timeout"
            meta["wait_error"] = str(e)[:200]

    # 透传构建期 issues（如视频缺母图的安全降级提示）
    issues = list(meta.get("issues", []))
    graph = meta.get("workflow_graph") or cc.workflow_to_graph(wf)
    return GenerateResponse(
        template_id=template_id, validated=True, prompt_id=prompt_id,
        status=status, images=images, issues=issues, meta=meta, workflow=graph)


# ── v4.38 分镜编排 ─────────────────────────────────────────────
@app.post("/api/storyboard", response_model=StoryboardResponse)
async def storyboard(req: StoryboardRequest) -> StoryboardResponse:
    """25宫格分镜编排 (Phase 9)：输入 N 条分镜提示词，并行生成 N 张帧图。

    每个分镜帧使用共享的 checkpoint / 尺寸 / 步数 / CFG 参数，
    seed 逐帧递增 (seed + frame_index)，确保各帧差异化。

    所有帧的 txt2img 工作流提交到 ComfyUI 后，轮询等待全部完成，
    按原始顺序返回帧结果列表。
    """
    prompts = [p.strip() for p in req.prompts if p.strip()]
    if not prompts:
        return StoryboardResponse(validated=False, issues=["至少需要 1 条分镜提示词"])

    # 确定 checkpoint
    checkpoint = req.checkpoint
    if not checkpoint:
        checkpoints = await asyncio.to_thread(cc.list_checkpoints)
        if not checkpoints:
            return StoryboardResponse(validated=False, issues=["共享库无可用模型"])
        checkpoint = checkpoints[0]

    # 1) 为每个分镜构建 txt2img 工作流（seed 逐帧递增）
    workflows: list[dict[str, Any]] = []
    for i, prompt in enumerate(prompts):
        frame_seed = max(req.seed + i, 0)
        wf = cc.build_txt2img(
            checkpoint=checkpoint,
            prompt=prompt,
            negative="",
            width=req.width, height=req.height,
            steps=req.steps, cfg=req.cfg,
            seed=frame_seed, batch_size=1,
        )
        workflows.append(wf)

    # 2) 校验所有工作流（仅报告失败的第一条）
    for i, wf in enumerate(workflows):
        ok, issues = await asyncio.to_thread(cc.validate_workflow, wf)
        if not ok:
            return StoryboardResponse(
                validated=False,
                issues=[f"分镜 {i+1} 校验失败: {'; '.join(issues[:3])}"],
            )

    # 3) 并行提交所有工作流到 ComfyUI
    prompt_ids: list[str] = []
    for i, wf in enumerate(workflows):
        try:
            pid = await asyncio.to_thread(cc.submit_workflow, wf)
            prompt_ids.append(pid)
        except Exception as e:
            return StoryboardResponse(
                validated=False,
                issues=[f"分镜 {i+1} 提交失败: {str(e)[:200]}"],
            )

    # 4) 并行轮询所有结果
    from concurrent.futures import ThreadPoolExecutor
    loop = asyncio.get_running_loop()

    def _wait_for(prompt_id: str):
        try:
            result = cc.wait_for_result(prompt_id, timeout=600)
            outs = result.get("outputs", {})
            imgs: list[str] = []
            for node_out in outs.values():
                for img in node_out.get("images", []):
                    imgs.append(img.get("filename", ""))
            return imgs[0] if imgs else None
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(len(prompts), 8)) as pool:
        tasks = [loop.run_in_executor(pool, _wait_for, pid) for pid in prompt_ids]
        images = await asyncio.gather(*tasks)

    # 5) 组装帧结果
    frames = [
        StoryboardFrame(
            index=i,
            prompt=prompts[i],
            prompt_id=prompt_ids[i],
            image=images[i] if i < len(images) else None,
            status="success" if images[i] else "error",
        )
        for i in range(len(prompts))
    ]

    return StoryboardResponse(validated=True, frames=frames)


# ── v4.39 视频多段拼接 ──────────────────────────────────────────
@app.post("/api/concat_videos", response_model=ConcatVideosResponse)
async def concat_videos(req: ConcatVideosRequest) -> ConcatVideosResponse:
    """视频多段拼接：使用 ffmpeg concat demuxer 拼接 MP4 文件列表。

    接收 ComfyUI output 目录下的视频文件名列表，按顺序拼接为单个 mp4 文件。
    所有输入文件必须存在于 output_dir 中，格式统一为 h264-mp4（VHS_VideoCombine 默认输出）。
    """
    import subprocess
    import tempfile

    output_dir = Path(_COMFYUI_OUTPUT_DIR)
    if not output_dir.is_dir():
        return ConcatVideosResponse(
            validated=False,
            issues=[f"ComfyUI 输出目录不存在: {output_dir}（请设置 COMFYUI_OUTPUT_DIR 环境变量）"],
        )

    # 1) 校验所有视频文件存在
    missing: list[str] = []
    for name in req.video_names:
        p = output_dir / name
        if not p.is_file():
            missing.append(name)
    if missing:
        return ConcatVideosResponse(
            validated=False,
            issues=[f"以下视频文件不存在: {', '.join(missing[:5])}"],
        )

    # 2) 构建 concat 文件列表
    list_lines = []
    for name in req.video_names:
        p = output_dir / name
        # ffmpeg concat demuxer 需要转义路径（用单引号包裹，内部 ' 替换为 '\\''）
        safe = str(p.resolve()).replace("\\", "/")
        list_lines.append(f"file '{safe}'")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    ) as f:
        f.write("\n".join(list_lines) + "\n")
        list_path = f.name

    # 3) 输出文件名
    out_name = req.output_name or f"ic_concat_{uuid.uuid4().hex[:8]}.mp4"
    out_path = output_dir / out_name

    # 4) 调用 ffmpeg concat
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", list_path,
                    "-c", "copy",  # 流复制避免重编码
                    str(out_path),
                ],
                capture_output=True, text=True, timeout=600,
            ),
        )
    except FileNotFoundError:
        try:
            Path(list_path).unlink(missing_ok=True)
        except Exception:
            pass
        return ConcatVideosResponse(
            validated=False,
            issues=["ffmpeg 未找到，请确保将 ffmpeg 添加到系统 PATH 环境变量"],
        )
    except subprocess.TimeoutExpired:
        try:
            Path(list_path).unlink(missing_ok=True)
        except Exception:
            pass
        return ConcatVideosResponse(
            validated=False, issues=["拼接超时（10 分钟）"],
        )
    finally:
        try:
            Path(list_path).unlink(missing_ok=True)
        except Exception:
            pass

    if result.returncode != 0:
        stderr = (result.stderr or "")[-400:]
        return ConcatVideosResponse(
            validated=False,
            issues=[f"ffmpeg 拼接失败 (code={result.returncode}): {stderr}"],
        )

    if not out_path.is_file():
        return ConcatVideosResponse(
            validated=False, issues=["拼接完成但输出文件丢失"],
        )

    return ConcatVideosResponse(validated=True, filename=out_name)


@app.post("/api/upload", response_model=UploadResponse)
async def upload(req: UploadRequest) -> UploadResponse:
    """上传图片到 ComfyUI input/（供图生图使用）。接收 base64（可含 dataURL 前缀）。"""
    import base64
    raw = req.data_base64
    if "," in raw and raw.strip().lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"base64 解码失败: {str(e)[:120]}")
    if not data:
        raise HTTPException(status_code=400, detail="空图片数据")
    try:
        name = await asyncio.to_thread(cc.upload_image, data, req.filename)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"上传 ComfyUI 失败: {str(e)[:160]}")
    return UploadResponse(name=name)


@app.get("/api/stream/{prompt_id}")
async def stream_progress(prompt_id: str, client_id: str | None = Query(None)):
    """v4.29 SSE 端点：实时流式推送 ComfyUI WebSocket 进度事件。

    前端 EventSource 连接此端点，接收生成过程中的实时进度：
      - status: 队列位置变化
      - start: 执行开始
      - executing: 正在运行的节点 ID
      - progress: KSampler 步进值 (value/max)
      - executed: 某个节点输出完成
      - done: 本 prompt 执行结束
      - error: 执行异常

    用法（前端）：
      const es = new EventSource(`/api/stream/${prompt_id}`);
      es.onmessage = (e) => { const ev = JSON.parse(e.data); ... };
    """
    cid = client_id or cc._DEFAULT_CLIENT_ID

    async def _gen():
        try:
            async for event in cc.ws_listen(cid, prompt_id):
                import json as _json
                yield f"data: {_json.dumps(event, default=str)}\n\n"
        except Exception as e:
            import json as _json
            yield f"data: {_json.dumps({'type': 'error', 'message': str(e)[:200], 'prompt_id': prompt_id})}\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/result/{prompt_id}")
async def get_result(prompt_id: str) -> dict:
    """v4.29 轮询获取生成结果（供 SSE done 事件后调用）。"""
    try:
        result = await asyncio.to_thread(cc.wait_for_result, prompt_id)
        images: list[str] = []
        for node_out in result.get("outputs", {}).values():
            for img in node_out.get("images", []):
                images.append(img.get("filename", ""))
            for g in node_out.get("gifs", []):
                images.append(g.get("filename", ""))
        return {"prompt_id": prompt_id, "images": images, "status": "success"}
    except TimeoutError:
        return {"prompt_id": prompt_id, "images": [], "status": "timeout"}
    except Exception as e:
        return {"prompt_id": prompt_id, "images": [], "status": "error", "message": str(e)[:200]}


# ── v4.40 画布导出（媒体文件 ZIP 打包） ──────────────────────────
class ExportCanvasRequest(BaseModel):
    filenames: list[str]


@app.post("/api/export_canvas")
async def export_canvas(req: ExportCanvasRequest):
    """将画布中所有节点的原始媒体文件（图片/视频）打包为 ZIP 下载。

    接收 ComfyUI output 目录下的文件名列表，读取每个文件并生成 ZIP。
    缺失文件静默跳过，在响应头 X-Missing-Count 中报告数量。
    """
    import zipfile
    import io

    output_dir = Path(_COMFYUI_OUTPUT_DIR)
    if not output_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"ComfyUI 输出目录不存在: {output_dir}（请设置 COMFYUI_OUTPUT_DIR 环境变量）",
        )

    buf = io.BytesIO()
    missing = 0
    added = 0

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in req.filenames:
            fp = output_dir / name
            if not fp.is_file():
                missing += 1
                continue
            # 读取文件并写入 ZIP，保留原始文件名（不添加路径前缀）
            data = fp.read_bytes()
            zf.writestr(name, data)
            added += 1

    if added == 0:
        raise HTTPException(
            status_code=404,
            detail=f"所有文件都不存在：请求 {len(req.filenames)} 个，缺失 {missing} 个",
        )

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="canvas-export-{uuid.uuid4().hex[:8]}.zip"',
            "X-Added-Count": str(added),
            "X-Missing-Count": str(missing),
        },
    )


# ── v5.4 项目导出/发布管线（§11.3）─────────────────────────────────

class ExportProjectRequest(BaseModel):
    """完整项目导出：节点、连线、端口连线、实体、工作流、时间线"""
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    port_edges: list[dict[str, Any]] = []
    layers: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    storyboard_shots: list[dict[str, Any]] = []
    entity_ids: list[str] = []         # 要包含的实体 ID
    workflow_graph: dict[str, Any] | None = None
    include_media: bool = False         # 是否打包媒体文件（大文件）
    export_format: str = "zip"          # zip | json


class ImportProjectRequest(BaseModel):
    """导入项目快照（JSON payload 或 base64 编码的 ZIP）"""
    data: dict[str, Any]                # 项目快照 JSON
    strategy: str = "merge"             # merge（合并）| replace（替换）| preview（仅预览不写入）


@app.post("/api/export_project")
async def export_project(req: ExportProjectRequest):
    """完整项目快照导出 — 包含画布状态 + 实体定义 + 可选媒体文件。

    返回 ZIP 文件（export_format=zip）或 JSON（export_format=json）。
    ZIP 内包含 project.json + 可选 media/ 目录。
    """
    import zipfile
    import io as io_mod
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()

    # 收集实体数据
    entities_data: list[dict[str, Any]] = []
    for eid in req.entity_ids:
        ent = er.get_entity(eid)
        if ent:
            entities_data.append(_entity_to_dict(ent))

    # 构建项目快照
    snapshot: dict[str, Any] = {
        "meta": {
            "exported_at": now_iso,
            "version": "v5.4",
            "app": "infinite-canvas",
            "node_count": len(req.nodes),
            "link_count": len(req.links),
            "port_edge_count": len(req.port_edges),
            "entity_count": len(entities_data),
            "layer_count": len(req.layers),
            "timeline_count": len(req.timeline),
            "storyboard_shot_count": len(req.storyboard_shots),
            "include_media": req.include_media,
        },
        "canvas": {
            "nodes": req.nodes,
            "links": req.links,
            "port_edges": req.port_edges,
            "layers": req.layers,
        },
        "timeline": req.timeline,
        "storyboard_shots": req.storyboard_shots,
        "entities": entities_data,
        "workflow_graph": req.workflow_graph,
    }

    if req.export_format == "json":
        # 纯 JSON 导出（不含媒体文件）
        json_bytes = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=json_bytes,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="canvas-project-{uuid.uuid4().hex[:8]}.json"',
            },
        )

    # ZIP 导出
    buf = io_mod.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 写入 project.json
        zf.writestr("project.json", json.dumps(snapshot, ensure_ascii=False, indent=2))

        # 可选：打包媒体文件
        if req.include_media:
            output_dir = Path(_COMFYUI_OUTPUT_DIR)
            added_files = 0
            for node in req.nodes:
                filename = node.get("filename", "")
                if not filename:
                    continue
                fp = output_dir / filename
                if fp.is_file():
                    zf.write(fp, f"media/{filename}")
                    added_files += 1
            snapshot["meta"]["media_files_included"] = added_files

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="canvas-project-{uuid.uuid4().hex[:8]}.zip"',
        },
    )


@app.post("/api/import_project")
async def import_project(req: ImportProjectRequest):
    """导入项目快照。

    strategy:
      - merge: 合并到现有画布（默认）
      - replace: 清空后替换
      - preview: 仅解析返回摘要，不写入（验证格式用）
    """
    data = req.data
    meta = data.get("meta", {})
    canvas = data.get("canvas", {})
    entities = data.get("entities", [])

    summary = {
        "version": meta.get("version", "unknown"),
        "exported_at": meta.get("exported_at"),
        "node_count": meta.get("node_count", 0),
        "link_count": meta.get("link_count", 0),
        "port_edge_count": meta.get("port_edge_count", 0),
        "entity_count": meta.get("entity_count", 0),
        "layer_count": meta.get("layer_count", 0),
        "timeline_count": meta.get("timeline_count", 0),
        "storyboard_shot_count": meta.get("storyboard_shot_count", 0),
    }

    if req.strategy == "preview":
        return {"strategy": "preview", "summary": summary, "valid": True}

    # merge / replace — 返回数据让前端处理实际状态合并
    imported_entities = 0
    if req.strategy == "replace" or req.strategy == "merge":
        for ent_dict in entities:
            try:
                kind = er.EntityKind(ent_dict.get("kind", "character"))
                # 避免重复导入：按名称查重
                existing = er.search_entities(ent_dict.get("name", ""))
                if existing and req.strategy == "merge":
                    continue
                er.create_entity(
                    kind=kind,
                    name=ent_dict.get("name", "imported"),
                    alias=ent_dict.get("alias", ""),
                    description=ent_dict.get("description", ""),
                    prompt_override=ent_dict.get("prompt_override"),
                    tags=ent_dict.get("tags", []),
                    metadata=ent_dict.get("metadata", {}),
                )
                imported_entities += 1
            except Exception:
                pass

    return {
        "strategy": req.strategy,
        "summary": summary,
        "imported_entities": imported_entities,
        "canvas": canvas,
        "timeline": data.get("timeline", []),
        "storyboard_shots": data.get("storyboard_shots", []),
        "entities": entities,
        "workflow_graph": data.get("workflow_graph"),
    }


# ── v4.50 画布实体系统（§10.1）───────────────────────────────────

class CreateEntityRequest(BaseModel):
    kind: str = Field(..., pattern="^(character|scene|prop|style)$",
                      description="实体类型")
    name: str = Field(..., min_length=1, max_length=128)
    alias: str = ""
    description: str = ""
    prompt_override: str | None = None
    tags: list[str] = []
    anchor_seed: int = 0
    anchor_lora_name: str | None = None
    anchor_controlnet_type: str | None = None
    parent_entity_id: str | None = None
    metadata: dict[str, Any] = {}


class UpdateEntityRequest(BaseModel):
    name: str | None = None
    alias: str | None = None
    description: str | None = None
    prompt_override: str | None = None
    tags: list[str] | None = None
    anchor_seed: int | None = None
    anchor_first_frame_path: str | None = None
    anchor_reference_image_path: str | None = None
    anchor_lora_name: str | None = None
    anchor_controlnet_type: str | None = None
    metadata: dict[str, Any] | None = None


@app.post("/api/entities")
async def create_entity_endpoint(req: CreateEntityRequest) -> dict:
    """创建画布实体（角色/场景/道具/风格）。"""
    anchor = er.VisualAnchor(
        seed=req.anchor_seed,
        lora_name=req.anchor_lora_name,
        controlnet_type=req.anchor_controlnet_type,
    )
    ent = er.create_entity(
        kind=er.EntityKind(req.kind),
        name=req.name,
        alias=req.alias,
        description=req.description,
        prompt_override=req.prompt_override,
        tags=req.tags,
        anchor=anchor,
        parent_entity_id=req.parent_entity_id,
        metadata=req.metadata,
    )
    return {"entity": _entity_to_dict(ent)}


@app.get("/api/entities")
async def list_entities_endpoint(kind: str | None = Query(None, pattern="^(character|scene|prop|style)$")) -> dict:
    """列出所有实体，可选按类型过滤。"""
    k = er.EntityKind(kind) if kind else None
    entities = er.list_entities(kind=k)
    return {"entities": [_entity_to_dict(e) for e in entities]}


@app.get("/api/entities/{entity_id}")
async def get_entity_endpoint(entity_id: str) -> dict:
    """按 ID 获取单个实体。"""
    ent = er.get_entity(entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail=f"实体 '{entity_id}' 不存在")
    return {"entity": _entity_to_dict(ent)}


@app.patch("/api/entities/{entity_id}")
async def update_entity_endpoint(entity_id: str, req: UpdateEntityRequest) -> dict:
    """部分更新实体字段。"""
    anchor_kwargs: dict[str, Any] = {}
    if req.anchor_seed is not None:
        anchor_kwargs["seed"] = req.anchor_seed
    if req.anchor_first_frame_path is not None:
        anchor_kwargs["first_frame_path"] = req.anchor_first_frame_path
    if req.anchor_reference_image_path is not None:
        anchor_kwargs["reference_image_path"] = req.anchor_reference_image_path
    if req.anchor_lora_name is not None:
        anchor_kwargs["lora_name"] = req.anchor_lora_name
    if req.anchor_controlnet_type is not None:
        anchor_kwargs["controlnet_type"] = req.anchor_controlnet_type

    anchor = er.VisualAnchor(**anchor_kwargs) if anchor_kwargs else None

    ent = er.update_entity(
        entity_id,
        name=req.name,
        alias=req.alias,
        description=req.description,
        prompt_override=req.prompt_override,
        tags=req.tags,
        anchor=anchor,
        metadata=req.metadata,
    )
    if ent is None:
        raise HTTPException(status_code=404, detail=f"实体 '{entity_id}' 不存在")
    return {"entity": _entity_to_dict(ent)}


@app.delete("/api/entities/{entity_id}")
async def delete_entity_endpoint(entity_id: str) -> dict:
    """删除实体。"""
    if not er.delete_entity(entity_id):
        raise HTTPException(status_code=404, detail=f"实体 '{entity_id}' 不存在")
    return {"deleted": entity_id}


@app.get("/api/entities/{entity_id}/prompt")
async def get_entity_prompt(entity_id: str) -> dict:
    """获取实体的 prompt 前缀（供工作流使用）。"""
    prompt = er.build_entity_prompt(entity_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"实体 '{entity_id}' 不存在")
    return {"entity_id": entity_id, "prompt": prompt}


@app.get("/api/entities/search")
async def search_entities_endpoint(q: str = Query(..., min_length=1)) -> dict:
    """按名称/别名/标签模糊搜索实体。"""
    results = er.search_entities(q)
    return {"query": q, "entities": [_entity_to_dict(e) for e in results]}


def _entity_to_dict(ent: er.Entity) -> dict:
    return {
        "entity_id": ent.entity_id,
        "kind": ent.kind.value,
        "name": ent.name,
        "alias": ent.alias,
        "description": ent.description,
        "prompt_override": ent.prompt_override,
        "tags": ent.tags,
        "anchor": {
            "seed": ent.anchor.seed,
            "first_frame_path": ent.anchor.first_frame_path,
            "reference_image_path": ent.anchor.reference_image_path,
            "lora_name": ent.anchor.lora_name,
            "controlnet_type": ent.anchor.controlnet_type,
        },
        "parent_entity_id": ent.parent_entity_id,
        "children_ids": ent.children_ids,
        "metadata": ent.metadata,
        "created_at": ent.created_at,
        "updated_at": ent.updated_at,
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "comfyui_url": cc.COMFYUI_URL}


# ── v5.0 工作流执行链（LibTV 风格：连线即执行）────────────────


class ExecuteChainRequest(BaseModel):
    """工作流链式执行请求。"""
    root_node_id: str
    nodes: list[dict[str, Any]]    # CanvasNode 列表（含 kind/prompt/ports 等）
    port_edges: list[dict[str, Any]] = []  # PortEdge 列表


@app.post("/api/workflow/execute-chain")
async def execute_chain_endpoint(req: ExecuteChainRequest) -> dict:
    """沿端口连线拓扑排序 → 逐个节点执行生成 → 汇总结果。

    这是 v5.0 的核心端点："拖线连接多个节点 → 一键全链路生成"。

    请求体:
        root_node_id: 链路起点节点 ID
        nodes: 画布节点列表（每个节点含 kind/prompt/ports/mode 等字段）
        port_edges: 端口间连线

    返回:
        results: [{"node_id", "status", "output_file", "prompt_id", "error"}, ...]
    """
    from workflow_executor import execute_chain as _exec
    results = _exec(req.root_node_id, req.nodes, req.port_edges, wait=True)
    return {
        "results": [
            {
                "node_id": r.node_id,
                "status": r.status,
                "output_file": r.output_file,
                "prompt_id": r.prompt_id,
                "error": r.error,
            }
            for r in results
        ],
    }


@app.get("/api/image/{filename}")
async def get_image(filename: str) -> Response:
    """代理 ComfyUI 输出图片（/view），前端画布经同源 /api/image 加载，免 CORS。"""
    try:
        data, ctype = await asyncio.to_thread(cc.get_image_bytes, filename)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)[:200])
    return Response(content=data, media_type=ctype)


# ═══════════════════════════════════════════════════════════════
# v5.2 端口连线后端 CRUD（POST/GET/DELETE）
# ═══════════════════════════════════════════════════════════════

_PORT_EDGES_FILE = Path(__file__).parent / "data" / "port_edges.json"


class PortEdgeItem(BaseModel):
    id: str
    fromPortId: str = Field(default="")
    toPortId: str = Field(default="")
    label: str | None = None


class PortEdgesPayload(BaseModel):
    """批量保存全部端口连线（前端完整状态同步）"""
    edges: list[PortEdgeItem]


def _load_port_edges() -> list[dict[str, Any]]:
    """从 JSON 文件加载端口连线（容错）。"""
    if not _PORT_EDGES_FILE.exists():
        return []
    try:
        data = json.loads(_PORT_EDGES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_port_edges(edges: list[dict[str, Any]]) -> None:
    """保存端口连线到 JSON 文件。"""
    _PORT_EDGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PORT_EDGES_FILE.write_text(
        json.dumps(edges, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@app.post("/api/port-edges")
async def save_port_edges(payload: PortEdgesPayload):
    """批量保存端口连线（完整覆盖模式）。

    前端每次画布编辑后调用此接口同步全量 portEdges 到后端。
    覆盖写入，非增量追加。
    """
    edges_data = [e.model_dump() for e in payload.edges]
    await asyncio.to_thread(_save_port_edges, edges_data)
    return {"status": "ok", "count": len(edges_data)}


@app.get("/api/port-edges")
async def get_port_edges():
    """获取全部端口连线列表。"""
    edges = await asyncio.to_thread(_load_port_edges)
    return {"edges": edges, "count": len(edges)}


@app.delete("/api/port-edges/{edge_id}")
async def delete_port_edge(edge_id: str):
    """删除指定端口连线。"""
    edges = await asyncio.to_thread(_load_port_edges)
    before = len(edges)
    edges = [e for e in edges if e.get("id") != edge_id]
    after = len(edges)
    await asyncio.to_thread(_save_port_edges, edges)
    return {"status": "ok", "deleted": before - after > 0, "remaining": after}


@app.delete("/api/port-edges")
async def clear_port_edges():
    """清空所有端口连线（画布重置时调用）。"""
    await asyncio.to_thread(_save_port_edges, [])
    return {"status": "ok", "deleted_all": True}


# ═══════════════════════════════════════════════════════════════
# v5.2 音频生成端点
# ═══════════════════════════════════════════════════════════════

class AudioTTSRequest(BaseModel):
    text: str
    speaker: str = "default"
    speed: float = 1.0
    emotion: str = "neutral"
    output_format: str = "wav"


class AudioMusicRequest(BaseModel):
    prompt: str
    duration: float = 30.0
    tempo: int = 120
    output_format: str = "wav"


@app.post("/api/audio/generate")
async def audio_generate(req: AudioTTSRequest):
    """TTS 语音合成 (CosyVoice2)。

    优先通过 ComfyUI CosyVoice 节点生成，回退为直接 subprocess 调用。
    """
    blueprint = ab.cosyvoice_tts_workflow(
        text=req.text,
        speaker=req.speaker,
        speed=req.speed,
        emotion=req.emotion,
        output_format=req.output_format,
    )
    if blueprint.get("_status") == "placeholder":
        return {
            "status": "unavailable",
            "message": "CosyVoice2 ComfyUI 节点未安装，请通过 ComfyUI Manager 安装 ComfyUI-CosyVoice",
            "blueprint": blueprint["_meta"],
        }
    # 提交 ComfyUI 工作流
    try:
        prompt_id = cc.submit_workflow(blueprint["workflow"])
        return {
            "status": "submitted",
            "prompt_id": prompt_id,
            "blueprint": blueprint["_meta"],
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:500],
            "blueprint": blueprint["_meta"],
        }


@app.post("/api/audio/music")
async def audio_music(req: AudioMusicRequest):
    """音乐生成 (MusicGen / Stable Audio)。"""
    blueprint = ab.musicgen_workflow(
        prompt=req.prompt,
        duration=req.duration,
        tempo=req.tempo,
        output_format=req.output_format,
    )
    if blueprint.get("_status") == "placeholder":
        return {
            "status": "unavailable",
            "message": "MusicGen ComfyUI 节点未安装",
            "blueprint": blueprint["_meta"],
        }
    try:
        prompt_id = cc.submit_workflow(blueprint["workflow"])
        return {
            "status": "submitted",
            "prompt_id": prompt_id,
            "blueprint": blueprint["_meta"],
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:500],
            "blueprint": blueprint["_meta"],
        }
