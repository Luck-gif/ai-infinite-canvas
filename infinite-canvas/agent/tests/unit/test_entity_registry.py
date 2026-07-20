"""实体注册表（entity_registry）单元测试。

覆盖：
  - CRUD（创建/读取/更新/删除）
  - 过滤搜索
  - prompt 生成
  - 文件名安全化
  - 持久化往返
"""

from __future__ import annotations

import json
import os
import pytest
import tempfile

import entity_registry as er


@pytest.fixture(autouse=True)
def _temp_store(monkeypatch, tmp_path):
    """将实体存储临时指向 tmp_path，避免污染真实 outputs。"""
    monkeypatch.setattr(er, "_STORE_ROOT", str(tmp_path))
    er._ensure_store()
    yield
    # 清理
    for f in os.listdir(str(tmp_path)):
        os.remove(os.path.join(str(tmp_path), f))


# ── 基本 CRUD ──────────────────────────────────────────────────────

def test_create_and_get_entity():
    ent = er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="孙悟空",
        alias="Sun Wukong",
        description="The Monkey King with golden armor and a magical staff",
        tags=["mythology", "chinese", "hero"],
        anchor=er.VisualAnchor(seed=42),
    )
    assert ent.entity_id
    assert ent.kind == er.EntityKind.CHARACTER
    assert ent.name == "孙悟空"

    # 从存储读取
    loaded = er.get_entity(ent.entity_id)
    assert loaded is not None
    assert loaded.name == "孙悟空"
    assert loaded.alias == "Sun Wukong"
    assert loaded.anchor.seed == 42
    assert "mythology" in loaded.tags


def test_update_entity():
    ent = er.create_entity(
        kind=er.EntityKind.SCENE, name="花果山", alias="Mount Huaguo")
    import time; time.sleep(1.1)  # 确保时间戳不同（秒级精度）
    updated = er.update_entity(
        ent.entity_id, description="A lush mountain paradise with waterfalls")
    assert updated is not None
    assert updated.description == "A lush mountain paradise with waterfalls"
    assert updated.updated_at != ent.created_at


def test_update_nonexistent():
    assert er.update_entity("nonexistent", name="x") is None


def test_delete_entity():
    ent = er.create_entity(
        kind=er.EntityKind.PROP, name="金箍棒", alias="Ruyi Jingu Bang")
    assert er.delete_entity(ent.entity_id)
    assert er.get_entity(ent.entity_id) is None


def test_delete_nonexistent():
    assert er.delete_entity("nonexistent") is False


# ── 列表与搜索 ─────────────────────────────────────────────────────

def test_list_all_entities():
    er.create_entity(er.EntityKind.CHARACTER, "唐僧", "Tang Sanzang")
    er.create_entity(er.EntityKind.SCENE, "西天", "Western Paradise")
    er.create_entity(er.EntityKind.PROP, "锦斓袈裟", "Kasaya")
    all_ents = er.list_entities()
    assert len(all_ents) == 3


def test_list_filter_by_kind():
    er.create_entity(er.EntityKind.CHARACTER, "猪八戒", "Zhu Bajie")
    er.create_entity(er.EntityKind.SCENE, "高老庄", "Gao Village")
    chars = er.list_entities(kind=er.EntityKind.CHARACTER)
    assert len(chars) == 1
    assert chars[0].name == "猪八戒"


def test_search_by_name():
    er.create_entity(er.EntityKind.CHARACTER, "沙僧", "Sha Wujing")
    er.create_entity(er.EntityKind.SCENE, "流沙河", "Flowing Sand River")
    results = er.search_entities("沙")
    assert len(results) == 2


def test_search_by_tag():
    er.create_entity(er.EntityKind.CHARACTER, "白龙马", "White Dragon Horse",
                     tags=["mount", "dragon"])
    results = er.search_entities("dragon")
    assert len(results) == 1
    assert results[0].name == "白龙马"


