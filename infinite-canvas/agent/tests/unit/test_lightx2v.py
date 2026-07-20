"""v5.0 LightX2V + SageAttention 单元测试。

覆盖：
  - LightX2V 蓝图结构完整性（T2V / I2V / GGUF / LTX）
  - SageAttention 检测与环境变量
  - 蓝图注册表查询
  - 视频构建 speed_mode 分支（双噪 vs 4步蒸馏）
  - SageAttention sampler 参数注入
"""

from __future__ import annotations

import os
import pytest

# 导入被测模块
from sage_attention import (
    detect_sage, enable_sage, disable_sage, apply_to_workflow,
    SageConfig, status_report,
)
from lightx2v_blueprints import (
    wan22_t2v_lightx2v, wan22_t2v_lightx2v_gguf,
    wan22_i2v_lightx2v, ltx_t2v_lightx2v,
    LIGHTX2V_REGISTRY, get_lightx2v_blueprint,
    list_lightx2v_blueprints, recommend_lightx2v_blueprint,
    estimated_time,
)
import comfy_client as cc


# ═══════════════════════════════════════════════════════════════════
# SageAttention 配置检测
# ═══════════════════════════════════════════════════════════════════

def test_sage_disabled_by_default():
    """默认 SageAttention 未启用（无环境变量 + 包未安装）。"""
    cfg = detect_sage()
    assert isinstance(cfg, SageConfig)
    # 在没有安装 sageattention 的环境下应关闭
    assert cfg.enabled is False


def test_sage_enable_via_env(monkeypatch):
    """通过环境变量 SAGEATTENTION=1 启用。"""
    monkeypatch.setenv("SAGEATTENTION", "1")
    monkeypatch.setenv("SAGE_FP8", "1")
    cfg = detect_sage()
    assert cfg.enabled is True
    assert cfg.dtype == "fp8"


def test_sage_explicit_disable(monkeypatch):
    """SAGEATTENTION=0 强制禁用。"""
    monkeypatch.setenv("SAGEATTENTION", "0")
    cfg = detect_sage()
    assert cfg.enabled is False


def test_enable_sage_sets_env():
    """enable_sage() 设置环境变量并返回配置。"""
    cfg = enable_sage("fp8")
    assert cfg.enabled is True
    assert cfg.dtype == "fp8"
    assert os.environ.get("SAGEATTENTION") == "1"


def test_disable_sage_clears_env(monkeypatch):
    """disable_sage() 清除所有 Sage 相关环境变量。"""
    monkeypatch.setenv("SAGEATTENTION", "1")
    monkeypatch.setenv("SAGE_FP8", "1")
    cfg = disable_sage()
    assert cfg.enabled is False
    assert os.environ.get("SAGEATTENTION") is None


def test_sage_estimated_speedup():
    """speedup 估算：fp8 ~2.5x, fp16 ~1.8x, disabled ~1.0x。"""
    cfg_fp8 = SageConfig(enabled=True, dtype="fp8")
    assert cfg_fp8.estimated_speedup == 2.5
    cfg_fp16 = SageConfig(enabled=True, dtype="fp16")
    assert cfg_fp16.estimated_speedup == 1.8
    cfg_off = SageConfig(enabled=False)
    assert cfg_off.estimated_speedup == 1.0


def test_sage_sampler_params():
    """sampler_params() 仅在启用时返回 attention 配置。"""
    cfg_on = SageConfig(enabled=True, dtype="fp8", tile_size=16)
    params = cfg_on.sampler_params()
    assert params["attention_mode"] == "sage"
    assert params["sage_dtype"] == "fp8"
    assert params["sage_blkh"] == 16
    cfg_off = SageConfig(enabled=False)
    assert cfg_off.sampler_params() == {}


def test_apply_to_workflow_injects_sampler(monkeypatch):
    """apply_to_workflow 向 sampler 节点注入 SageAttention 参数（启用时）。"""
    monkeypatch.setenv("SAGEATTENTION", "1")
    monkeypatch.setenv("SAGE_FP8", "1")
    nodes = [
        {"class_type": "KSampler", "inputs": {"steps": 4}},
        {"class_type": "VAEDecode", "inputs": {}},
        {"class_type": "WanVideoSampler", "inputs": {"steps": 4}},
    ]
    result = apply_to_workflow(nodes)
    # KSampler 和 WanVideoSampler 都被注入
    assert result[0]["inputs"]["attention_mode"] == "sage"
    assert result[2]["inputs"]["attention_mode"] == "sage"
    # VAEDecode 不受影响
    assert "attention_mode" not in result[1]["inputs"]


