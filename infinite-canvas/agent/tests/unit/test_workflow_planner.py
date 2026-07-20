"""工作流规划器（workflow_planner）单元测试。

覆盖：
  - 叙事结构推断
  - 帧数推断
  - 角色序列生成
  - 分镜计划生成
  - plan_to_frame_contexts 转换
  - 自动分镜（auto_plan_from_intent）
"""

from __future__ import annotations

import os
import pytest

import entity_registry as er
import consistency_manager as cm
import workflow_planner as wp


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
        name="孙悟空", alias="Sun Wukong",
        description="The Monkey King",
    )


@pytest.fixture
def huaguo():
    return er.create_entity(
        kind=er.EntityKind.SCENE,
        name="花果山", alias="Mount Huaguo",
        description="A lush paradise",
    )


@pytest.fixture
def base_intent():
    return {"action": "generate", "subject": "A hero's journey",
            "style": "epic", "params": {"frames": 3}}


# ── 结构推断 ────────────────────────────────────────────────────────

def test_infer_structure_single():
    intent = {"action": "generate", "params": {"frames": 1}}
    assert wp._infer_structure(intent) == wp.StoryStructure.SINGLE


def test_infer_structure_story():
    intent = {"action": "story", "params": {"frames": 3}}
    assert wp._infer_structure(intent) == wp.StoryStructure.THREE_ACT


def test_infer_structure_movie():
    intent = {"action": "movie", "params": {"frames": 5}}
    assert wp._infer_structure(intent) == wp.StoryStructure.FIVE_ACT


def test_infer_structure_default():
    # unknown action + no frames → single（因为 params 无 frames）
    intent = {"action": "unknown", "params": {}}
    assert wp._infer_structure(intent) == wp.StoryStructure.SINGLE

def test_infer_structure_linear():
    # generate action with 3 frames → linear（不是 story/narrative/sequence）
    intent = {"action": "generate", "params": {"frames": 3}}
    assert wp._infer_structure(intent) == wp.StoryStructure.LINEAR


# ── 帧数推断 ────────────────────────────────────────────────────────

def test_infer_frame_count_explicit():
    intent = {"params": {"frames": 10}}
    assert wp._infer_frame_count(intent, wp.StoryStructure.LINEAR) == 10


def test_infer_frame_count_default_three_act():
    assert wp._infer_frame_count({}, wp.StoryStructure.THREE_ACT) == 3


def test_infer_frame_count_default_five_act():
    assert wp._infer_frame_count({}, wp.StoryStructure.FIVE_ACT) == 5


def test_infer_frame_count_default_linear():
    assert wp._infer_frame_count({}, wp.StoryStructure.LINEAR) == 4


# ── 角色序列生成 ────────────────────────────────────────────────────

def test_generate_role_sequence_three_act():
    seq = wp._generate_role_sequence(wp.StoryStructure.THREE_ACT, 3)
    assert seq == [wp.FrameRole.OPENING, wp.FrameRole.CONFLICT,
                   wp.FrameRole.RESOLUTION]


def test_generate_role_sequence_single():
    seq = wp._generate_role_sequence(wp.StoryStructure.SINGLE, 1)
    assert seq == [wp.FrameRole.OPENING]


def test_generate_role_sequence_linear():
    seq = wp._generate_role_sequence(wp.StoryStructure.LINEAR, 5)
    assert len(seq) == 5
    assert seq[0] == wp.FrameRole.OPENING
    assert seq[-1] == wp.FrameRole.RESOLUTION


def test_generate_role_sequence_expanded():
    # 3-act 扩展到 7 帧
    seq = wp._generate_role_sequence(wp.StoryStructure.THREE_ACT, 7)
    assert len(seq) == 7
    # 应该包含核心角色
    roles_set = set(seq)
    assert wp.FrameRole.OPENING in roles_set
    assert wp.FrameRole.CONFLICT in roles_set
    assert wp.FrameRole.RESOLUTION in roles_set


# ── 分镜计划生成 ────────────────────────────────────────────────────

def test_plan_storyboard_basic(base_intent):
    plan = wp.plan_storyboard(base_intent)
    # generate action with 3 frames → LINEAR
    assert plan.story_structure == wp.StoryStructure.LINEAR
    assert plan.total_frames == 3
    assert len(plan.frames) == 3
    assert plan.plan_id


