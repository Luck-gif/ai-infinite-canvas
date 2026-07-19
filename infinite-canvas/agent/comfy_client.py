"""无限画布 · ComfyUI 客户端（对接原生 ComfyUI Desktop @ 8188 + 共享模型库）。

设计要点（§6.7.1 / §16.4 / §16.9）：
- 通过 HTTP API 与**运行中的原生 ComfyUI**通信，不 fork/修改 ComfyUI，仅 API 调用 → 不触发 GPL 传染（§9.3）。
- 工作流节点 class_type / 参数经 `/object_info` 动态校验（非硬编码），即「ComfyUI 工作流校验器」核心。
- 共享模型库见 `C:/ai_comfyui_dd/models`（Comfy Desktop 默认 base_path）。

默认指向本机原生 ComfyUI（端口 8188），可用环境变量 COMFYUI_URL 覆盖。
"""
from __future__ import annotations

import os
import time
import uuid
import asyncio
from typing import Any, AsyncIterator

import json
import urllib.error
import urllib.parse
import urllib.request

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
_DEFAULT_CLIENT_ID = f"infinite-canvas-{uuid.uuid4().hex[:8]}"

# 共享模型库默认 base_path（与 shared_model_paths.yaml 中 comfy.desktop_0 对齐）
SHARED_MODEL_LIB = os.environ.get("SHARED_MODEL_LIB", r"C:\ai_comfyui_dd\models")

_object_info_cache: dict[str, Any] | None = None

# 核心节点白名单：ComfyUI 原生必含；/object_info 不可用时降级校验用（§6.7.1 动态校验优先，此为兜底）
_CORE_NODES: set[str] = {
    "KSampler", "KSamplerAdvanced", "CheckpointLoaderSimple", "CLIPLoader",
    "CLIPTextEncode", "EmptyLatentImage", "VAELoader", "VAEDecode",
    "SaveImage", "LoadImage", "UNETLoader",
}


def get_object_info(force: bool = False) -> dict[str, Any]:
    """拉取 ComfyUI 已注册节点 schema（带缓存，启动/变更时 force 刷新）。

    含重试：ComfyUI Desktop 的 manager 代理偶发 502，重试可恢复；
    仍失败时由 validate_workflow 降级到核心节点白名单。
    """
    global _object_info_cache
    if _object_info_cache is None or force:
        info: dict[str, Any] | None = None
        last: Exception | None = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(f"{COMFYUI_URL}/object_info")
                with urllib.request.urlopen(req, timeout=60) as r:
                    info = json.loads(r.read().decode())
                    break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (attempt + 1))
        if info is None:
            raise RuntimeError(f"ComfyUI /object_info 不可用（{last!r}）")
        _object_info_cache = info
    assert _object_info_cache is not None  # 缓存此时必已填充
    return _object_info_cache


# ── 工作流可视化（前端无限画布内节点图，商业级 UI 参考）──
# class_type → (中文标题, 分类) ；分类驱动前端配色与图例
_NODE_META: dict[str, tuple[str, str]] = {
    "KSampler": ("采样器", "sample"),
    "KSamplerAdvanced": ("采样器(高阶)", "sample"),
    "CheckpointLoaderSimple": ("大模型加载", "model"),
    "UNETLoader": ("UNet 加载", "model"),
    "VAELoader": ("VAE 加载", "model"),
    "CLIPLoader": ("文本编码器", "model"),
    "CLIPLoaderGGUF": ("文本编码器", "model"),
    "CLIPTextEncode": ("提示词编码", "cond"),
    "EmptyLatentImage": ("空潜空间", "latent"),
    "LoadImage": ("加载图片", "io"),
    "LoadImageMask": ("加载蒙版", "io"),
    "VAEEncode": ("VAE 编码", "vae"),
    "VAEEncodeForInpaint": ("VAE 编码(重绘)", "vae"),
    "VAEDecode": ("VAE 解码", "vae"),
    "SaveImage": ("保存图片", "io"),
    "VHS_VideoCombine": ("视频合成", "io"),
    "LoraLoader": ("LoRA 注入", "model"),
    "LoraLoaderModelOnly": ("LoRA 注入", "model"),
    "ControlNetLoader": ("ControlNet 加载", "model"),
    "SetUnionControlNetType": ("控制类型", "model"),
    "ControlNetApply": ("ControlNet 应用", "cond"),
    "ControlNetApplyAdvanced": ("ControlNet 应用", "cond"),
    "WanImageToVideo": ("Wan 视频潜空间", "latent"),
    "ModelSamplingSD3": ("采样参数", "sample"),
    "WanVideoModelLoader": ("Wan 模型加载", "model"),
}


