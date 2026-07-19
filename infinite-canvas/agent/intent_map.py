"""无限画布 · 意图→模板映射与参数填充（§6.0 / §6.0.2 / §6.0.4）。

将 `/api/intent` 解析出的意图（§8.1.4 schema）映射为 §6.7 的具体模板，并从
**共享模型库真实文件**填充参数，最终产出可提交 ComfyUI 的 workflow JSON。

MVP 支持（RTX 5080 16GB 实测可行）：
- txt2img（文生图）：
    · qwen2  → Qwen-Image 2.0（UNET+CLIP+VAE，Apache 2.0 优先，§6.0.4）
    · sdxl / anime / 默认 → NoobAI-XL checkpoint（CheckpointLoaderSimple，已实测出图）

设计纪律：
- 模型文件取自共享库真实文件名（探测 /object_info 枚举确认合法，§6.7.1）。
- 非商用模型（FLUX.2 [dev] 等）仅当用户显式要求且仅自用时填入（§6.0.4）；MVP 默认优先 Apache 2.0。
- 未实现的 action（视频/3D 等，规划 Phase 9+）暂 coercion 为 txt2img 并记录，保证「自然语言→真实出图」闭环不破。
"""
from __future__ import annotations

import comfy_client as cc
from typing import Any

# ── 共享库真实文件（经 /object_info 枚举校验合法）──────────────────────
QWEN_UNET = "qwen_image_2512_fp8_e4m3fn.safetensors"
QWEN_CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
QWEN_VAE = "qwen_image_vae.safetensors"
NOOBAI_CKPT = "NoobAI-XL-Vpred-v1.0.safetensors"

# 模板注册表（§6.7）
TEMPLATES = [
    {"id": "txt2img_qwen", "name": "文生图 · Qwen-Image 2.0",
     "category": "txt2img", "model": "qwen2", "license": "Apache 2.0",
     "params": {"steps": 25, "cfg": 7.0, "sampler": "euler", "scheduler": "normal"}},
    {"id": "txt2img_sdxl", "name": "文生图 · NoobAI-XL (SDXL)",
     "category": "txt2img", "model": "sdxl", "license": "OpenRAIL++-M",
     "params": {"steps": 20, "cfg": 7.0, "sampler": "euler", "scheduler": "normal"}},
    {"id": "img2img_sdxl", "name": "图生图 · NoobAI-XL (SDXL)",
     "category": "img2img", "model": "sdxl", "license": "OpenRAIL++-M",
     "params": {"steps": 20, "cfg": 7.0, "denoise": 0.6, "sampler": "euler", "scheduler": "normal"}},
    {"id": "inpaint_sdxl", "name": "局部重绘 · NoobAI-XL (SDXL)",
     "category": "inpaint", "model": "sdxl", "license": "OpenRAIL++-M",
     "params": {"steps": 20, "cfg": 7.0, "denoise": 1.0, "grow_mask_by": 6, "sampler": "euler", "scheduler": "normal"}},
    {"id": "outpaint_sdxl", "name": "扩图 · NoobAI-XL (SDXL)",
     "category": "outpaint", "model": "sdxl", "license": "OpenRAIL++-M",
     "params": {"steps": 20, "cfg": 7.0, "denoise": 1.0, "grow_mask_by": 8, "sampler": "euler", "scheduler": "normal"}},
    {"id": "face_consistency_sdxl", "name": "角色一致性 · NoobAI-XL + IPAdapterFaceID (v4.33)",
     "category": "face_consistency", "model": "sdxl", "license": "OpenRAIL++-M / Apache 2.0",
     "params": {"steps": 20, "cfg": 7.0, "face_weight": 0.8, "sampler": "euler", "scheduler": "normal"}},
    {"id": "image_blend", "name": "多图融合 · ImageBlend (v4.34)",
     "category": "image_blend", "model": "none", "license": "MIT",
     "params": {"blend_mode": "normal", "blend_factor": 0.5}},
    {"id": "style_consistency_sdxl", "name": "风格一致性 · NoobAI-XL + IPAdapterStyle (v4.35)",
     "category": "style_consistency", "model": "sdxl", "license": "OpenRAIL++-M / Apache 2.0",
     "params": {"steps": 20, "cfg": 7.0, "style_weight": 0.8, "composition_weight": 0.3, "sampler": "euler", "scheduler": "normal"}},
    {"id": "scene_consistency_sdxl", "name": "场景一致性 · NoobAI-XL + IPAdapter (v4.36)",
     "category": "scene_consistency", "model": "sdxl", "license": "OpenRAIL++-M / Apache 2.0",
     "params": {"steps": 20, "cfg": 7.0, "scene_weight": 0.7, "sampler": "euler", "scheduler": "normal"}},
    {"id": "prop_consistency_sdxl", "name": "道具一致性 · NoobAI-XL + IPAdapter (v4.37)",
     "category": "prop_consistency", "model": "sdxl", "license": "OpenRAIL++-M / Apache 2.0",
     "params": {"steps": 20, "cfg": 7.0, "prop_weight": 0.7, "sampler": "euler", "scheduler": "normal"}},
]

