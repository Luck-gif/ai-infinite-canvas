"""故事板与实体集成单元测试 (v4.59)

覆盖：
  - 实体 prompt 前缀生成（分镜引用场景）
  - 按 kind 批量过滤（分镜时间轴实体选择器）
  - 搜索 + 多实体组合
  - 实体 ID 唯一性 + prompt_override
"""

from __future__ import annotations

import os
import pytest

import entity_registry as er


@pytest.fixture(autouse=True)
def _temp_store(monkeypatch, tmp_path):
    """将实体存储临时指向 tmp_path，避免污染真实 outputs。"""
    monkeypatch.setattr(er, "_STORE_ROOT", str(tmp_path))
    er._ensure_store()
    yield
    for f in os.listdir(str(tmp_path)):
        os.remove(os.path.join(str(tmp_path), f))


# ── 故事板分镜引用场景（单个实体 prompt） ────────────────────────

def test_character_prompt_for_shot():
    """角色实体的 prompt 前缀可被分镜引用。"""
    ent = er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="Alice",
        alias="Alice",
        description="A blonde girl in a blue dress",
        tags=["protagonist"],
    )
    prompt = er.build_entity_prompt(ent.entity_id)
    assert prompt is not None
    assert "Alice" in prompt
    assert "blonde" in prompt or "blue" in prompt


def test_scene_prompt_for_shot():
    """场景实体的 prompt 前缀。"""
    ent = er.create_entity(
        kind=er.EntityKind.SCENE,
        name="Cyberpunk City",
        alias="Night City",
        description="Neon-lit rainy streets, towering skyscrapers",
        tags=["cyberpunk", "city"],
    )
    prompt = er.build_entity_prompt(ent.entity_id)
    assert prompt is not None
    assert "Cyberpunk City" in prompt
    assert "Neon-lit" in prompt


def test_style_prompt_for_shot():
    """风格实体的 prompt 前缀。"""
    ent = er.create_entity(
        kind=er.EntityKind.STYLE,
        name="Oil Painting",
        alias="Oil",
        description="Classical oil painting style, rich textures, visible brushstrokes",
        tags=["painting", "art"],
    )
    prompt = er.build_entity_prompt(ent.entity_id)
    assert prompt is not None
    assert "Oil Painting" in prompt
    assert "oil painting" in prompt.lower()


def test_prop_prompt_for_shot():
    """道具实体的 prompt 前缀。"""
    ent = er.create_entity(
        kind=er.EntityKind.PROP,
        name="Excalibur",
        alias="Holy Sword",
        description="A glowing legendary sword with golden hilt",
        tags=["weapon", "legendary"],
    )
    prompt = er.build_entity_prompt(ent.entity_id)
    assert prompt is not None
    assert "Excalibur" in prompt
    assert "sword" in prompt.lower()


# ── 批量过滤 ────────────────────────────────────────────────────

def test_list_entities_by_kind_for_shot_binding():
    """按 kind 过滤：分镜时间轴实体选择器场景。"""
    er.create_entity(kind=er.EntityKind.CHARACTER, name="Hero", description="brave warrior")
    er.create_entity(kind=er.EntityKind.CHARACTER, name="Villain", description="dark lord")
    er.create_entity(kind=er.EntityKind.SCENE, name="Forest", description="dense forest")
    er.create_entity(kind=er.EntityKind.PROP, name="Sword", description="sharp blade")

    chars = er.list_entities(kind=er.EntityKind.CHARACTER)
    assert len(chars) == 2

    scenes = er.list_entities(kind=er.EntityKind.SCENE)
    assert len(scenes) == 1

    props = er.list_entities(kind=er.EntityKind.PROP)
    assert len(props) == 1


# ── 搜索功能 ────────────────────────────────────────────────────

def test_search_entities_for_shot_binding():
    """分镜时间轴搜索实体（按名称 + 按标签）。"""
    er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="John",
        description="a detective",
        tags=["detective"],
    )
    er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="Mary",
        description="a scientist",
        tags=["scientist"],
    )
    er.create_entity(
        kind=er.EntityKind.SCENE,
        name="Office",
        description="modern office",
    )

    # 按名称搜索
    results = er.search_entities("John")
    assert len(results) == 1
    assert results[0].name == "John"

    # 按标签搜索
    results = er.search_entities("detective")
    assert len(results) >= 1
    assert results[0].name == "John"


# ── 多实体组合 ──────────────────────────────────────────────────

def test_multi_entity_prompt_for_shot():
    """一个分镜同时引用角色 + 场景 + 风格的 prompt 均可独立生成。"""
    char = er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="Sam",
        description="a cowboy wearing a brown hat",
        tags=["cowboy"],
    )
    scene = er.create_entity(
        kind=er.EntityKind.SCENE,
        name="Desert",
        description="vast desert with cacti",
        tags=["desert"],
    )
    style = er.create_entity(
        kind=er.EntityKind.STYLE,
        name="Watercolor",
        description="soft watercolor painting",
        tags=["art"],
    )

    char_prompt = er.build_entity_prompt(char.entity_id)
    scene_prompt = er.build_entity_prompt(scene.entity_id)
    style_prompt = er.build_entity_prompt(style.entity_id)

    assert char_prompt is not None and "Sam" in char_prompt
    assert scene_prompt is not None and "Desert" in scene_prompt
    assert style_prompt is not None and "Watercolor" in style_prompt

    # 组合后的 prompt 可正确拼接
    combined = f"{char_prompt}, {scene_prompt}, {style_prompt}"
    assert "Sam" in combined
    assert "Desert" in combined
    assert "Watercolor" in combined


def test_missing_entity_prompt_returns_none():
    """不存在的实体 ID 返回 None（不崩溃）。"""
    prompt = er.build_entity_prompt("nonexistent-id-12345")
    assert prompt is None


# ── 实体的唯一性 ────────────────────────────────────────────────

def test_entity_ids_are_unique():
    """创建的实体 ID 应唯一。"""
    a = er.create_entity(kind=er.EntityKind.CHARACTER, name="A", description="desc")
    b = er.create_entity(kind=er.EntityKind.CHARACTER, name="B", description="desc")
    assert a.entity_id != b.entity_id
    assert len(a.entity_id) > 0
    assert len(b.entity_id) > 0


# ── prompt_override 覆盖 ────────────────────────────────────────

def test_prompt_override_in_shot_context():
    """实体设置 prompt_override 后，分镜直接使用该覆盖 prompt。"""
    ent = er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="Custom Hero",
        description="irrelevant",
        tags=["custom"],
    )
    # 设置覆盖 prompt
    updated = er.update_entity(ent.entity_id, prompt_override="a custom prompt: hero with cape")
    assert updated is not None

    prompt = er.build_entity_prompt(ent.entity_id)
    assert prompt is not None
    assert "custom" in prompt
    assert "hero with cape" in prompt