def _is_link(v: Any) -> bool:
    """判断是否为 ComfyUI 连线引用 [源节点, 输出槽]（恰好两元素，第二为整型槽号）。"""
    if not isinstance(v, list) or len(v) != 2:
        return False
    return isinstance(v[1], int) and isinstance(v[0], (str, int))


def _short_val(v: Any, limit: int = 30) -> str:
    s = str(v)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _count_outputs(wf: dict, nid: str) -> int:
    out = 0
    for node in wf.values():
        for val in (node.get("inputs") or {}).values():
            if _is_link(val) and str(val[0]) == str(nid):
                out += 1
    return out


def _assign_layout(nodes: list[dict], edges: list[dict]) -> None:
    """分层 DAG 布局：拓扑层级 → 列(x)，层内序号 → 行(y)。无需外部依赖。"""
    ids = [n["id"] for n in nodes]
    idset = set(ids)
    incoming: dict[str, list[str]] = {i: [] for i in ids}
    outgoing: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        if e["from"] in idset and e["to"] in idset:
            incoming[e["to"]].append(e["from"])
            outgoing[e["from"]].append(e["to"])

    # Kahn 拓扑序
    indeg = {i: len(incoming[i]) for i in ids}
    from collections import deque
    q = deque([i for i in ids if indeg[i] == 0])
    topo: list[str] = []
    while q:
        n = q.popleft()
        topo.append(n)
        for m in outgoing[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)

    # 层级 = 前驱最大层级 + 1（根节点为 0）
    level: dict[str, int] = {}
    for i in topo:
        preds = incoming[i]
        level[i] = 0 if not preds else max(level[p] for p in preds) + 1

    by_level: dict[int, list[str]] = {}
    for i in ids:
        by_level.setdefault(level[i], []).append(i)

    col_w, row_h = 260, 132
    for lv, members in by_level.items():
        for order, i in enumerate(sorted(members)):
            for n in nodes:
                if n["id"] == i:
                    n["pos"] = {"x": lv * col_w, "y": order * row_h}
                    break


def workflow_to_graph(wf: dict) -> dict:
    """将 ComfyUI API 格式工作流转换为前端节点图（带分层布局坐标）。

    返回 {"nodes":[...], "edges":[...], "layout":"dag"}。
    - nodes 含 id/type/title/category/pos/input_links/values/num_outputs
    - edges 含 from/from_slot/to/to_slot
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    link_inputs: dict[str, list[tuple[str, str, int]]] = {}

    for nid, node in wf.items():
        inputs = node.get("inputs", {}) or {}
        links: list[tuple[str, str, int]] = []
        for k, v in inputs.items():
            if _is_link(v):
                links.append((str(k), str(v[0]), int(v[1])))
        link_inputs[str(nid)] = links

        ct = node.get("class_type", "Node")
        title, cat = _NODE_META.get(ct, (ct, "other"))
        values: dict[str, str] = {}
        for k, v in inputs.items():
            if not _is_link(v):
                values[str(k)] = _short_val(v)

        nodes.append({
            "id": str(nid),
            "type": ct,
            "title": title,
            "category": cat,
            "input_links": [{"name": k, "from": src, "from_slot": idx} for (k, src, idx) in links],
            "values": values,
            "num_outputs": _count_outputs(wf, str(nid)),
            "pos": {"x": 0, "y": 0},
        })

    for nid, links in link_inputs.items():
        for (k, src, idx) in links:
            edges.append({"from": str(src), "from_slot": idx, "to": str(nid), "to_slot": k})

    _assign_layout(nodes, edges)
    return {"nodes": nodes, "edges": edges, "layout": "dag"}


def validate_workflow(wf: dict[str, Any], allow_degraded: bool = True) -> tuple[bool, list[str]]:
    """用 /object_info 校验工作流：每个节点的 class_type 必须存在。

    返回 (ok, issues)。issues 非空时 ok=False。
    （§6.7.1：节点不硬编码，优先经动态 schema 校验；
      manager 代理偶发 502 致 /object_info 不可用时，降级到核心节点白名单。）
    """
    try:
        info = get_object_info()
    except RuntimeError:
        if not allow_degraded:
            raise
        import sys as _sys
        print("[warn] /object_info 不可用，降级到核心节点白名单校验", file=_sys.stderr)
        info = None

    issues: list[str] = []
    for nid, node in wf.items():
        ct = node.get("class_type")
        if not ct:
            issues.append(f"节点 {nid}: 缺 class_type")
            continue
        if info is not None:
            if ct not in info:
                issues.append(f"节点 {nid}: class_type '{ct}' 在运行中的 ComfyUI 不存在")
        elif ct not in _CORE_NODES:
            issues.append(f"节点 {nid}: '{ct}' 不在核心节点白名单（/object_info 不可用降级校验）")
    return (len(issues) == 0, issues)


def submit_workflow(wf: dict[str, Any], client_id: str | None = None, tries: int = 3) -> str:
    """提交工作流到 /prompt，返回 prompt_id（含重试抵御代理 502）。"""
    cid = client_id or _DEFAULT_CLIENT_ID
    last: Exception | None = None
    for i in range(tries):
        try:
            payload = json.dumps({"prompt": wf, "client_id": cid}).encode()
            req = urllib.request.Request(
                f"{COMFYUI_URL}/prompt", data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())["prompt_id"]
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"/prompt 提交失败（{last!r}）")


def wait_for_result(prompt_id: str, timeout: int = 600, poll: float = 2.0) -> dict[str, Any]:
    """轮询 /history/{prompt_id} 直到完成或超时，返回该 prompt 的输出（连接抖动重试）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{COMFYUI_URL}/history/{prompt_id}")
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            if prompt_id in data:
                return data[prompt_id]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(poll)
    raise TimeoutError(f"prompt {prompt_id} 在 {timeout}s 内未完成")