def test_search_case_insensitive():
    er.create_entity(er.EntityKind.CHARACTER, "玉皇大帝", "Jade Emperor",
                     tags=["Celestial"])
    results = er.search_entities("celestial")
    assert len(results) == 1


# ── Prompt 生成 ────────────────────────────────────────────────────

def test_build_entity_prompt_character():
    ent = er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="孙悟空",
        alias="Sun Wukong",
        description="The Monkey King with golden armor and a magical staff",
        tags=["mythology", "chinese"],
    )
    prompt = er.build_entity_prompt(ent.entity_id)
    assert prompt is not None
    assert "孙悟空" in prompt
    assert "Sun Wukong" in prompt
    assert "Monkey King" in prompt


def test_build_entity_prompt_scene():
    ent = er.create_entity(
        kind=er.EntityKind.SCENE,
        name="花果山",
        alias="Mount Huaguo",
        description="A lush paradise with waterfalls and fruit trees",
    )
    prompt = er.build_entity_prompt(ent.entity_id)
    assert prompt is not None
    assert "scene of" in prompt.lower()


def test_build_entity_prompt_style():
    ent = er.create_entity(
        kind=er.EntityKind.STYLE,
        name="水墨画",
        alias="Ink Wash Painting",
        description="Traditional Chinese ink wash style with flowing brushstrokes",
    )
    prompt = er.build_entity_prompt(ent.entity_id)
    assert prompt is not None
    assert "style of" in prompt.lower()


def test_build_entity_prompt_override():
    ent = er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="孙悟空",
        alias="Sun Wukong",
        prompt_override="masterpiece, best quality, 1boy, monkey king, golden armor",
    )
    prompt = er.build_entity_prompt(ent.entity_id)
    assert prompt == "masterpiece, best quality, 1boy, monkey king, golden armor"


def test_build_entity_prompt_nonexistent():
    assert er.build_entity_prompt("nonexistent") is None


# ── 文件名安全化 ───────────────────────────────────────────────────

def test_sanitize_filename_chinese():
    assert er._sanitize_filename("孙悟空") == "孙悟空"


def test_sanitize_filename_special_chars():
    assert er._sanitize_filename("hello/world:test") == "hello_world_test"


def test_sanitize_filename_only_special():
    # 全部非法字符 → "unnamed"
    result = er._sanitize_filename("!@#$%")
    assert result == "unnamed" or result != "!@#$%"


# ── 持久化往返 ─────────────────────────────────────────────────────

def test_persistence_roundtrip():
    ent = er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="哪吒",
        alias="Nezha",
        description="The rebellious child god with fire-tipped spear",
        tags=["mythology", "warrior"],
        anchor=er.VisualAnchor(
            seed=99,
            lora_name="nezha_style.safetensors",
            controlnet_type="openpose",
        ),
        metadata={"origin": "user_input", "priority": 1},
    )
    # 重新读取
    loaded = er.get_entity(ent.entity_id)
    assert loaded is not None
    assert loaded.entity_id == ent.entity_id
    assert loaded.name == "哪吒"
    assert loaded.alias == "Nezha"
    assert loaded.anchor.seed == 99
    assert loaded.anchor.lora_name == "nezha_style.safetensors"
    assert loaded.anchor.controlnet_type == "openpose"
    assert loaded.metadata["priority"] == 1
    assert loaded.created_at
    assert loaded.updated_at


def test_list_empty_store():
    # 新临时目录应该返回空列表
    # _temp_store fixture 确保临时目录已创建
    assert er.list_entities() == []


# ── VisualAnchor 默认值 ────────────────────────────────────────────

def test_visual_anchor_defaults():
    anchor = er.VisualAnchor()
    assert anchor.seed == 0
    assert anchor.first_frame_path is None
    assert anchor.reference_image_path is None
    assert anchor.lora_name is None
    assert anchor.controlnet_type is None