def test_plan_storyboard_with_entities(base_intent, sun_wukong, huaguo):
    plan = wp.plan_storyboard(
        base_intent,
        character_ids=[sun_wukong.entity_id],
        scene_id=huaguo.entity_id,
        style_id=None,
    )
    assert len(plan.frames) == 3
    for fp in plan.frames:
        assert sun_wukong.entity_id in fp.character_ids
        assert fp.scene_id == huaguo.entity_id


def test_plan_storyboard_single_frame():
    intent = {"action": "generate", "params": {"frames": 1}}
    plan = wp.plan_storyboard(intent)
    assert plan.total_frames == 1
    assert plan.frames[0].frame_role == wp.FrameRole.OPENING


def test_plan_storyboard_explicit_structure():
    intent = {"action": "story", "params": {}}
    plan = wp.plan_storyboard(intent, structure=wp.StoryStructure.FIVE_ACT)
    assert plan.story_structure == wp.StoryStructure.FIVE_ACT
    assert plan.total_frames == 5


def test_plan_storyboard_with_description():
    intent = {"action": "story", "params": {"frames": 3}}
    plan = wp.plan_storyboard(
        intent,
        description="A hero begins the journey. He faces a great challenge. "
                     "He emerges victorious.",
    )
    assert len(plan.frames) == 3
    for fp in plan.frames:
        assert fp.prompt_template  # 每帧都有描述


# ── plan_to_frame_contexts ──────────────────────────────────────────

def test_plan_to_frame_contexts(base_intent, sun_wukong):
    plan = wp.plan_storyboard(
        base_intent, character_ids=[sun_wukong.entity_id])
    ctxs = wp.plan_to_frame_contexts(plan)
    assert len(ctxs) == 3
    for ctx in ctxs:
        assert sun_wukong.entity_id in ctx.character_ids
        assert ctx.total_frames == 3


def test_plan_to_frame_contexts_with_pipeline(base_intent, sun_wukong):
    plan = wp.plan_storyboard(
        base_intent, character_ids=[sun_wukong.entity_id])
    ctxs = wp.plan_to_frame_contexts(plan, pipeline=cm.CORE_PIPELINE)
    assert len(ctxs) == 3
    for ctx in ctxs:
        assert "孙悟空" in ctx.prompt  # 角色一致性已注入


# ── 自动分镜 ────────────────────────────────────────────────────────

def test_auto_plan_from_intent(base_intent, sun_wukong, huaguo):
    plan = wp.auto_plan_from_intent(
        base_intent,
        entity_ids={
            "character": [sun_wukong.entity_id],
            "scene": huaguo.entity_id,
        },
    )
    assert plan.total_frames == 3
    for fp in plan.frames:
        assert sun_wukong.entity_id in fp.character_ids
        assert fp.scene_id == huaguo.entity_id


def test_auto_plan_from_intent_no_entities(base_intent):
    plan = wp.auto_plan_from_intent(base_intent)
    assert plan.total_frames == 3
    for fp in plan.frames:
        assert fp.character_ids == []


# ── FramePlan 默认值 ────────────────────────────────────────────────

def test_frame_plan_defaults():
    fp = wp.FramePlan(
        frame_index=0,
        frame_role=wp.FrameRole.OPENING,
        prompt_template="test prompt",
    )
    assert fp.duration_sec == 1.0
    assert fp.character_ids == []
    assert fp.scene_id is None
    assert fp.prop_ids == []


# ── 边界情况 ────────────────────────────────────────────────────────

def test_plan_storyboard_zero_frames():
    intent = {"action": "generate", "params": {"frames": 0}}
    # 应该至少生成 1 帧
    plan = wp.plan_storyboard(intent)
    assert plan.total_frames >= 1


def test_empty_description():
    intent = {"action": "story", "params": {"frames": 2}}
    plan = wp.plan_storyboard(intent, description="")
    assert len(plan.frames) == 2
    for fp in plan.frames:
        assert fp.prompt_template  # 模板回退


def test_generate_role_sequence_small_n():
    # n_frames=1 不应该崩溃
    seq = wp._generate_role_sequence(wp.StoryStructure.THREE_ACT, 1)
    assert len(seq) == 1
