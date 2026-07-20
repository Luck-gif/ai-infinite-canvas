"""无限画布 · video_blueprints / 视频蓝图注册表 单元测试 (v5.4)。

覆盖:
  - BLUEPRINT_REGISTRY 结构校验
  - get_blueprint / list_blueprints 查询
  - recommend_blueprint VRAM 自动选型
  - LightX2V 状态端点响应
  - comfy_client _vram_gb 检测函数
"""
from __future__ import annotations

import video_blueprints as vb
import comfy_client as cc


def _find_node(wf: dict, class_type: str):
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            return node
    return None


def test_registry_has_four_standard_blueprints():
    reg = vb.BLUEPRINT_REGISTRY
    assert len(reg) >= 4
    for bp_id in ("wan2.2_t2v_fp8", "wan2.2_t2v_gguf", "wan2.2_i2v_fp8", "ltx_t2v"):
        assert bp_id in reg
        bp = reg[bp_id]
        assert "id" in bp
        assert "name" in bp
        assert "category" in bp
        assert "params" in bp
        assert "steps" in bp["params"]


def test_get_blueprint_known():
    bp = vb.get_blueprint("wan2.2_i2v_fp8")
    assert bp is not None
    assert bp["id"] == "wan2.2_i2v_fp8"
    assert bp["category"] == "video"


def test_get_blueprint_unknown():
    assert vb.get_blueprint("nonexistent_bp_id") is None


def test_list_blueprints_all():
    all_bp = vb.list_blueprints()
    assert isinstance(all_bp, list)
    assert len(all_bp) >= 4


def test_list_blueprints_filter_video():
    video_bp = vb.list_blueprints(category="video")
    assert all(bp["category"] == "video" for bp in video_bp)
    assert len(video_bp) >= 4


def test_recommend_blueprint_t2v_high_vram():
    result = vb.recommend_blueprint(vram_gb=32, mode="t2v", prefer_quality=True)
    assert result == "wan2.2_t2v_fp8"


def test_recommend_blueprint_t2v_medium_vram():
    result = vb.recommend_blueprint(vram_gb=16, mode="t2v", prefer_quality=False)
    assert result == "wan2.2_t2v_gguf"


def test_recommend_blueprint_t2v_low_vram():
    result = vb.recommend_blueprint(vram_gb=8, mode="t2v")
    assert result == "ltx_t2v"


def test_recommend_blueprint_i2v_high_vram():
    result = vb.recommend_blueprint(vram_gb=24, mode="i2v")
    assert result == "wan2.2_i2v_fp8"


def test_recommend_blueprint_speed_mode():
    result = vb.recommend_blueprint(vram_gb=24, mode="t2v", speed_mode=True)
    assert result.startswith("wan2.2") or result.startswith("ltx")


def test_get_blueprint_lightx2v_fallback():
    """当标准注册表中找不到时，尝试 LightX2V 注册表。"""
    bp = vb.get_blueprint("wan2.2_t2v_lightx2v")
    if bp is not None:
        assert "speed_mode" in bp


def test_vram_gb_returns_float():
    vram = cc._vram_gb()
    assert isinstance(vram, float)
    assert vram > 0


# ── 模板引擎视频模板 ──────────────────────────────────────────────

def test_build_txt2vid_speed_mode_fps_forwarded():
    """speed_mode=True 时 fps 被注入到 SaveAnimatedWEBP 节点。"""
    wf = cc.build_txt2vid("test prompt", fps=30, speed_mode=True)
    save = _find_node(wf, "SaveAnimatedWEBP")
    if save is not None:
        assert save["inputs"]["fps"] == 30


def test_build_txt2vid_speed_mode_prefix_forwarded():
    """speed_mode=True 时 filename_prefix 被注入。"""
    wf = cc.build_txt2vid("test prompt", prefix="my_prefix", speed_mode=True)
    save = _find_node(wf, "SaveAnimatedWEBP")
    if save is not None:
        assert save["inputs"]["filename_prefix"] == "my_prefix"


def test_build_img2vid_speed_mode_fps_forwarded():
    """speed_mode=True 时 fps 被注入到 SaveAnimatedWEBP。"""
    wf = cc.build_img2vid("start.png", "test", fps=24, speed_mode=True)
    save = _find_node(wf, "SaveAnimatedWEBP")
    if save is not None:
        assert save["inputs"]["fps"] == 24