def test_status_report_format():
    """status_report() 返回可读状态字符串。"""
    report = status_report()
    assert isinstance(report, str)
    assert len(report) > 0
    assert "SageAttention" in report


# ═══════════════════════════════════════════════════════════════════
# LightX2V 蓝图结构
# ═══════════════════════════════════════════════════════════════════

def test_wan22_t2v_lightx2v_has_save_video():
    """LightX2V T2V 蓝图包含 SaveVideo 节点用于输出。"""
    nodes = wan22_t2v_lightx2v(
        "a cat surfing", negative="blur", width=640, height=480, frames=33, seed=42)
    assert len(nodes) >= 8
    node_types = [n["class_type"] for n in nodes]
    assert "WanVideoCLIPLoader" in node_types
    assert "WanVideoUNETLoaderV2" in node_types
    assert "SaveVideo" in node_types
    # 确认 4 步蒸馏配置
    sampler = next(n for n in nodes if "Sampler" in n["class_type"])
    assert sampler["inputs"]["steps"] == 4
    assert sampler["inputs"]["sampler_name"] == "euler_lightx2v"


def test_wan22_t2v_lightx2v_seed_deterministic():
    """给定 seed 时多次调用输出相同 workflow（确定性）。"""
    n1 = wan22_t2v_lightx2v("test", seed=123)
    n2 = wan22_t2v_lightx2v("test", seed=123)
    # 结构一致（seed=0 时随机，指定时固定）
    assert n1 == n2


def test_wan22_t2v_lightx2v_gguf_gpu_16gb():
    """GGUF 版专用 UNETLoaderGGUF，16GB VRAM 友好。"""
    nodes = wan22_t2v_lightx2v_gguf(
        "sunset beach", width=832, height=480, frames=49, seed=99)
    node_types = [n["class_type"] for n in nodes]
    assert "WanVideoUNETLoaderGGUF" in node_types
    assert "SaveVideo" in node_types


def test_ltx_t2v_lightx2v_2steps():
    """LTX LightX2V 只有 2 步（极速模式）。"""
    nodes = ltx_t2v_lightx2v(
        "a robot walking", steps=2, width=768, height=512, frames=49, seed=7)
    node_types = [n["class_type"] for n in nodes]
    assert "LTXVideoSampler" in node_types or \
           any("LTX" in ct for ct in node_types)
    sampler = next(n for n in nodes if "Sampler" in n["class_type"])
    assert sampler["inputs"]["steps"] == 2


def test_wan22_i2v_lightx2v_has_load_image():
    """I2V 蓝图包含 LoadImage 节点引用起始图。"""
    nodes = wan22_i2v_lightx2v(
        "cinematic motion", image_ref="input_frame.png",
        width=1280, height=720, frames=81, seed=1)
    node_types = [n["class_type"] for n in nodes]
    assert "LoadImage" in node_types
    assert "SaveVideo" in node_types


# ═══════════════════════════════════════════════════════════════════
# LightX2V 注册表
# ═══════════════════════════════════════════════════════════════════

def test_registry_has_four_blueprints():
    """LightX2V 注册表包含 4 个加速蓝图。"""
    assert len(LIGHTX2V_REGISTRY) == 4
    for key in ["wan2.2_t2v_lightx2v", "wan2.2_t2v_lightx2v_gguf",
                "wan2.2_i2v_lightx2v", "ltx_t2v_lightx2v"]:
        assert key in LIGHTX2V_REGISTRY


def test_get_lightx2v_blueprint():
    """按 ID 获取 LightX2V 蓝图。"""
    bp = get_lightx2v_blueprint("wan2.2_t2v_lightx2v")
    assert bp is not None
    assert bp["speed_mode"] is True
    assert bp["speedup"] == "5x"
    assert bp["params"]["steps"] == 4


def test_get_lightx2v_blueprint_unknown():
    """未知 ID 返回 None。"""
    assert get_lightx2v_blueprint("nonexistent") is None


