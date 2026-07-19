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
import intent_map as im

app = FastAPI(title="Infinite Canvas Agent", version="0.3.0")

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


class IntentResponse(BaseModel):
    action: str
    subject: str
    style: str
    elements: list[str] = []
    params: dict = {}


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
    return IntentResponse(
        action=intent.get("action", "txt2img"),
        subject=intent.get("subject", ""),
        style=intent.get("style", ""),
        elements=intent.get("elements", []),
        params=intent.get("params", {}),
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
            req.prop_image, req.prop_weight)

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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "comfyui_url": cc.COMFYUI_URL}


@app.get("/api/image/{filename}")
async def get_image(filename: str) -> Response:
    """代理 ComfyUI 输出图片（/view），前端画布经同源 /api/image 加载，免 CORS。"""
    try:
        data, ctype = await asyncio.to_thread(cc.get_image_bytes, filename)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)[:200])
    return Response(content=data, media_type=ctype)
