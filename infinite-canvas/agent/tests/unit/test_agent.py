"""无限画布 · 后端单元测试（pytest）。

覆盖纯函数（无需网络 / ComfyUI / API Key）：
  - deepseek._postprocess 退化兜底与白名单
  - intent_map.build_workflow 模板映射 / img2img / 批量 / 种子
  - comfy_client 防路径穿越 + 工作流结构

运行：  .venv\\Scripts\\python.exe -m pytest -q
"""
from __future__ import annotations

import pytest

import comfy_client as cc
import deepseek as ds
import intent_map as im


# ── deepseek._postprocess ──────────────────────────────────────────
def test_postprocess_keeps_good_english_prompt():
    intent = {"action": "txt2img", "subject": "fox",
              "params": {"prompt": "a red fox running under a starry sky, cyberpunk neon"}}
    out = ds._postprocess(dict(intent), "画一只狐狸")
    assert out["params"]["prompt"].startswith("a red fox running")


def test_postprocess_falls_back_on_placeholder():
    intent = {"action": "txt2img", "subject": "unknown",
              "params": {"prompt": "An image with question marks"}}
    out = ds._postprocess(dict(intent), "画一座雪山湖泊")
    # 占位符被识别为退化 → 回退用户中文原输入
    assert out["params"]["prompt"] == "画一座雪山湖泊"
    assert out["subject"] != "unknown"


def test_postprocess_falls_back_on_generic():
    intent = {"action": "txt2img", "subject": "scene",
              "params": {"prompt": "A beautiful landscape, high quality, photorealistic"}}
    out = ds._postprocess(dict(intent), "赛博朋克城市夜景")
    assert out["params"]["prompt"] == "赛博朋克城市夜景"


def test_postprocess_short_prompt_fallback():
    intent = {"action": "txt2img", "params": {"prompt": "cat"}}  # <20 字符
    out = ds._postprocess(dict(intent), "一只猫")
    assert out["params"]["prompt"] == "一只猫"


def test_postprocess_unknown_action_coerced():
    intent = {"action": "make_video", "params": {"prompt": "a detailed cinematic scene of city"}}
    out = ds._postprocess(dict(intent), "城市")
    assert out["action"] == "txt2img"


def test_postprocess_img2img_action_preserved():
    intent = {"action": "img2img", "params": {"prompt": "a detailed portrait, oil painting style"}}
    out = ds._postprocess(dict(intent), "油画肖像")
    assert out["action"] == "img2img"


# ── intent_map.build_workflow ──────────────────────────────────────
def test_build_workflow_txt2img_default_sdxl():
    tid, wf, meta = im.build_workflow({"action": "txt2img", "params": {"prompt": "a serene lake"}})
    assert tid == "txt2img_sdxl"
    save = _find(wf, "SaveImage")
    assert save["inputs"]["filename_prefix"] == "infinite_canvas"


def test_build_workflow_qwen():
    tid, wf, meta = im.build_workflow(
        {"action": "txt2img", "params": {"model": "qwen2", "prompt": "a red fox"}})
    assert tid == "txt2img_qwen"
    assert meta["model_token"] in ("qwen2", "qwen", "qwen_image")


def test_build_workflow_img2img_with_input():
    tid, wf, meta = im.build_workflow(
        {"action": "img2img", "params": {"prompt": "repaint as watercolor"}},
        input_image="src_00001.png")
    assert tid == "img2img_sdxl"
    assert _find(wf, "LoadImage")["inputs"]["image"] == "src_00001.png"
    assert _find(wf, "VAEEncode") is not None
    assert meta["input_image"] == "src_00001.png"


def test_build_workflow_img2img_without_input_coerced():
    tid, wf, meta = im.build_workflow(
        {"action": "img2img", "params": {"prompt": "x"}}, input_image=None)
    assert tid.startswith("txt2img")
    assert meta["coerced_from"] == "img2img"


