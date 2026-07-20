"""意图映射单元测试 — intent_map.py（v5.5 补测）

覆盖：
- _coerce_action() 降级链（inpaint→img2img→txt2img）
- _model_token() 模型解析
- list_templates() 模板列表完整性
- SUPPORTED_ACTIONS 覆盖全部 TEMPLATES
"""
from __future__ import annotations

import pytest

import intent_map as im


class TestCoerceAction:
    """_coerce_action() 降级路由逻辑"""

    # ── 不退化的路径 ──
    def test_txt2img_no_degradation(self):
        action, coerced = im._coerce_action("txt2img", None, None)
        assert action == "txt2img"
        assert coerced is False

    def test_img2img_with_input_no_degradation(self):
        action, coerced = im._coerce_action("img2img", "test.png", None)
        assert action == "img2img"
        assert coerced is False

    def test_inpaint_with_both_images_no_degradation(self):
        action, coerced = im._coerce_action("inpaint", "img.png", "mask.png")
        assert action == "inpaint"
        assert coerced is False

    def test_txt2vid_no_degradation(self):
        action, coerced = im._coerce_action("txt2vid", None, None)
        assert action == "txt2vid"
        assert coerced is False

    def test_img2vid_no_degradation(self):
        action, coerced = im._coerce_action("img2vid", "video.png", None)
        assert action == "img2vid"
        assert coerced is False

    def test_regional_no_degradation(self):
        action, coerced = im._coerce_action("regional", None, None)
        assert action == "regional"
        assert coerced is False

    # ── 退化链 ──
    def test_inpaint_without_mask_degrade_to_img2img(self):
        action, coerced = im._coerce_action("inpaint", "img.png", None)
        assert action == "img2img"
        assert coerced is True

    def test_inpaint_without_any_image_degrade_to_txt2img(self):
        action, coerced = im._coerce_action("inpaint", None, None)
        assert action == "txt2img"
        assert coerced is True

    def test_img2img_without_input_degrade_to_txt2img(self):
        action, coerced = im._coerce_action("img2img", None, None)
        assert action == "txt2img"
        assert coerced is True

    def test_outpaint_without_input_degrade_to_txt2img(self):
        action, coerced = im._coerce_action("outpaint", None, None)
        assert action == "txt2img"
        assert coerced is True

    def test_unknown_action_degrade_to_txt2img(self):
        action, coerced = im._coerce_action("unknown_action_xyz", None, None)
        assert action == "txt2img"
        assert coerced is True

    # ── 支持但无需额外参数 ──
    def test_face_consistency_no_degradation(self):
        action, coerced = im._coerce_action("face_consistency", None, None)
        assert action == "face_consistency"
        assert coerced is False

    def test_image_blend_no_degradation(self):
        action, coerced = im._coerce_action("image_blend", None, None)
        assert action == "image_blend"
        assert coerced is False

    def test_storyboard_no_degradation(self):
        action, coerced = im._coerce_action("storyboard", None, None)
        assert action == "storyboard"
        assert coerced is False


class TestModelToken:
    def test_qwen_token(self):
        assert im._model_token({"model": "qwen2"}) == "qwen2"

    def test_sdxl_token(self):
        assert im._model_token({"model": "sdxl"}) == "sdxl"

    def test_default_token(self):
        assert im._model_token({}) == ""

    def test_empty_dict(self):
        assert im._model_token({}) == ""


class TestListTemplates:
    def test_returns_list(self):
        assert isinstance(im.list_templates(), list)

    def test_has_expected_count(self):
        assert len(im.list_templates()) >= 8  # 10 templates in TEMPLATES

    def test_each_has_required_fields(self):
        for tpl in im.list_templates():
            assert "id" in tpl
            assert "name" in tpl
            assert "category" in tpl
            assert "params" in tpl

    def test_all_ids_unique(self):
        ids = [t["id"] for t in im.list_templates()]
        assert len(ids) == len(set(ids))


class TestSupportedActions:
    def test_all_template_categories_covered(self):
        """SUPPORTED_ACTIONS 必须包含 TEMPLATES 中所有 category。"""
        categories = {t["category"] for t in im.TEMPLATES}
        uncovered = categories - im.SUPPORTED_ACTIONS
        assert not uncovered, f"未覆盖的 category: {uncovered}"

    def test_video_actions_supported(self):
        assert "txt2vid" in im.SUPPORTED_ACTIONS
        assert "img2vid" in im.SUPPORTED_ACTIONS

    def test_consistency_actions_supported(self):
        assert "face_consistency" in im.SUPPORTED_ACTIONS
        assert "style_consistency" in im.SUPPORTED_ACTIONS
        assert "scene_consistency" in im.SUPPORTED_ACTIONS
        assert "prop_consistency" in im.SUPPORTED_ACTIONS
