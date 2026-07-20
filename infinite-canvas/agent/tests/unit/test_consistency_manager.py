"""一致性管理器（consistency_manager）单元测试。

覆盖：
  - 核心约束（角色/场景/道具/风格/叙事/空间）
  - 管道组合
  - 批量帧处理
  - 边界情况（空上下文、无实体）
"""

from __future__ import annotations

import os
import pytest
import tempfile

import entity_registry as er
import consistency_manager as cm


@pytest.fixture(autouse=True)
def _temp_store(monkeypatch, tmp_path):
    """将实体存储临时指向 tmp_path。"""
    monkeypatch.setattr(er, "_STORE_ROOT", str(tmp_path))
    er._ensure_store()
    yield
    for f in os.listdir(str(tmp_path)):
        os.remove(os.path.join(str(tmp_path), f))


@pytest.fixture
def sun_wukong():
    return er.create_entity(
        kind=er.EntityKind.CHARACTER,
        name="孙悟空",
        alias="Sun Wukong",
        description="The Monkey King with golden armor",
        tags=["mythology"],
        anchor=er.VisualAnchor(seed=42, lora_name="wukong.safetensors"),
    )


@pytest.fixture
def huaguo():
    return er.create_entity(
        kind=er.EntityKind.SCENE,
        name="花果山",
        alias="Mount Huaguo",
        description="A lush paradise with waterfalls",
        anchor=er.VisualAnchor(controlnet_type="depth"),
    )


@pytest.fixture
def staff():
    return er.create_entity(
        kind=er.EntityKind.PROP,
        name="金箍棒",
        alias="Ruyi Jingu Bang",
        description="A magical staff that can change size",
    )


@pytest.fixture
def ink_style():
    return er.create_entity(
        kind=er.EntityKind.STYLE,
        name="水墨画",
        alias="Ink Wash Painting",
        description="Traditional Chinese ink wash style",
        anchor=er.VisualAnchor(lora_name="ink_wash.safetensors"),
    )


# ── 角色一致性 ──────────────────────────────────────────────────────

def test_character_consistency(sun_wukong):
    ctx = cm.build_frame_context(
        prompt="masterpiece, best quality",
        character_ids=[sun_wukong.entity_id],
    )
    result = cm.character_consistency(ctx)
    assert "孙悟空" in result.prompt
    assert "Sun Wukong" in result.prompt
    assert "Monkey King" in result.prompt


def test_character_consistency_empty():
    ctx = cm.build_frame_context(prompt="test")
    result = cm.character_consistency(ctx)
    assert result.prompt == "test"


def test_character_consistency_multiple(sun_wukong):
    bajie = er.create_entity(
        er.EntityKind.CHARACTER, "猪八戒", "Zhu Bajie",
        description="A pig demon with a rake")
    ctx = cm.build_frame_context(
        prompt="test",
        character_ids=[sun_wukong.entity_id, bajie.entity_id],
    )
    result = cm.character_consistency(ctx)
    assert "孙悟空" in result.prompt
    assert "猪八戒" in result.prompt


# ── 场景一致性 ──────────────────────────────────────────────────────

def test_scene_consistency(huaguo):
    ctx = cm.build_frame_context(prompt="test", scene_id=huaguo.entity_id)
    result = cm.scene_consistency(ctx)
    assert "花果山" in result.prompt


def test_scene_consistency_none():
    ctx = cm.build_frame_context(prompt="test")
    result = cm.scene_consistency(ctx)
    assert result.prompt == "test"


# ── 道具一致性 ──────────────────────────────────────────────────────

def test_prop_consistency(staff):
    ctx = cm.build_frame_context(prompt="test", prop_ids=[staff.entity_id])
    result = cm.prop_consistency(ctx)
    assert "金箍棒" in result.prompt


def test_prop_consistency_empty():
    ctx = cm.build_frame_context(prompt="test")
    result = cm.prop_consistency(ctx)
    assert result.prompt == "test"


# ── 风格一致性 ──────────────────────────────────────────────────────

def test_style_consistency(ink_style):
    ctx = cm.build_frame_context(prompt="test", style_id=ink_style.entity_id)
    result = cm.style_consistency(ctx)
    assert "水墨画" in result.prompt
    assert "lora_stack" in result.params
    assert result.params["lora_stack"][0]["name"] == "ink_wash.safetensors"