def test_list_lightx2v_blueprints():
    """list 返回全部 LightX2V 蓝图摘要。"""
    bps = list_lightx2v_blueprints()
    assert isinstance(bps, list)
    assert len(bps) == 4
    for bp in bps:
        assert "id" in bp
        assert "name" in bp
        assert bp["speed_mode"] is True


def test_recommend_lightx2v_t2v_24gb():
    """24GB VRAM → wan2.2_t2v_lightx2v (fp8)。"""
    result = recommend_lightx2v_blueprint(vram_gb=24, mode="t2v")
    assert result == "wan2.2_t2v_lightx2v"


def test_recommend_lightx2v_t2v_16gb():
    """16GB VRAM → wan2.2_t2v_lightx2v_gguf。"""
    result = recommend_lightx2v_blueprint(vram_gb=16, mode="t2v")
    assert result == "wan2.2_t2v_lightx2v_gguf"


def test_recommend_lightx2v_t2v_12gb():
    """12GB VRAM → ltx_t2v_lightx2v。"""
    result = recommend_lightx2v_blueprint(vram_gb=12, mode="t2v")
    assert result == "ltx_t2v_lightx2v"


def test_recommend_lightx2v_i2v_24gb():
    """24GB + i2v → wan2.2_i2v_lightx2v。"""
    result = recommend_lightx2v_blueprint(vram_gb=24, mode="i2v")
    assert result == "wan2.2_i2v_lightx2v"


def test_estimated_time_returns_float():
    """estimated_time 返回正浮点数。"""
    t = estimated_time("wan2.2_t2v_lightx2v", frames=81)
    assert isinstance(t, float)
    assert t > 0


# ═══════════════════════════════════════════════════════════════════
# comfy_client 视频 speed_mode 分支
# ═══════════════════════════════════════════════════════════════════

def test_build_txt2vid_speed_mode_lightx2v():
    """speed_mode=True 时 build_txt2vid 走 LightX2V 4步蓝图。"""
    wf = cc.build_txt2vid(
        "a fox running", width=640, height=480, length=33, speed_mode=True)
    assert isinstance(wf, dict)
    assert len(wf) > 0
    # LightX2V 蓝图用数字字符串作 key（"1", "2", ...）
    node_ids = set(wf.keys())
    assert "1" in node_ids or "2" in node_ids  # 数字字符串 key
    # 应包含 SaveVideo 节点
    has_save = any(
        "SaveVideo" in str(v.get("class_type", ""))
        for v in wf.values()
    )
    assert has_save


def test_build_txt2vid_quality_mode_wan22():
    """speed_mode=False 时 build_txt2vid 走标准双噪 Wan2.2。"""
    wf = cc.build_txt2vid(
        "test", width=640, height=480, length=17, speed_mode=False)
    assert isinstance(wf, dict)
    assert len(wf) > 0
    # 标准模式应包含 WanImageToVideo（Wan2.2 双噪工作流）
    node_types = [
        n.get("class_type", "") for n in wf.values()
        if isinstance(n, dict)
    ]
    assert "WanImageToVideo" in node_types


def test_build_img2vid_speed_mode_lightx2v():
    """img2vid speed_mode=True 走 LightX2V I2V 4步蓝图。"""
    wf = cc.build_img2vid(
        "input.png", "cinematic",
        width=640, height=480, length=33, speed_mode=True)
    assert isinstance(wf, dict)
    assert len(wf) > 0
    has_save = any(
        "SaveVideo" in str(v.get("class_type", ""))
        for v in wf.values()
    )
    assert has_save


def test_blueprint_nodes_to_wf_converts_list_to_dict():
    """_blueprint_nodes_to_wf 将节点列表转为 ComfyUI API dict 格式。"""
    nodes = [
        {"id": 1, "class_type": "CLIPLoader", "inputs": {"clip": "x"}},
        {"id": 2, "class_type": "VAELoader", "inputs": {"vae": "y"}},
    ]
    wf = cc._blueprint_nodes_to_wf(nodes)
    assert isinstance(wf, dict)
    assert wf["1"]["class_type"] == "CLIPLoader"
    assert wf["1"]["inputs"]["clip"] == "x"
    assert wf["2"]["class_type"] == "VAELoader"
    assert len(wf) == 2