# ── v4.29 WebSocket 进度流 ──────────────────────────────────────────
async def ws_listen(client_id: str, prompt_id: str, timeout: float = 600.0) -> "AsyncIterator[dict]":
    """异步连接 ComfyUI WebSocket，yield 进度事件 dict（供 SSE 端点消费）。

    使用 `websockets` 库（已在 requirements.txt）连接 ws://.../ws?clientId=...，
    解析 ComfyUI WS 消息并筛选与 prompt_id 相关的事件：
      - status: 队列位置
      - execution_start: 开始执行
      - executing: 哪个节点正在运行（node=null 时表示本 prompt 执行完成）
      - progress: KSampler 步骤进度 (value/max)
      - executed: 节点输出完成
      - execution_error: 执行错误
      结束事件: {"type":"done"} / {"type":"error", "message":...} / {"type":"timeout"}
    """
    import websockets  # type: ignore[import-untyped]
    ws_url = COMFYUI_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={client_id}"
    loop = asyncio.get_running_loop()
    start = loop.time()
    try:
        async with websockets.connect(ws_url, ping_interval=30, close_timeout=10, max_size=2**20) as ws:
            while (loop.time() - start) < timeout:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
                except asyncio.TimeoutError:
                    yield {"type": "heartbeat", "prompt_id": prompt_id}
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                t = msg.get("type", "")
                d = msg.get("data", {})
                pid = d.get("prompt_id", "")
                # 只关注我们的 prompt_id（status 消息无 prompt_id，始终推送）
                if t == "status":
                    yield {"type": "status", "queue_remaining": d.get("status", {}).get("exec_info", {}).get("queue_remaining", 0), "prompt_id": prompt_id}
                elif pid != prompt_id and t not in ("status",):
                    continue
                elif t == "execution_start":
                    yield {"type": "start", "prompt_id": prompt_id}
                elif t == "execution_cached":
                    yield {"type": "cached", "nodes": d.get("nodes", []), "prompt_id": prompt_id}
                elif t == "executing":
                    node_id = d.get("node")
                    yield {"type": "executing", "node": node_id, "display_node": d.get("display_node"), "prompt_id": prompt_id}
                    if node_id is None:
                        yield {"type": "done", "prompt_id": prompt_id}
                        return
                elif t == "progress":
                    yield {"type": "progress", "value": d["value"], "max": d["max"], "node": d.get("node"), "prompt_id": prompt_id}
                elif t == "executed":
                    yield {"type": "executed", "node": d.get("node"), "prompt_id": prompt_id}
                elif t == "execution_error":
                    yield {"type": "error", "message": str(d.get("exception_message", ""))[:300], "prompt_id": prompt_id}
                    return
            yield {"type": "timeout", "prompt_id": prompt_id}
    except Exception as e:
        yield {"type": "error", "message": str(e)[:200], "prompt_id": prompt_id}