def test_style_consistency_no_lora():
    ent = er.create_entity(
        er.EntityKind.STYLE, "简约", "Minimal", anchor=er.VisualAnchor())
    ctx = cm.build_frame_context(prompt="test", style_id=ent.entity_id)
    result = cm.style_consistency(ctx)
    assert "lora_stack" not in result.params


# ── 叙事一致性 ──────────────────────────────────────────────────────

def test_narrative_consistency_opening():
    ctx = cm.build_frame_context(prompt="test", frame_index=0, total_frames=10)
    result = cm.narrative_consistency(ctx)
    assert "[opening scene]" in result.prompt


def test_narrative_consistency_closing():
    ctx = cm.build_frame_context(prompt="test", frame_index=9, total_frames=10)
    result = cm.narrative_consistency(ctx)
    assert "[closing scene]" in result.prompt


def test_narrative_consistency_mid():
    ctx = cm.build_frame_context(prompt="test", frame_index=4, total_frames=10)
    result = cm.narrative_consistency(ctx)
    assert "[storyboard frame 5/10]" in result.prompt


def test_narrative_consistency_single_frame():
    ctx = cm.build_frame_context(prompt="test", frame_index=0, total_frames=1)
    result = cm.narrative_consistency(ctx)
    assert "[opening scene]" not in result.prompt
    assert result.prompt == "test"


# ── 空间一致性 ──────────────────────────────────────────────────────

def test_spatial_consistency_with_controlnet(huaguo):
    ctx = cm.build_frame_context(prompt="test", scene_id=huaguo.entity_id)
    result = cm.spatial_consistency(ctx)
    assert result.params.get("controlnet_type") == "depth"


def test_spatial_consistency_no_scene():
    ctx = cm.build_frame_context(prompt="test")
    result = cm.spatial_consistency(ctx)
    assert "controlnet_type" not in result.params


# ── 管道组合 ────────────────────────────────────────────────────────

def test_apply_pipeline_full(sun_wukong, huaguo, staff, ink_style):
    ctx = cm.build_frame_context(
        prompt="masterpiece",
        character_ids=[sun_wukong.entity_id],
        scene_id=huaguo.entity_id,
        prop_ids=[staff.entity_id],
        style_id=ink_style.entity_id,
        frame_index=0,
        total_frames=5,
    )
    result = cm.apply_pipeline(ctx)
    # 应该包含所有注入
    assert "孙悟空" in result.prompt
    assert "花果山" in result.prompt
    assert "金箍棒" in result.prompt
    assert "水墨画" in result.prompt
    assert "lora_stack" in result.params
    assert result.params.get("controlnet_type") == "depth"


def test_apply_pipeline_core(sun_wukong):
    ctx = cm.build_frame_context(
        prompt="test", character_ids=[sun_wukong.entity_id])
    result = cm.apply_pipeline(ctx, pipeline=cm.CORE_PIPELINE)
    assert "孙悟空" in result.prompt


def test_apply_pipeline_to_frames(sun_wukong, huaguo):
    frames = [
        cm.build_frame_context(
            prompt=f"frame {i}",
            frame_index=i,
            total_frames=3,
            character_ids=[sun_wukong.entity_id],
            scene_id=huaguo.entity_id,
        )
        for i in range(3)
    ]
    results = cm.apply_pipeline_to_frames(frames, pipeline=cm.CORE_PIPELINE)
    assert len(results) == 3
    for r in results:
        assert "孙悟空" in r.prompt
        assert "花果山" in r.prompt


# ── 边界情况 ────────────────────────────────────────────────────────

def test_empty_pipeline():
    ctx = cm.build_frame_context(prompt="test")
    result = cm.apply_pipeline(ctx, pipeline=[])
    assert result.prompt == "test"


def test_custom_pipeline():
    ctx = cm.build_frame_context(prompt="test", frame_index=0, total_frames=3)
    result = cm.apply_pipeline(ctx, pipeline=[cm.narrative_consistency])
    assert "[opening scene]" in result.prompt


def test_nonexistent_entity_graceful():
    ctx = cm.build_frame_context(
        prompt="test", character_ids=["nonexistent"])
    result = cm.character_consistency(ctx)
    # 不应该崩溃
    assert result.prompt == "test"