# MVP 已支持的 action（Phase 9 起含视频，v4.33 角色一致性，v4.34 多图融合）
SUPPORTED_ACTIONS = {"txt2img", "img2img", "inpaint", "outpaint", "txt2vid", "img2vid", "face_consistency", "image_blend", "style_consistency", "scene_consistency", "prop_consistency"}


def list_templates() -> list[dict]:
    return TEMPLATES


def _model_token(params: dict) -> str:
    m = (params.get("model") or "").lower()
    return m


def _coerce_action(action: str, input_image: str | None, mask_image: str | None) -> tuple[str, bool]:
    """未知/未实现 action 暂 coercion（MVP），返回 (action, coerced)。

    - inpaint 需同时有 input_image + mask_image，否则降级（有底图→img2img，无→txt2img）。
    - img2img 仅在提供了 input_image 时才成立，否则降级 txt2img。
    - 视频（Phase 9）：txt2vid / img2vid 不再 coercion，直接放行。
    """
    if action in ("txt2vid", "img2vid"):
        return action, False
    if action == "inpaint":
        if input_image and mask_image:
            return "inpaint", False
        if input_image:
            return "img2img", True  # 缺蒙版，退化为整图重绘
        return "txt2img", True
    if action == "outpaint":
        if input_image:
            return "outpaint", False
        return "txt2img", True
    if action == "img2img" and input_image:
        return "img2img", False
    if action in SUPPORTED_ACTIONS and action not in ("img2img", "inpaint"):
        return action, False
    if action == "img2img" and not input_image:
        return "txt2img", True  # 无输入图，降级
    return "txt2img", True


def _fallback(action: str, msg: str, prompt: str, vw: int, vh: int):
    """特殊 action 缺前置条件的**安全降级**：回退文生图并在 meta 标注原因。

    例如 img2vid 未选中母图时调用，避免直接 500；前端已做选择拦截，此为防御兜底。
    """
    wf = cc.build_txt2img(
        checkpoint=NOOBAI_CKPT, prompt=prompt, negative="",
        width=int(vw or 1024), height=int(vh or 1024),
        steps=20, cfg=7.0, seed=0, batch_size=1,
    )
    meta: dict[str, Any] = {
        "action": action, "coerced_from": action, "model_token": "default",
        "prompt": prompt, "batch_size": 1, "seed": 0,
        "issues": [msg],
    }
    meta["workflow_graph"] = cc.workflow_to_graph(wf)
    return "txt2img_sdxl", wf, meta