# ── 工作流蓝图构建 ──────────────────────────────────────────────
def build_face_consistency(
    face_image: str,
    checkpoint: str,
    prompt: str = "a beautiful scenery",
    negative: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
    face_weight: float = 0.8,
) -> dict[str, Any]:
    """构造角色一致性工作流（v4.33, Phase 8）。

    使用 IPAdapterFaceID + InsightFace 实现人脸跨图保持一致：
    1. LoadImage 加载参考人脸图
    2. IPAdapterInsightFaceLoader 加载人脸检测模型
    3. CheckpointLoaderSimple 加载 SDXL checkpoint
    4. IPAdapterUnifiedLoaderFaceID 加载 FaceID preset
    5. IPAdapterFaceID 将人脸特征注入模型
    6. 标准 KSampler → VAEDecode → SaveImage 出图
    """
    prefix = uuid.uuid4().hex[:8]
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": face_image}},
        "2": {"class_type": "IPAdapterInsightFaceLoader",
              "inputs": {"provider": "CPU", "model_name": "buffalo_l"}},
        "3": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": checkpoint}},
        "4": {"class_type": "IPAdapterUnifiedLoaderFaceID",
              "inputs": {"model": ["3", 0], "preset": "FACEID PLUS V2",
                         "lora_strength": 0.0, "provider": "CPU"}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["3", 1]}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["3", 1]}},
        "7": {"class_type": "IPAdapterFaceID",
              "inputs": {
                  "model": ["3", 0],
                  "ipadapter": ["4", 0],
                  "image": ["1", 0],
                  "weight": face_weight,
                  "weight_faceidv2": face_weight,
                  "weight_type": "linear",
                  "combine_embeds": "concat",
                  "start_at": 0.0,
                  "end_at": 1.0,
                  "embeds_scaling": "V only",
                  "insightface": ["2", 0],
              }},
        "8": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "9": {"class_type": "KSampler",
              "inputs": {
                  "model": ["7", 0],
                  "seed": seed,
                  "steps": steps,
                  "cfg": cfg,
                  "sampler_name": "euler",
                  "scheduler": "normal",
                  "positive": ["5", 0],
                  "negative": ["6", 0],
                  "latent_image": ["8", 0],
                  "denoise": 1.0,
              }},
        "10": {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": ["3", 2]}},
        "11": {"class_type": "SaveImage",
               "inputs": {"images": ["10", 0], "filename_prefix": f"infinite_canvas_face/{prefix}"}},
    }


def build_image_blend(
    image_a: str,
    image_b: str,
    blend_mode: str = "normal",
    blend_factor: float = 0.5,
) -> dict[str, Any]:
    """多图融合工作流（v4.34, Phase 9）。

    两张图片通过 ImageBlend 节点按指定模式和强度混合：
    1. LoadImage A → ImageBlend(image1)
    2. LoadImage B → ImageBlend(image2)
    3. ImageBlend(blend_factor, blend_mode) → SaveImage

    blend_mode: normal / add / multiply / screen / overlay / soft_light / difference / darken / lighten / color_dodge / color_burn / linear_dodge / linear_burn / hue / saturation / color / luminosity / subtract / divide
    """
    prefix = uuid.uuid4().hex[:8]
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_a}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image_b}},
        "3": {"class_type": "ImageBlend",
              "inputs": {
                  "image1": ["1", 0],
                  "image2": ["2", 0],
                  "blend_factor": blend_factor,
                  "blend_mode": blend_mode,
              }},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": f"infinite_canvas_blend/{prefix}"}},
    }


def build_txt2img(
    checkpoint: str,
    prompt: str = "a beautiful scenery",
    negative: str = "",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
    batch_size: int = 1,
) -> dict[str, Any]:
    """构造最小可用 txt2img 工作流（CheckpointLoaderSimple 自带 CLIP+VAE）。

    默认 checkpoint 取自共享库 checkpoints/ 下已装模型。
    """
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg,
                "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": max(1, batch_size)}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "infinite_canvas"}},
    }