def test_build_workflow_batch_size():
    tid, wf, meta = im.build_workflow(
        {"action": "txt2img", "params": {"prompt": "a lake"}}, batch_size=3)
    latent = _find(wf, "EmptyLatentImage")
    assert latent["inputs"]["batch_size"] == 3
    assert meta["batch_size"] == 3


def test_build_workflow_seed_passthrough():
    tid, wf, meta = im.build_workflow(
        {"action": "txt2img", "params": {"prompt": "a lake"}}, seed=12345)
    assert _find(wf, "KSampler")["inputs"]["seed"] == 12345
    assert meta["seed"] == 12345


def test_build_workflow_batch_clamped():
    _, wf, meta = im.build_workflow(
        {"action": "txt2img", "params": {"prompt": "a lake"}}, batch_size=99)
    assert meta["batch_size"] == 8  # 上限 8


# ── comfy_client 防路径穿越 + 工作流结构 ────────────────────────────
@pytest.mark.parametrize("bad", ["../etc/passwd", "a/b.png", "..\\x.png", "sub/dir/x.png"])
def test_get_image_bytes_rejects_traversal(bad):
    with pytest.raises(ValueError):
        cc.get_image_bytes(bad)


def test_build_img2img_structure():
    wf = cc.build_img2img("ckpt.safetensors", "in.png", prompt="p", denoise=0.6)
    assert _find(wf, "LoadImage")["inputs"]["image"] == "in.png"
    ks = _find(wf, "KSampler")
    assert 0.0 < ks["inputs"]["denoise"] <= 1.0
    assert _find(wf, "SaveImage")["inputs"]["filename_prefix"] == "infinite_canvas"


def test_build_img2img_denoise_clamped():
    wf = cc.build_img2img("ckpt.safetensors", "in.png", denoise=5.0)
    assert cc.build_img2img("c", "i", denoise=5.0)  # 不抛异常
    assert _find(wf, "KSampler")["inputs"]["denoise"] <= 1.0


def test_build_txt2img_batch():
    wf = cc.build_txt2img("ckpt.safetensors", batch_size=4)
    assert _find(wf, "EmptyLatentImage")["inputs"]["batch_size"] == 4


# ── 局部重绘 inpaint（§6.1.4）────────────────────────────────────────
def test_build_inpaint_structure():
    wf = cc.build_inpaint("ckpt.safetensors", "in.png", "mask.png",
                          prompt="p", denoise=1.0, grow_mask_by=6)
    assert _find(wf, "LoadImage")["inputs"]["image"] == "in.png"
    lm = _find(wf, "LoadImageMask")
    assert lm["inputs"]["image"] == "mask.png"
    assert lm["inputs"]["channel"] == "red"
    enc = _find(wf, "VAEEncodeForInpaint")
    assert enc is not None
    assert enc["inputs"]["grow_mask_by"] == 6
    assert _find(wf, "SaveImage")["inputs"]["filename_prefix"] == "infinite_canvas"


def test_build_inpaint_denoise_clamped():
    wf = cc.build_inpaint("c", "i.png", "m.png", denoise=9.0)
    assert _find(wf, "KSampler")["inputs"]["denoise"] <= 1.0


def test_build_workflow_inpaint_with_mask():
    tid, wf, meta = im.build_workflow(
        {"action": "inpaint", "params": {"prompt": "replace sky", "denoise": 1.0}},
        input_image="base_00001.png", mask_image="mask_00001.png")
    assert tid == "inpaint_sdxl"
    assert meta["action"] == "inpaint"
    assert meta["mask_image"] == "mask_00001.png"
    assert _find(wf, "VAEEncodeForInpaint") is not None


def test_build_workflow_inpaint_without_mask_degrades_to_img2img():
    tid, wf, meta = im.build_workflow(
        {"action": "inpaint", "params": {"prompt": "x"}},
        input_image="base.png", mask_image=None)
    assert tid == "img2img_sdxl"
    assert meta["coerced_from"] == "inpaint"


