"""实体注册表单元测试 — entity_registry.py（v5.5 补测）

覆盖：
- 创建/读取/更新/删除 CRUD
- 按 kind 过滤列表
- 模糊搜索
- prompt 生成
- workflow_assembler 桥接
"""
from __future__ import annotations

import os
import json
import pytest

import entity_registry as er


@pytest.fixture(autouse=True)
def _isolate_store(monkeypatch, tmp_path):
    """每次测试使用独立存储目录，避免互相污染。"""
    monkeypatch.setattr(er, "_STORE_ROOT", str(tmp_path / "test_entities"))
    yield
    # 清理
    root = str(tmp_path / "test_entities")
    if os.path.isdir(root):
        import shutil
        shutil.rmtree(root, ignore_errors=True)


class TestCreateEntity:
    def test_create_character(self):
        ent = er.create_entity(er.EntityKind.CHARACTER, "孙悟空", alias="sun_wukong",
                               description="石猴，金箍棒，火眼金睛")
        assert ent.kind == er.EntityKind.CHARACTER
        assert ent.name == "孙悟空"
        assert ent.alias == "sun_wukong"
        assert ent.description == "石猴，金箍棒，火眼金睛"
        assert len(ent.entity_id) == 32  # UUID4 hex

    def test_create_persists_to_disk(self):
        ent = er.create_entity(er.EntityKind.PROP, "金箍棒")
        assert os.path.isfile(er._entity_path(ent.entity_id))

    def test_create_scene_with_tags(self):
        ent = er.create_entity(er.EntityKind.SCENE, "花果山", tags=["山", "瀑布", "水帘洞"])
        assert ent.tags == ["山", "瀑布", "水帘洞"]

    def test_create_with_prompt_override(self):
        ent = er.create_entity(er.EntityKind.CHARACTER, "哪吒",
                               prompt_override="A young warrior with a red lotus ribbon")
        assert ent.prompt_override == "A young warrior with a red lotus ribbon"


class TestGetEntity:
    def test_get_existing(self):
        ent = er.create_entity(er.EntityKind.CHARACTER, "test_get")
        found = er.get_entity(ent.entity_id)
        assert found is not None
        assert found.name == "test_get"

    def test_get_nonexistent(self):
        assert er.get_entity("nonexistent_id_12345") is None


class TestUpdateEntity:
    def test_update_name(self):
        ent = er.create_entity(er.EntityKind.CHARACTER, "旧名")
        er.update_entity(ent.entity_id, name="新名")
        reloaded = er.get_entity(ent.entity_id)
        assert reloaded.name == "新名"

    def test_update_description(self):
        ent = er.create_entity(er.EntityKind.CHARACTER, "test")
        er.update_entity(ent.entity_id, description="new description")
        assert er.get_entity(ent.entity_id).description == "new description"

    def test_update_tags(self):
        ent = er.create_entity(er.EntityKind.CHARACTER, "test")
        er.update_entity(ent.entity_id, tags=["a", "b"])
        assert er.get_entity(ent.entity_id).tags == ["a", "b"]

    def test_update_nonexistent_returns_none(self):
        assert er.update_entity("no_such_id", name="x") is None


class TestDeleteEntity:
    def test_delete_existing(self):
        ent = er.create_entity(er.EntityKind.CHARACTER, "可删除")
        assert er.delete_entity(ent.entity_id) is True
        assert er.get_entity(ent.entity_id) is None
        assert not os.path.isfile(er._entity_path(ent.entity_id))

    def test_delete_nonexistent(self):
        assert er.delete_entity("no_such_id") is False


class TestListEntities:
    def test_list_all(self):
        er.create_entity(er.EntityKind.CHARACTER, "A")
        er.create_entity(er.EntityKind.SCENE, "B")
        er.create_entity(er.EntityKind.PROP, "C")
        all_ents = er.list_entities()
        assert len(all_ents) == 3

    def test_list_filter_by_kind(self):
        er.create_entity(er.EntityKind.CHARACTER, "A")
        er.create_entity(er.EntityKind.CHARACTER, "B")
        er.create_entity(er.EntityKind.SCENE, "C")
        chars = er.list_entities(kind=er.EntityKind.CHARACTER)
        assert len(chars) == 2
        assert all(e.kind == er.EntityKind.CHARACTER for e in chars)

    def test_list_empty_store(self):
        assert er.list_entities() == []


class TestSearchEntities:
    def test_search_by_name(self):
        er.create_entity(er.EntityKind.CHARACTER, "孙悟空")
        er.create_entity(er.EntityKind.CHARACTER, "猪八戒")
        results = er.search_entities("悟空")
        assert len(results) == 1
        assert results[0].name == "孙悟空"

    def test_search_by_tag(self):
        er.create_entity(er.EntityKind.PROP, "金箍棒", tags=["武器", "神器"])
        er.create_entity(er.EntityKind.PROP, "九齿钉耙", tags=["武器"])
        results = er.search_entities("神器")
        assert len(results) == 1
        assert results[0].name == "金箍棒"

    def test_search_case_insensitive(self):
        er.create_entity(er.EntityKind.CHARACTER, "Nezha", alias="nezha")
        results = er.search_entities("NEZHA")
        assert len(results) == 1

    def test_search_no_match(self):
        assert er.search_entities("不存在的") == []


class TestBuildEntityPrompt:
    def test_character_prompt(self):
        ent = er.create_entity(er.EntityKind.CHARACTER, "孙悟空", alias="sun_wukong",
                               description="石猴握金箍棒", tags=["战斗"])
        prompt = er.build_entity_prompt(ent.entity_id)
        assert "孙悟空" in prompt
        assert "sun_wukong" in prompt
        assert "石猴握金箍棒" in prompt
        assert "战斗" in prompt

    def test_prompt_override_bypasses_auto(self):
        override = "CUSTOM OVERRIDE PROMPT"
        ent = er.create_entity(er.EntityKind.CHARACTER, "test",
                               prompt_override=override,
                               description="should be ignored")
        prompt = er.build_entity_prompt(ent.entity_id)
        assert prompt == override

    def test_nonexistent_entity_returns_none(self):
        assert er.build_entity_prompt("no_such_id") is None


class TestLoadAllEntities:
    def test_load_all_format(self):
        er.create_entity(er.EntityKind.CHARACTER, "TestChar", description="A test")
        data = er.load_all_entities()
        assert "entities" in data
        assert len(data["entities"]) == 1
        for eid, edata in data["entities"].items():
            assert "name" in edata
            assert "type" in edata
            assert "description" in edata


class TestVisualAnchor:
    def test_default_anchor(self):
        ent = er.create_entity(er.EntityKind.CHARACTER, "test")
        assert ent.anchor.seed == 0
        assert ent.anchor.first_frame_path is None

    def test_custom_anchor(self):
        anchor = er.VisualAnchor(seed=42, lora_name="test_lora.safetensors")
        ent = er.create_entity(er.EntityKind.CHARACTER, "test", anchor=anchor)
        assert ent.anchor.seed == 42
        assert ent.anchor.lora_name == "test_lora.safetensors"