def build_img2img(
    checkpoint: str,
    image_name: str,
    prompt: str = "a beautiful scenery",
    negative: str = "",
    denoise: float = 0.6,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
    loras: list[dict[str, Any]] | None = None,
    controlnets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """构造图生图工作流（§6.1.2）：LoadImage → VAEEncode → KSampler(denoise<1)。

    - image_name 为已上传到 ComfyUI input/ 的文件名（见 upload_image）。
    - denoise 0.3~0.8 常用；越低越贴近原图（§6.1.2 表）。
    - VAE 取自 checkpoint（CheckpointLoaderSimple 第 3 输出）。
    - loras：[{name, strength}]（§6.22 LoRA 节点化）。
    - controlnets：[{model, type?, strength, image, preprocessor?}]（§6.23 ControlNet 节点化）。
      type 仅对 union 模型（文件名含 'union'）有效，经 SetUnionControlNetType 指定；
      其余模型（如 anima-lllite）直传原图，不指定 type。
    """
    wf: dict[str, Any] = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg,
                "sampler_name": "euler", "scheduler": "normal",
                "denoise": max(0.05, min(1.0, denoise)),
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["11", 0],
            },
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "infinite_canvas"}},
        "10": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["4", 2]}},
    }
    # ── LoRA 注入（§6.22）：将 checkpoint 的 model/clip 经 LoraLoader 链 ──
    # loras: [{name, strength}]，strength 同时作用于 model 与 clip。
    if loras:
        cur_model, cur_clip = ["4", 0], ["4", 1]
        for i, lr in enumerate(loras or []):
            nid = f"lora{i}"
            name = lr.get("name") if isinstance(lr, dict) else str(lr)
            st = float(lr.get("strength", 1.0)) if isinstance(lr, dict) else 1.0
            wf[nid] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": cur_model, "clip": cur_clip,
                    "lora_name": name,
                    "strength_model": st, "strength_clip": st,
                },
            }
            cur_model, cur_clip = [nid, 0], [nid, 1]
        wf["3"]["inputs"]["model"] = cur_model
        wf["6"]["inputs"]["clip"] = cur_clip
        wf["7"]["inputs"]["clip"] = cur_clip
    # ── ControlNet 注入（§6.23）：conditioning 经 ControlNetApply 链 ──
    # controlnets: [{model, type?, strength, image, preprocessor?}]
    #   - 每项为一张控制图：预处理器(可选) → 提示图；ControlNetLoader；
    #     union 模型须 SetUnionControlNetType(type)；ControlNetApply 串接正条件。
    if controlnets:
        cur_pos = ["6", 0]  # 当前正条件（初值=原始 CLIPTextEncode）
        for i, cn in enumerate(controlnets or []):
            model = cn.get("model") if isinstance(cn, dict) else str(cn)
            ctype = cn.get("type") if isinstance(cn, dict) else None
            strength = float(cn.get("strength", 1.0)) if isinstance(cn, dict) else 1.0
            cimg = cn.get("image") if isinstance(cn, dict) else image_name
            # 预处理器：优先显式指定，否则按 union type 从注册表推导（单源）
            pre = cn.get("preprocessor") if isinstance(cn, dict) else None
            if not pre and ctype:
                pre = CONTROLNET_PREPROC.get(ctype)
            # 控制图加载（与底图独立节点）
            limg = f"cnimg{i}"
            wf[limg] = {"class_type": "LoadImage", "inputs": {"image": cimg}}
            # 提示图（预处理器可选）
            if pre:
                hint = [f"cnpre{i}", 0]
                wf[f"cnpre{i}"] = {"class_type": pre, "inputs": {"image": [limg, 0]}}
            else:
                hint = [limg, 0]
            # 加载 controlnet + 如需指定 union 类型
            wf[f"cnld{i}"] = {"class_type": "ControlNetLoader",
                                "inputs": {"control_net_name": model}}
            cn_node = [f"cnld{i}", 0]
            if ctype:  # 仅 union 模型
                wf[f"cntyp{i}"] = {"class_type": "SetUnionControlNetType",
                                     "inputs": {"control_net": cn_node, "type": ctype}}
                cn_node = [f"cntyp{i}", 0]
            # 串接到正条件
            wf[f"cnapply{i}"] = {
                "class_type": "ControlNetApply",
                "inputs": {
                    "conditioning": cur_pos,
                    "control_net": cn_node,
                    "image": hint,
                    "strength": strength,
                },
            }
            cur_pos = [f"cnapply{i}", 0]
        wf["3"]["inputs"]["positive"] = cur_pos
    return wf


# ── ControlNet 运行时校验出的合法 union 类型与预处理器映射（§6.23）──
# 取自 ComfyUI /prompt 校验（SetUnionControlNetType.type 经 object_info 仅序列为 'COMBO'，
# 无法静态枚举，故以运行时「假 checkpoint + 真实 union 模型」提交，捕获 node_errors
# 得到权威合法集合）。逐一配对应预处理器，端到端出图验证通过。
CONTROLNET_UNION_TYPES: list[str] = [
    "auto", "openpose", "depth", "hed/pidi/scribble/ted",
    "canny/lineart/anime_lineart/mlsd", "normal", "segment", "tile", "repaint",
]
CONTROLNET_PREPROC: dict[str, str | None] = {
    "auto": None,
    "openpose": "OpenposePreprocessor",
    "depth": "DepthAnythingPreprocessor",
    "hed/pidi/scribble/ted": "ScribblePreprocessor",
    "canny/lineart/anime_lineart/mlsd": "CannyEdgePreprocessor",
    "normal": "BAE-NormalMapPreprocessor",
    "segment": "OneFormer-ADE20K-SemSegPreprocessor",
    "tile": "TilePreprocessor",
    "repaint": None,
}


def build_inpaint(
    checkpoint: str,
    image_name: str,
    mask_name: str,
    prompt: str = "a beautiful scenery",
    negative: str = "",
    denoise: float = 1.0,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
    grow_mask_by: int = 6,
) -> dict[str, Any]:
    """构造局部重绘工作流（§6.1.4）：LoadImage + LoadImageMask → VAEEncodeForInpaint → KSampler。

    - image_name：底图（已上传到 ComfyUI input/）。
    - mask_name：蒙版图（黑底 + 白色为待重绘区，已上传到 input/）；经 LoadImageMask
      取 red 通道为 MASK（白=1.0=重绘）。
    - grow_mask_by：向外扩张蒙版像素数（默认 6，令接缝更自然，§6.1.4）。
    - denoise：inpaint 常用 1.0（全新填充）；调低可保留原区域更多结构。
    - VAE 取自 checkpoint（CheckpointLoaderSimple 第 3 输出）。
    """
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg,
                "sampler_name": "euler", "scheduler": "normal",
                "denoise": max(0.05, min(1.0, denoise)),
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["11", 0],
            },
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "infinite_canvas"}},
        "10": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "12": {"class_type": "LoadImageMask", "inputs": {"image": mask_name, "channel": "red"}},
        "11": {
            "class_type": "VAEEncodeForInpaint",
            "inputs": {
                "pixels": ["10", 0], "vae": ["4", 2], "mask": ["12", 0],
                "grow_mask_by": max(0, int(grow_mask_by)),
            },
        },
    }