def test_build_workflow_inpaint_without_input_degrades_to_txt2img():
    tid, wf, meta = im.build_workflow(
        {"action": "inpaint", "params": {"prompt": "x"}},
        input_image=None, mask_image=None)
    assert tid.startswith("txt2img")
    assert meta["coerced_from"] == "inpaint"


def test_inpaint_template_registered():
    ids = {t["id"] for t in im.TEMPLATES}
    assert "inpaint_sdxl" in ids
    assert "inpaint" in im.SUPPORTED_ACTIONS


# ── 工具 ───────────────────────────────────────────────────────────
# ── 扩图 outpaint（§6.1.5）──────────────────────────────────────
from unittest.mock import patch as _patch


def _make_src_png(w, h, color=(255, 0, 0)):
    from io import BytesIO
    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def _run_outpaint(direction="right", pixels=32, w=64, h=48):
    src = _make_src_png(w, h)
    with _patch.object(cc, "get_image_bytes", return_value=(src, "image/png")), \
         _patch.object(cc, "upload_image") as mup:
        wf, meta = cc.build_outpaint(
            "ckpt.safetensors", "src.png", direction=direction, pixels=pixels)
    return wf, meta, mup.call_args_list


def test_build_outpaint_right_pads_width_and_mask():
    wf, meta, calls = _run_outpaint("right", 32)
    assert meta["out_w"] == 64 + 32
    assert meta["out_h"] == 48
    assert meta["direction"] == "right"
    assert _find(wf, "VAEEncodeForInpaint") is not None
    assert _find(wf, "KSampler")["inputs"]["denoise"] == 1.0
    from PIL import Image as _I
    from io import BytesIO as _B
    mimg = _I.open(_B(calls[1].args[0]))  # 第二次上传 = mask
    assert mimg.size == (96, 48)
    mp = mimg.load()
    for x in range(64, 96):
        assert mp[x, 24] == 255   # 右扩区白
    for x in range(0, 64):
        assert mp[x, 24] == 0      # 原图区黑


def test_build_outpaint_down_pads_height():
    wf, meta, _ = _run_outpaint("down", 24)
    assert meta["out_w"] == 64
    assert meta["out_h"] == 48 + 24


def test_build_outpaint_all_four_sides():
    wf, meta, calls = _run_outpaint("all", 32)
    assert meta["out_w"] == 64 + 64
    assert meta["out_h"] == 48 + 64
    from PIL import Image as _I
    from io import BytesIO as _B
    mimg = _I.open(_B(calls[1].args[0]))
    assert mimg.size == (128, 112)
    mp = mimg.load()
    assert mp[10, 56] == 255    # 左缘白
    assert mp[110, 56] == 255   # 右缘白
    assert mp[64, 56] == 0       # 原图中心黑


def test_build_outpaint_clamps_min_pixels():
    _, meta, _ = _run_outpaint("right", 8)
    assert meta["pixels"] == 16


def test_build_workflow_outpaint_branch():
    src = _make_src_png(64, 48)
    with _patch.object(cc, "get_image_bytes", return_value=(src, "image/png")), \
         _patch.object(cc, "upload_image"):
        tid, wf, meta = im.build_workflow(
            {"action": "outpaint", "params": {"prompt": "extend"}},
            input_image="src.png", outpaint_direction="right", outpaint_pixels=32)
    assert tid == "outpaint_sdxl"
    assert meta["action"] == "outpaint"
    assert meta["out_w"] == 64 + 32
    assert _find(wf, "VAEEncodeForInpaint") is not None


def test_build_workflow_outpaint_without_input_degrades():
    tid, wf, meta = im.build_workflow(
        {"action": "outpaint", "params": {"prompt": "x"}}, input_image=None)
    assert tid.startswith("txt2img")
    assert meta["coerced_from"] == "outpaint"


