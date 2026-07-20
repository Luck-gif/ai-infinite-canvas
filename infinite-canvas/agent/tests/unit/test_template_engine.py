"""v5.4 模板引擎单元测试（v5.5 补测）

覆盖：
- TEMPLATE_REGISTRY 完整性（10 模板全注册，含蓝图桥接）
- 模板文件存在性（蓝图条目豁免 JSON 检查）
- _ui_to_api_format() 转换正确性
- load_template() 正常/异常路径
- get_template_names()
"""

import json
import os
import pytest

import comfy_client as cc

# v5.5: __blueprint__ 开头的条目是蓝图桥接（非 JSON 文件）
_BLUEPRINT_MARKER = "__blueprint__"


def _is_blueprint_entry(filename: str) -> bool:
    """判断是否为蓝图桥接条目。"""
    return filename.startswith(_BLUEPRINT_MARKER)


def _json_templates_only(registry: dict) -> dict:
    """返回仅有 JSON 文件模板的注册表子集。"""
    return {k: v for k, v in registry.items() if not _is_blueprint_entry(v)}


class TestTemplateRegistry:
    """TEMPLATE_REGISTRY 基础设施验证"""

    # ── v5.5 常量和工具函数 ──
    EXPECTED_COUNT = 10       # 9 JSON + 1 蓝图桥接（wan22-txt2vid）
    JSON_COUNT = 9            # 纯 JSON 模板数
    EXPECTED_BLUEPRINT = {"wan22-txt2vid"}

    def test_all_ten_entries_registered(self):
        """v5.5 模板引擎应注册 10 个模板（含 wan22-txt2vid 蓝图桥接）。"""
        assert len(cc.TEMPLATE_REGISTRY) == self.EXPECTED_COUNT

    def test_registry_keys_exact(self):
        expected = {
            "sdxl-txt2img", "sdxl-img2img", "sdxl-inpaint",
            "sdxl-lora", "sdxl-controlnet",
            "wan22-img2vid", "wan22-camera",
            "wan22-first-last", "wan22-fun-control",
            "wan22-txt2vid",
        }
        actual = set(cc.TEMPLATE_REGISTRY.keys())
        assert actual == expected

    def test_blueprint_entry_marked_correctly(self):
        """蓝图桥接条目必须以 __blueprint__ 开头。"""
        for key in self.EXPECTED_BLUEPRINT:
            filename = cc.TEMPLATE_REGISTRY[key]
            assert _is_blueprint_entry(filename), f"{key}: 应为蓝图标记，实为 {filename}"

    def test_template_files_exist(self):
        """每个注册的 JSON 模板文件必须存在（蓝图条目豁免）。"""
        templates_dir = cc._TEMPLATES_DIR
        for key, filename in _json_templates_only(cc.TEMPLATE_REGISTRY).items():
            path = os.path.join(templates_dir, filename)
            assert os.path.isfile(path), f"missing: {path}"

    def test_template_files_are_valid_json(self):
        """每个 JSON 模板文件必须是合法 JSON（蓝图条目豁免）。"""
        templates_dir = cc._TEMPLATES_DIR
        for key, filename in _json_templates_only(cc.TEMPLATE_REGISTRY).items():
            path = os.path.join(templates_dir, filename)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert isinstance(data, dict), f"{key}/{filename}: not a dict"

    def test_get_template_names(self):
        names = cc.get_template_names()
        assert len(names) == self.EXPECTED_COUNT
        assert isinstance(names, list)
        assert set(names) == set(cc.TEMPLATE_REGISTRY.keys())

    def test_apply_blueprint_template_returns_workflow(self):
        """wan22-txt2vid 蓝图模板应通过 apply_template() 返回合法工作流。"""
        wf = cc.apply_template("wan22-txt2vid", prompt="test wireframe",
                               width=832, height=480)
        assert isinstance(wf, dict)
        assert len(wf) > 0
        # LightX2V 蓝图生成的工作流应有节点包含 class_type
        for node_id, node_info in wf.items():
            assert "class_type" in node_info, f"node {node_id} 缺少 class_type"


class TestUiToApiFormat:
    """_ui_to_api_format() 转换验证"""

    def test_json_templates_convert_to_api_format(self):
        """全部 JSON 模板通过 _ui_to_api_format() 转换不应抛异常（蓝图豁免 load_template）。"""
        for key in _json_templates_only(cc.TEMPLATE_REGISTRY):
            wf = cc.load_template(key)
            assert isinstance(wf, dict)
            assert len(wf) > 0, f"{key}: 空工作流"

    def test_converted_nodes_have_class_type(self):
        """API 格式中每个 JSON 模板节点必须有 class_type（蓝图豁免）。"""
        for key in _json_templates_only(cc.TEMPLATE_REGISTRY):
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

    def test_load_json_templates_do_not_raise(self):
        for key in _json_templates_only(cc.TEMPLATE_REGISTRY):
            cc.load_template(key)  # 不应抛异常