def upload_image(data: bytes, filename: str, overwrite: bool = True) -> str:
    """上传图片到 ComfyUI input/（POST /upload/image, multipart），返回存储文件名。

    用 urllib 手工构造 multipart/form-data（规避 manager 代理对 httpx 的 502，§16.4）。
    """
    safe = os.path.basename(filename) or f"upload_{uuid.uuid4().hex[:8]}.png"
    boundary = f"----InfiniteCanvas{uuid.uuid4().hex}"
    ctype = "image/png" if safe.lower().endswith(".png") else "image/jpeg"
    parts: list[bytes] = []
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="image"; filename="{safe}"\r\n'.encode()
    )
    parts.append(f"Content-Type: {ctype}\r\n\r\n".encode())
    parts.append(data)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(b'Content-Disposition: form-data; name="overwrite"\r\n\r\n')
    parts.append(b"true" if overwrite else b"false")
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        f"{COMFYUI_URL}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
    return resp.get("name", safe)


def build_txt2img_qwen(
    unet: str,
    clip: str,
    vae: str,
    prompt: str = "a beautiful scenery",
    negative: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 7.0,
    seed: int = 0,
    batch_size: int = 1,
) -> dict[str, Any]:
    """构造 Qwen-Image 2.0 文生图工作流（分离加载 UNET+CLIP+VAE，Apache 2.0 优先，§6.0.4 / §6.7）。

    模型文件取自共享库真实文件名（并经 /object_info 枚举校验合法）：
      unet  = qwen_image_2512_fp8_e4m3fn.safetensors
      clip  = qwen_2.5_vl_7b_fp8_scaled.safetensors（CLIPLoader type=qwen_image）
      vae   = qwen_image_vae.safetensors
    """
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "qwen_image"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": max(1, batch_size)}},
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg,
                "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                "latent_image": ["6", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "infinite_canvas"}},
    }


def list_checkpoints() -> list[str]:
    """列出共享库 checkpoints/ 下可用 .safetensors 模型（去 metadata.json）。"""
    import glob
    import os as _os
    d = _os.path.join(SHARED_MODEL_LIB, "checkpoints")
    if not _os.path.isdir(d):
        return []
    return sorted(
        _os.path.basename(p)
        for p in glob.glob(_os.path.join(d, "*.safetensors"))
    )


def list_loras() -> list[str]:
    """共享模型库 loras/ 已装 LoRA（§6.22）。返回文件名（含 .safetensors）。"""
    import glob
    import os as _os
    d = _os.path.join(SHARED_MODEL_LIB, "loras")
    if not _os.path.isdir(d):
        return []
    return sorted(
        _os.path.basename(p)
        for p in glob.glob(_os.path.join(d, "*.safetensors"))
    )


def list_controlnets() -> list[str]:
    """共享模型库 controlnet/ 已装 ControlNet（§6.23）。返回文件名（含 .safetensors）。"""
    import glob
    import os as _os
    d = _os.path.join(SHARED_MODEL_LIB, "controlnet")
    if not _os.path.isdir(d):
        return []
    return sorted(
        _os.path.basename(p)
        for p in glob.glob(_os.path.join(d, "*.safetensors"))
    )


def get_image_bytes(filename: str, img_type: str = "output") -> tuple[bytes, str]:
    """从 ComfyUI 目录取图（经官方 /view API，避免依赖本地绝对路径）。

    - img_type="output"（默认）：output/ 生成结果；"input"：input/ 已上传图（扩图需读原图）。
    - 防路径穿越：仅接受 basename（拒绝含 '/' 或 '..' 的输入）。
    - 返回 (bytes, content_type)，交由上层直接回写为 HTTP 响应。
    """
    safe = os.path.basename(filename)
    if safe != filename or not safe:
        raise ValueError(f"非法文件名（疑似路径穿越）：{filename!r}")
    url = (
        f"{COMFYUI_URL}/view?filename={urllib.parse.quote(safe)}"
        f"&subfolder=&type={img_type}"
    )
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as r:
        ctype = r.headers.get("Content-Type", "image/png")
        return r.read(), ctype