def test_outpaint_template_registered():
    ids = {t["id"] for t in im.TEMPLATES}
    assert "outpaint_sdxl" in ids
    assert "outpaint" in im.SUPPORTED_ACTIONS


def _find(wf: dict, class_type: str):
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            return node
    return None


# ── LoRA 注入（§6.22 控制节点化）──────────────────────────────
def test_build_img2img_with_lora_inserts_loader():
    wf = cc.build_img2img("ckpt.safetensors", "in.png", prompt="x",
                            loras=[{"name": "a.safetensors", "strength": 0.8}])
    assert "lora0" in wf
    assert wf["lora0"]["class_type"] == "LoraLoader"
    assert wf["lora0"]["inputs"]["lora_name"] == "a.safetensors"
    assert wf["lora0"]["inputs"]["strength_model"] == 0.8
    # KSampler.model 与正负向 CLIP 都指向最后的 LoraLoader
    assert wf["3"]["inputs"]["model"] == ["lora0", 0]
    assert wf["6"]["inputs"]["clip"] == ["lora0", 1]
    assert wf["7"]["inputs"]["clip"] == ["lora0", 1]
    # checkpoint 仍提供 vae
    assert wf["11"]["inputs"]["vae"] == ["4", 2]


def test_build_img2img_multi_lora_chain():
    wf = cc.build_img2img("ck.safetensors", "in.png", prompt="x",
                            loras=[{"name": "a.safetensors", "strength": 0.5},
                                   {"name": "b.safetensors", "strength": 1.0}])
    assert "lora0" in wf and "lora1" in wf
    # 链式：lora0 接 checkpoint，lora1 接 lora0
    assert wf["lora0"]["inputs"]["model"] == ["4", 0]
    assert wf["lora1"]["inputs"]["model"] == ["lora0", 0]
    # 末端指向 lora1
    assert wf["3"]["inputs"]["model"] == ["lora1", 0]
    assert wf["6"]["inputs"]["clip"] == ["lora1", 1]


def test_build_img2img_no_lora_keeps_checkpoint():
    wf = cc.build_img2img("ck.safetensors", "in.png", prompt="x")
    assert "lora0" not in wf
    assert wf["3"]["inputs"]["model"] == ["4", 0]
    assert wf["6"]["inputs"]["clip"] == ["4", 1]


def test_build_workflow_img2img_with_loras():
    tid, wf, meta = im.build_workflow(
        {"action": "img2img", "params": {"prompt": "x"}},
        input_image="in.png",
        loras=[{"name": "a.safetensors", "strength": 0.8}])
    assert tid.startswith("img2img")
    assert "lora0" in wf
    assert meta.get("loras") == [{"name": "a.safetensors", "strength": 0.8}]


def test_list_loras_returns_shared_lib():
    loras = cc.list_loras()
    assert isinstance(loras, list)
    # 共享库 loras/ 下含真实 LoRA（如 anima_aixxx 系列）
    assert any("anima" in n.lower() for n in loras)


# ── ControlNet 注入（§6.23 控制节点化）──────────────────────
def test_build_img2img_with_controlnet_union():
    wf = cc.build_img2img(
        "ck.safetensors", "in.png", prompt="x",
        controlnets=[{"model": "controlnet++_union_sdxl_promax.safetensors",
                      "type": "canny/lineart/anime_lineart/mlsd",
                      "strength": 0.75, "image": "ctrl.png"}])
    # 控制图加载节点
    assert "cnimg0" in wf and wf["cnimg0"]["class_type"] == "LoadImage"
    # 预处理器（按 union type 从注册表推导为 CannyEdgePreprocessor）
    assert wf["cnpre0"]["class_type"] == "CannyEdgePreprocessor"
    # ControlNetLoader + SetUnionControlNetType（union 模型必带 type）
    assert wf["cnld0"]["class_type"] == "ControlNetLoader"
    assert wf["cntyp0"]["class_type"] == "SetUnionControlNetType"
    assert wf["cntyp0"]["inputs"]["type"] == "canny/lineart/anime_lineart/mlsd"
    # ControlNetApply 串接正条件，KSampler.positive 指向末级
    assert wf["cnapply0"]["class_type"] == "ControlNetApply"
    assert wf["cnapply0"]["inputs"]["conditioning"] == ["6", 0]
    # 强度须透传（非默认 1.0，证明 stength→strength 修复生效）
    assert wf["cnapply0"]["inputs"]["strength"] == 0.75
    assert wf["3"]["inputs"]["positive"] == ["cnapply0", 0]