def build_workflow(
    intent: dict[str, Any],
    input_image: str | None = None,
    batch_size: int = 1,
    seed: int | None = None,
    mask_image: str | None = None,
    outpaint_direction: str = "right",
    outpaint_pixels: int = 256,
    loras: list[dict[str, Any]] | None = None,
    controlnets: list[dict[str, Any]] | None = None,
    frames: int | None = None,
    fps: int | None = None,
    face_image: str | None = None,
    face_weight: float = 0.8,
    blend_image_b: str | None = None,
    blend_mode: str = "normal",
    blend_factor: float = 0.5,
    style_image: str | None = None,
    style_weight: float = 0.8,
    composition_weight: float = 0.3,
    scene_image: str | None = None,
    scene_weight: float = 0.7,
    prop_image: str | None = None,
    prop_weight: float = 0.7,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """意图 → 模板 → 参数填充 → workflow JSON。

    - input_image：已上传到 ComfyUI input/ 的文件名；提供且 action=img2img/inpaint 时走图路径。
    - mask_image：蒙版文件名（已上传 input/）；提供且 action=inpaint 时走局部重绘。
    - batch_size：一次生成张数（>1 时前端会散布为多个画布节点）。
    - seed：显式随机种子（None 则用意图/默认 0）。
    返回 (template_id, wf_json, meta)。wf_json 已含 SaveImage.filename_prefix（§6.7.1）。
    """
    action, coerced = _coerce_action(intent.get("action", "txt2img"), input_image, mask_image)
    params = intent.get("params", {}) or {}
    prompt = (params.get("prompt") or intent.get("subject") or "").strip()
    negative = (params.get("negative_prompt") or "").strip()
    width = int(params.get("width") or 1024)
    height = int(params.get("height") or 1024)
    batch_size = max(1, min(8, int(batch_size or 1)))
    seed = int(seed) if seed is not None else int(params.get("seed") or 0)
    tok = _model_token(params)

    meta: dict[str, Any] = {
        "action": action, "coerced_from": intent.get("action") if coerced else None,
        "model_token": tok or "default", "prompt": prompt,
        "batch_size": batch_size, "seed": seed,
    }

    # ── Phase 9：视频生成（文生 / 图生）──
    if action in ("txt2vid", "img2vid"):
        template_id = "video_" + action
        # 视频固定默认 832×480（与 Wan2.2 推荐分辨率一致），
        # 不走全局 width/height（默认为 1024，会撑大视频潜空间导致报错）。
        vw = int(params.get("width") or 832)
        vh = int(params.get("height") or 480)
        vlen = int(params.get("frames") or frames or 33)
        vfps = int(params.get("fps") or fps or 16)
        if action == "img2vid":
            if not input_image:
                return _fallback(action, "img2vid 需要 input_image（先选中一张图片）", prompt, vw, vh)
            wf = cc.build_img2vid(
                image_name=input_image, prompt=prompt, negative=negative,
                width=vw, height=vh, length=vlen, fps=vfps, seed=seed,
            )
        else:
            wf = cc.build_txt2vid(
                prompt=prompt, negative=negative,
                width=vw, height=vh, length=vlen, fps=vfps, seed=seed,
            )
        meta["video"] = True
        meta["frames"] = vlen
        meta["fps"] = vfps
        meta["width"] = vw
        meta["height"] = vh
        meta["workflow_graph"] = cc.workflow_to_graph(wf)
        return template_id, wf, meta

    # ── 局部重绘（§6.1.4）：需 input_image + mask_image ──
    if action == "inpaint":
        template_id = "inpaint_sdxl"
        steps = int(params.get("steps") or 20)
        cfg = float(params.get("cfg") or 7.0)
        denoise = float(params.get("denoise") or 1.0)
        grow = int(params.get("grow_mask_by") or 6)
        wf = cc.build_inpaint(
            checkpoint=NOOBAI_CKPT, image_name=input_image or "", mask_name=mask_image or "",
            prompt=prompt, negative=negative,
            denoise=denoise, steps=steps, cfg=cfg, seed=seed, grow_mask_by=grow,
        )
        meta["model_files"] = {"checkpoint": NOOBAI_CKPT}
        meta["denoise"] = denoise
        meta["grow_mask_by"] = grow
        meta["input_image"] = input_image
        meta["mask_image"] = mask_image
        meta["workflow_graph"] = cc.workflow_to_graph(wf)
        return template_id, wf, meta

    # ── 扩图（§6.1.5）：需 input_image，pad+mask → 标准 inpaint 复用 ──
    if action == "outpaint":
        template_id = "outpaint_sdxl"
        steps = int(params.get("steps") or 20)
        cfg = float(params.get("cfg") or 7.0)
        denoise = 1.0  # 扩图：扩展区全新生成
        grow = int(params.get("grow_mask_by") or 8)
        wf, op_meta = cc.build_outpaint(
            checkpoint=NOOBAI_CKPT, image_name=input_image or "",
            direction=outpaint_direction, pixels=int(outpaint_pixels or 256),
            prompt=prompt, negative=negative,
            denoise=denoise, steps=steps, cfg=cfg, seed=seed, grow_mask_by=grow,
        )
        meta["model_files"] = {"checkpoint": NOOBAI_CKPT}
        meta["action"] = "outpaint"
        meta["direction"] = outpaint_direction
        meta["pixels"] = outpaint_pixels
        meta.update(op_meta)  # out_w, out_h, base_image, mask_image
        meta["workflow_graph"] = cc.workflow_to_graph(wf)
        return template_id, wf, meta

    # ── 图生图（§6.1.2）：需 input_image，走 checkpoint + LoadImage/VAEEncode ──
    if action == "img2img":
        template_id = "img2img_sdxl"
        steps = int(params.get("steps") or 20)
        cfg = float(params.get("cfg") or 7.0)
        denoise = float(params.get("denoise") or 0.6)
        wf = cc.build_img2img(
            checkpoint=NOOBAI_CKPT, image_name=input_image or "",
            prompt=prompt, negative=negative,
            denoise=denoise, steps=steps, cfg=cfg, seed=seed,
            loras=loras,
            controlnets=controlnets,
        )
        meta["model_files"] = {"checkpoint": NOOBAI_CKPT}
        meta["denoise"] = denoise
        meta["input_image"] = input_image
        if loras:
            meta["loras"] = loras
        if controlnets:
            meta["controlnets"] = controlnets
        meta["workflow_graph"] = cc.workflow_to_graph(wf)
        return template_id, wf, meta

    # ── v4.33: 角色一致性（Phase 8）──
    if action == "face_consistency":
        template_id = "face_consistency_sdxl"
        if not face_image:
            return _fallback(action, "face_consistency 需要 face_image（先上传参考人脸图）", prompt, width, height)
        steps = int(params.get("steps") or 20)
        cfg = float(params.get("cfg") or 7.0)
        fw = float(params.get("face_weight") or face_weight)
        wf = cc.build_face_consistency(
            face_image=face_image, checkpoint=NOOBAI_CKPT,
            prompt=prompt, negative=negative,
            width=width, height=height,
            steps=steps, cfg=cfg, seed=seed,
            face_weight=fw,
        )
        meta["model_files"] = {"checkpoint": NOOBAI_CKPT}
        meta["face_image"] = face_image
        meta["face_weight"] = fw
        meta["workflow_graph"] = cc.workflow_to_graph(wf)
        return template_id, wf, meta

    # ── v4.34: 多图融合（Phase 9）──
    if action == "image_blend":
        template_id = "image_blend"
        if not input_image or not blend_image_b:
            return _fallback(action, "image_blend 需要两张图片（A 和 B）", prompt, width, height)
        bm = str(params.get("blend_mode") or blend_mode)
        bf = float(params.get("blend_factor") or blend_factor)
        wf = cc.build_image_blend(
            image_a=input_image, image_b=blend_image_b,
            blend_mode=bm, blend_factor=bf,
        )
        meta["image_a"] = input_image
        meta["image_b"] = blend_image_b
        meta["blend_mode"] = bm
        meta["blend_factor"] = bf
        meta["workflow_graph"] = cc.workflow_to_graph(wf)
        return template_id, wf, meta

    # ── v4.35: 风格一致性（Phase 8）──
    if action == "style_consistency":
        template_id = "style_consistency_sdxl"
        if not style_image:
            return _fallback(action, "style_consistency 需要 style_image（先上传风格参考图）", prompt, width, height)
        steps = int(params.get("steps") or 20)
        cfg = float(params.get("cfg") or 7.0)
        sw = float(params.get("style_weight") or style_weight)
        cw = float(params.get("composition_weight") or composition_weight)
        wf = cc.build_style_consistency(
            style_image=style_image, checkpoint=NOOBAI_CKPT,
            prompt=prompt, negative=negative,
            width=width, height=height,
            steps=steps, cfg=cfg, seed=seed,
            style_weight=sw, composition_weight=cw,
        )
        meta["model_files"] = {"checkpoint": NOOBAI_CKPT}
        meta["style_image"] = style_image
        meta["style_weight"] = sw
        meta["composition_weight"] = cw
        meta["workflow_graph"] = cc.workflow_to_graph(wf)
        return template_id, wf, meta

    # ── v4.36: 场景一致性（Phase 8）──
    if action == "scene_consistency":
        template_id = "scene_consistency_sdxl"
        if not scene_image:
            return _fallback(action, "scene_consistency 需要 scene_image（先上传场景参考图）", prompt, width, height)
        steps = int(params.get("steps") or 20)
        cfg = float(params.get("cfg") or 7.0)
        sw = float(params.get("scene_weight") or scene_weight)
        wf = cc.build_scene_consistency(
            scene_image=scene_image, checkpoint=NOOBAI_CKPT,
            prompt=prompt, negative=negative,
            width=width, height=height,
            steps=steps, cfg=cfg, seed=seed,
            scene_weight=sw,
        )
        meta["model_files"] = {"checkpoint": NOOBAI_CKPT}
        meta["scene_image"] = scene_image
        meta["scene_weight"] = sw
        meta["workflow_graph"] = cc.workflow_to_graph(wf)
        return template_id, wf, meta

    # ── v4.37: 道具一致性（Phase 8）──
    if action == "prop_consistency":
        template_id = "prop_consistency_sdxl"
        if not prop_image:
            return _fallback(action, "prop_consistency 需要 prop_image（先上传道具参考图）", prompt, width, height)
        steps = int(params.get("steps") or 20)
        cfg = float(params.get("cfg") or 7.0)
        pw = float(params.get("prop_weight") or prop_weight)
        wf = cc.build_prop_consistency(
            prop_image=prop_image, checkpoint=NOOBAI_CKPT,
            prompt=prompt, negative=negative,
            width=width, height=height,
            steps=steps, cfg=cfg, seed=seed,
            prop_weight=pw,
        )
        meta["model_files"] = {"checkpoint": NOOBAI_CKPT}
        meta["prop_image"] = prop_image
        meta["prop_weight"] = pw
        meta["workflow_graph"] = cc.workflow_to_graph(wf)
        return template_id, wf, meta

    # 选择构建器（txt2img）
    if tok in ("qwen2", "qwen", "qwen_image"):
        template_id = "txt2img_qwen"
        steps = int(params.get("steps") or 25)
        cfg = float(params.get("cfg") or 7.0)
        wf = cc.build_txt2img_qwen(
            unet=QWEN_UNET, clip=QWEN_CLIP, vae=QWEN_VAE,
            prompt=prompt, negative=negative,
            width=width, height=height, steps=steps, cfg=cfg,
            seed=seed, batch_size=batch_size,
        )
        meta["model_files"] = {"unet": QWEN_UNET, "clip": QWEN_CLIP, "vae": QWEN_VAE}
    else:
        # sdxl / anime / flux_klein(无 4B fp8，降级) / 默认 → NoobAI checkpoint
        template_id = "txt2img_sdxl"
        steps = int(params.get("steps") or 20)
        cfg = float(params.get("cfg") or 7.0)
        wf = cc.build_txt2img(
            checkpoint=NOOBAI_CKPT, prompt=prompt, negative=negative,
            width=width, height=height, steps=steps, cfg=cfg,
            seed=seed, batch_size=batch_size,
        )
        meta["model_files"] = {"checkpoint": NOOBAI_CKPT}
        if tok == "flux_klein":
            meta["note"] = "flux_klein 4B fp8 不在共享库，已降级到 Apache 优先的 NoobAI-XL"

    meta["workflow_graph"] = cc.workflow_to_graph(wf)
    return template_id, wf, meta