def build_outpaint(
    checkpoint: str,
    image_name: str,
    direction: str = "right",
    pixels: int = 256,
    prompt: str = "a beautiful scenery",
    negative: str = "",
    denoise: float = 1.0,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
    grow_mask_by: int = 8,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """构造扩图（Outpainting）工作流（§6.1.5）：复用标准 VAEEncodeForInpaint。

    做法（不依赖版本敏感的 vae_output 参数，最大兼容 ComfyUI 各版本）：
      1. 下载原图 → PIL 按 direction 向一侧/四周 pad 到扩展尺寸（扩展区先填黑）；
      2. 生成 mask：扩展区=白(255)、原图区=黑(0)；
      3. 以「padded 图 + mask」走普通 inpaint（denoise=1.0），
         原图区 mask=0 被 VAE 保留，扩展区 mask=1 由 KSampler 重绘生成连贯内容。
    - image_name：已上传到 ComfyUI input/ 的原图文件名。
    - 返回 (workflow_json, meta)，meta 含 out_w/out_h（扩展后像素尺寸，供前端按比例布局）。
    """
    data, _ = get_image_bytes(image_name, img_type="input")
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(data)).convert("RGB")
    W, H = img.size
    px = max(16, int(pixels))
    d = (direction or "right").lower()

    if d in ("left", "right"):
        nW, nH = W + px, H
        offX, offY = (0, 0) if d == "right" else (px, 0)
    elif d in ("up", "top"):
        nW, nH = W, H + px
        offX, offY = 0, px
    elif d in ("down", "bottom"):
        nW, nH = W, H + px
        offX, offY = 0, 0
    else:  # all：四向等扩
        nW, nH = W + 2 * px, H + 2 * px
        offX, offY = px, px

    canvas = Image.new("RGB", (nW, nH), (0, 0, 0))
    canvas.paste(img, (offX, offY))

    mask = Image.new("L", (nW, nH), 255)  # 默认全白（待重绘）
    mask.paste(Image.new("L", (W, H), 0), (offX, offY))  # 原图区置黑（保留）

    buf_c, buf_m = BytesIO(), BytesIO()
    canvas.save(buf_c, "PNG")
    mask.save(buf_m, "PNG")
    base_name = upload_image(buf_c.getvalue(), f"outpaint_base_{uuid.uuid4().hex[:6]}.png")
    mask_name = upload_image(buf_m.getvalue(), f"outpaint_mask_{uuid.uuid4().hex[:6]}.png")

    wf = build_inpaint(
        checkpoint=checkpoint, image_name=base_name, mask_name=mask_name,
        prompt=prompt, negative=negative,
        denoise=denoise, steps=steps, cfg=cfg, seed=seed, grow_mask_by=grow_mask_by,
    )
    meta = {
        "out_w": nW, "out_h": nH, "direction": d, "pixels": px,
        "base_image": base_name, "mask_image": mask_name,
    }
    return wf, meta


# ── 视频生成（Phase 9，§6.4.1 / §6.4.2）：ComfyUI 原生 Wan2.2 文生/图生视频 ──
# 采用 ComfyUI 原生核心节点（与 ComfyUI Desktop 0.11 自带 Wan2.2 蓝图一致，已端到端验证）：
#   UNETLoader(高噪) → ModelSamplingSD3(shift=5)
#   UNETLoader(低噪) → ModelSamplingSD3(shift=5)
#   CLIPLoader(type=wan, umt5) → CLIPTextEncode(±) → WanImageToVideo
#   KSamplerAdvanced 高噪[0→2] + 低噪[2→4]（cfg=1, euler/simple）
#   VAEDecode → VHS_VideoCombine(format=video/h264-mp4) 落盘，history 返回 gifs。
# 不依赖 WanVideoWrapper 自定义节点，最大化兼容与可验证性。
VIDEO_CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"   # CLIPLoader type=wan
VIDEO_VAE = "wan_2.1_vae.safetensors"

# 文生视频模型对（Wan2.2 Bernini T2V，Apache 2.0）
VIDEO_T2V_HIGH = "wan2.2_bernini_r_high_noise_mxfp8.safetensors"
VIDEO_T2V_LOW = "wan2.2_bernini_r_low_noise_mxfp8.safetensors"
# 图生视频模型对（Wan2.2 I2V 14B）
VIDEO_I2V_HIGH = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
VIDEO_I2V_LOW = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"