def test_build_img2img_controlnet_non_union_no_type():
    wf = cc.build_img2img(
        "ck.safetensors", "in.png", prompt="x",
        controlnets=[{"model": "anima-lllite-any-test-like-v2.safetensors",
                      "strength": 0.7, "image": "ctrl.png"}])
    assert "cntyp0" not in wf  # 非 union 模型不注入 SetUnionControlNetType
    assert wf["cnapply0"]["class_type"] == "ControlNetApply"
    assert "cnpre0" not in wf  # 直传原图，无预处理器
    assert wf["cnapply0"]["inputs"]["strength"] == 0.7  # 非 union 强度同样透传
    assert wf["cnapply0"]["inputs"]["image"] == ["cnimg0", 0]
    assert wf["3"]["inputs"]["positive"] == ["cnapply0", 0]


def test_build_img2img_multi_controlnet_chain():
    wf = cc.build_img2img(
        "ck.safetensors", "in.png", prompt="x",
        controlnets=[
            {"model": "controlnet++_union_sdxl_promax.safetensors", "type": "depth",
             "strength": 1.0, "image": "c1.png"},
            {"model": "controlnet++_union_sdxl_promax.safetensors", "type": "openpose",
             "strength": 0.8, "image": "c2.png"},
        ])
    assert "cnapply0" in wf and "cnapply1" in wf
    # 链式：apply1 的正条件来自 apply0
    assert wf["cnapply1"]["inputs"]["conditioning"] == ["cnapply0", 0]
    assert wf["3"]["inputs"]["positive"] == ["cnapply1", 0]


def test_build_img2img_with_lora_and_controlnet():
    wf = cc.build_img2img(
        "ck.safetensors", "in.png", prompt="x",
        loras=[{"name": "a.safetensors", "strength": 0.5}],
        controlnets=[{"model": "controlnet++_union_sdxl_promax.safetensors",
                      "type": "tile", "strength": 1.0, "image": "ctrl.png"}])
    # LoRA 仍作用在 model 上
    assert wf["3"]["inputs"]["model"] == ["lora0", 0]
    # ControlNet 作用在正条件上
    assert wf["3"]["inputs"]["positive"] == ["cnapply0", 0]


def test_build_workflow_img2img_with_controlnets():
    tid, wf, meta = im.build_workflow(
        {"action": "img2img", "params": {"prompt": "x"}},
        input_image="in.png",
        controlnets=[{"model": "controlnet++_union_sdxl_promax.safetensors",
                      "type": "depth", "strength": 1.0, "image": "ctrl.png"}])
    assert tid.startswith("img2img")
    assert "cnapply0" in wf
    assert meta.get("controlnets") is not None


def test_list_controlnets_returns_shared_lib():
    cns = cc.list_controlnets()
    assert isinstance(cns, list)
    assert any("union" in n.lower() for n in cns)  # 含 union 模型


