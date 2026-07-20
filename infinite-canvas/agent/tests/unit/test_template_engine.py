"""v5.4 模板引擎单元测试（v5.5 补测）

覆盖：
- TEMPLATE_REGISTRY 完整性（9 模板全注册）
- 模板文件存在性
- _ui_to_api_format() 转换正确性
- load_template() 正常/异常路径
- get_template_names()
"""
from __future__ import annotations

import json
import os
import pytest

import comfy_client as cc


class TestTemplateRegistry:
    """TEMPLATE_REGISTRY 基础设施验证"""

    def test_all_nine_entries_registered(self):
        """v5.4 模板引擎应注册 9 个模板。"""
        assert len(cc.TEMPLATE_REGISTRY) == 9

    def test_registry_keys_exact(self):
        expected = {
            "sdxl-txt2img", "sdxl-img2img", "sdxl-inpaint",
            "sdxl-lora", "sdxl-controlnet",
            "wan22-img2vid", "wan22-camera",
            "wan22-first-last", "wan22-fun-control",
        }
        actual = set(cc.TEMPLATE_REGISTRY.keys())
        assert actual == expected

    def test_template_files_exist(self):
        """每个注册的模板 JSON 文件必须存在。"""
        templates_dir = cc._TEMPLATES_DIR
        for key, filename in cc.TEMPLATE_REGISTRY.items():
            path = os.path.join(templates_dir, filename)
            assert os.path.isfile(path), f"missing: {path}"

    def test_template_files_are_valid_json(self):
        """每个模板文件必须是合法 JSON。"""
        templates_dir = cc._TEMPLATES_DIR
        for key, filename in cc.TEMPLATE_REGISTRY.items():
            path = os.path.join(templates_dir, filename)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert isinstance(data, dict), f"{key}/{filename}: not a dict"

    def test_get_template_names(self):
        names = cc.get_template_names()
        assert len(names) == 9
        assert isinstance(names, list)
        # 只验证包含所有 key，不要求排序
        assert set(names) == set(cc.TEMPLATE_REGISTRY.keys())


class TestUiToApiFormat:
    """_ui_to_api_format() 转换验证"""

    def test_all_nine_convert_to_api_format(self):
        """全部 9 模板通过 _ui_to_api_format() 转换不应抛异常。"""
        for key in cc.TEMPLATE_REGISTRY:
            wf = cc.load_template(key)
            assert isinstance(wf, dict)
            assert len(wf) > 0, f"{key}: 空工作流"

    def test_converted_nodes_have_class_type(self):
        """API 格式中每个节点必须有 class_type。"""
        for key in cc.TEMPLATE_REGISTRY:
            wf = cc.load_template(key)
            for node_id, node_info in wf.items():
                assert "class_type" in node_info, \
                    f"{key}/{node_id}: 缺少 class_type"
                assert isinstance(node_info["class_type"], str), \
                    f"{key}/{node_id}: class_type 非字符串"

    def test_sdxl_templates_have_checkpoint_loader(self):
        """SDXL 模板必须包含 CheckpointLoaderSimple。"""
        for key in ["sdxl-txt2img", "sdxl-img2img", "sdxl-inpaint",
                     "sdxl-lora", "sdxl-controlnet"]:
            wf = cc.load_template(key)
            has_loader = any(
                n.get("class_type") == "CheckpointLoaderSimple"
                for n in wf.values()
            )
            assert has_loader, f"{key}: 缺少 CheckpointLoaderSimple"

    def test_wan22_templates_have_unet_loader(self):
        """WAN2.2 模板必须包含 UNETLoader。"""
        for key in ["wan22-img2vid", "wan22-camera",
                     "wan22-first-last", "wan22-fun-control"]:
            wf = cc.load_template(key)
            has_unet = any(
                n.get("class_type") == "UNETLoader"
                for n in wf.values()
            )
            assert has_unet, f"{key}: 缺少 UNETLoader"

    def test_sdxl_node_counts(self):
        """SDXL 模板节点数合理（5-15 范围）。"""
        for key in ["sdxl-txt2img", "sdxl-img2img", "sdxl-inpaint",
                     "sdxl-lora", "sdxl-controlnet"]:
            wf = cc.load_template(key)
            assert 5 <= len(wf) <= 15, \
                f"{key}: 节点数 {len(wf)} 异常"

    def test_wan22_node_counts(self):
        """WAN2.2 模板节点数合理（8-25 范围）。"""
        for key in ["wan22-img2vid", "wan22-camera",
                     "wan22-first-last", "wan22-fun-control"]:
            wf = cc.load_template(key)
            assert 8 <= len(wf) <= 25, \
                f"{key}: 节点数 {len(wf)} 异常"


class TestLoadTemplate:
    """load_template() 函数验证"""

    def test_load_valid_returns_dict(self):
        wf = cc.load_template("sdxl-txt2img")
        assert isinstance(wf, dict)
        assert len(wf) > 0

    def test_load_invalid_raises_valueerror(self):
        with pytest.raises(ValueError, match="未知模板"):
            cc.load_template("nonexistent-template-xyz")

    def test_load_all_nine_do_not_raise(self):
        for key in cc.TEMPLATE_REGISTRY:
            cc.load_template(key)  # 不应抛异常