def _build_wan_video(
    *,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    length: int,
    fps: int,
    seed: int,
    high_model: str,
    low_model: str,
    start_image: str | None = None,   # I2V：已上传到 input/ 的文件名；None=T2V
    prefix: str = "ic_video",
) -> dict[str, Any]:
    """构造 Wan2.2 视频工作流（文生/图生统一）。

    - T2V：start_image=None，WanImageToVideo 退化为文生视频潜空间。
    - I2V：start_image=上传文件名，走 start_image 条件。
    - 双 KSamplerAdvanced 蒸馏：高噪 0→2 + 低噪 2→4（start/end_at_step 切分），
      cfg=1, euler/simple，与官方 Wan2.2 蓝图完全一致。
    - 输出经 VHS_VideoCombine（format=video/h264-mp4）落盘，history 返回 gifs。
    """
    wf: dict[str, Any] = {}
    wf["clip"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": VIDEO_CLIP, "type": "wan"}}
    wf["vae"] = {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}}
    # 高噪模型链
    wf["unet_hi"] = {"class_type": "UNETLoader", "inputs": {"unet_name": high_model, "weight_dtype": "fp8_e4m3fn"}}
    wf["ms_hi"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": ["unet_hi", 0], "shift": 5.0}}
    # 低噪模型链
    wf["unet_lo"] = {"class_type": "UNETLoader", "inputs": {"unet_name": low_model, "weight_dtype": "fp8_e4m3fn"}}
    wf["ms_lo"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": ["unet_lo", 0], "shift": 5.0}}
    # 文本条件（WanImageToVideo 的 ± 输入即 CONDITIONING）
    wf["pos"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["clip", 0]}}
    wf["neg"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["clip", 0]}}
    # 空/起始潜空间（T2V 不传 start_image；I2V 传 start_image）
    wan_in: dict[str, Any] = {
        "positive": ["pos", 0],
        "negative": ["neg", 0],
        "vae": ["vae", 0],
        "width": int(width),
        "height": int(height),
        "length": int(length),
        "batch_size": 1,
    }
    if start_image:
        wan_in["start_image"] = ["img_src", 0]
        wf["img_src"] = {"class_type": "LoadImage", "inputs": {"image": start_image}}
    wf["wan"] = {"class_type": "WanImageToVideo", "inputs": wan_in}
    # 高噪采样（0→2）
    wf["ks_hi"] = {
        "class_type": "KSamplerAdvanced",
        "inputs": {
            "model": ["ms_hi", 0],
            "add_noise": "enable",
            "noise_seed": int(seed),
            "steps": 4,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "positive": ["wan", 0],
            "negative": ["wan", 1],
            "latent_image": ["wan", 2],
            "start_at_step": 0,
            "end_at_step": 2,
            "return_with_leftover_noise": "disable",
        },
    }
    # 低噪采样（2→4）
    wf["ks_lo"] = {
        "class_type": "KSamplerAdvanced",
        "inputs": {
            "model": ["ms_lo", 0],
            "add_noise": "disable",
            "noise_seed": int(seed),
            "steps": 4,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "positive": ["wan", 0],
            "negative": ["wan", 1],
            "latent_image": ["ks_hi", 0],
            "start_at_step": 2,
            "end_at_step": 4,
            "return_with_leftover_noise": "disable",
        },
    }
    # 解码 + 视频合成
    wf["vae_dec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["ks_lo", 0], "vae": ["vae", 0]}}
    wf["video"] = {
        "class_type": "VHS_VideoCombine",
        "inputs": {
            "images": ["vae_dec", 0],
            "frame_rate": float(fps),
            "loop_count": 0,
            "filename_prefix": prefix,
            "format": "video/h264-mp4",
            "pingpong": False,
            "save_output": True,
        },
    }
    return wf


def build_txt2vid(
    prompt: str = "a cat walking on a sunny beach",
    negative: str = "",
    width: int = 832,
    height: int = 480,
    length: int = 33,
    fps: int = 16,
    seed: int = 0,
    prefix: str = "ic_txt2vid",
) -> dict[str, Any]:
    """文生视频（Phase 9，§6.4.1）：Wan2.2 Bernini T2V 双噪采样。"""
    return _build_wan_video(
        prompt=prompt, negative=negative, width=width, height=height,
        length=length, fps=fps, seed=seed,
        high_model=VIDEO_T2V_HIGH, low_model=VIDEO_T2V_LOW,
        start_image=None, prefix=prefix,
    )


def build_img2vid(
    image_name: str,
    prompt: str = "the scene comes alive, cinematic motion",
    negative: str = "",
    width: int = 832,
    height: int = 480,
    length: int = 33,
    fps: int = 16,
    seed: int = 0,
    prefix: str = "ic_img2vid",
) -> dict[str, Any]:
    """图生视频（Phase 9，§6.4.2）：Wan2.2 I2V，start_image 为已上传文件。"""
    return _build_wan_video(
        prompt=prompt, negative=negative, width=width, height=height,
        length=length, fps=fps, seed=seed,
        high_model=VIDEO_I2V_HIGH, low_model=VIDEO_I2V_LOW,
        start_image=image_name, prefix=prefix,
    )