# ── Phase 9：视频生成（Wan2.2 文生/图生视频）────────────────────
def test_build_txt2vid_structure():
    """speed_mode=False 走标准 Wan2.2 双噪工作流（v5.0）。"""
    wf = cc.build_txt2vid("a cat surfing", length=17, fps=16, seed=7,
                          speed_mode=False)
    wan = _find(wf, "WanImageToVideo")
    assert wan["inputs"]["width"] == 832
    assert wan["inputs"]["height"] == 480
    assert wan["inputs"]["length"] == 17            # 帧数透传
    assert "start_image" not in wan["inputs"]        # T2V 无起始图
    vhs = _find(wf, "VHS_VideoCombine")
    assert vhs["inputs"]["format"] == "video/h264-mp4"
    assert vhs["inputs"]["frame_rate"] == 16.0
    assert vhs["inputs"]["filename_prefix"] == "ic_txt2vid"
    ks = [n for n in wf.values()
          if isinstance(n, dict) and n.get("class_type") == "KSamplerAdvanced"]
    assert len(ks) == 2
    steps = sorted((k["inputs"]["start_at_step"], k["inputs"]["end_at_step"]) for k in ks)
    assert steps == [(0, 2), (2, 4)]              # 高/低噪切分
    for k in ks:
        assert k["inputs"]["cfg"] == 1.0


def test_build_img2vid_has_start_image():
    """speed_mode=False 走标准 I2V 双噪工作流（v5.0）。"""
    wf = cc.build_img2vid("start.png", "bring it to life", length=33, fps=24,
                          seed=3, speed_mode=False)
    wan = _find(wf, "WanImageToVideo")
    assert wan["inputs"]["length"] == 33
    assert "start_image" in wan["inputs"]
    assert _find(wf, "LoadImage")["inputs"]["image"] == "start.png"
    assert _find(wf, "VHS_VideoCombine")["inputs"]["frame_rate"] == 24.0


def test_build_workflow_txt2vid_branch():
    """video_quality='quality' 走标准 Wan2.2 双噪工作流（v5.0）。"""
    tid, wf, meta = im.build_workflow(
        {"action": "txt2vid", "params": {"prompt": "a fox in snow"}},
        frames=17, fps=16, seed=11, video_quality="quality")
    assert tid == "video_txt2vid"
    assert meta["video"] is True
    vhs = _find(wf, "VHS_VideoCombine")
    assert vhs["inputs"]["format"] == "video/h264-mp4"
    wan = _find(wf, "WanImageToVideo")
    assert wan["inputs"]["length"] == 17
    assert wan["inputs"]["width"] == 832


def test_build_workflow_txt2vid_lightx2v():
    """默认 video_quality='speed' 走 LightX2V 4步蒸馏路径（v5.0）。"""
    tid, wf, meta = im.build_workflow(
        {"action": "txt2vid", "params": {"prompt": "a fox in snow"}},
        frames=33, fps=16, seed=42)
    assert tid == "video_txt2vid"
    assert meta["video"] is True
    # LightX2V 格式使用 SaveVideo 而非 VHS_VideoCombine
    has_save = any(
        "SaveVideo" in str(v.get("class_type", ""))
        for v in wf.values()
    )
    assert has_save, "speed 模式应输出 LightX2V SaveVideo 格式"


def test_build_workflow_img2vid_branch():
    tid, wf, meta = im.build_workflow(
        {"action": "img2vid", "params": {"prompt": "animate this"}},
        input_image="uploaded.png", frames=33, fps=16, seed=12)
    assert tid == "video_img2vid"
    assert meta["video"] is True
    assert _find(wf, "LoadImage")["inputs"]["image"] == "uploaded.png"


def test_video_action_not_coerced():
    # 视频 action 不应被降级为 txt2img
    assert im._coerce_action("txt2vid", None, None) == ("txt2vid", False)
    assert im._coerce_action("img2vid", "x.png", None) == ("img2vid", False)


def test_img2vid_without_parent_falls_back():
    # 图生视频未选中母图：安全降级为文生图并标注原因，绝不 500
    tid, wf, meta = im.build_workflow(
        {"action": "img2vid", "params": {"prompt": "animate this"}}, seed=12)
    assert tid == "txt2img_sdxl"
    assert meta.get("issues"), "应在 issues 中标注缺母图原因"

