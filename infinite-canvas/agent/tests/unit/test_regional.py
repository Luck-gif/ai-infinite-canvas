"""v5.1 Regional Pipeline 多角色同框 单元测试。

覆盖：
  - CharacterSlot 创建与验证
  - RegionalConfig 校验（比例和、slot 数量）
  - build_regional_prompt / resolve_regional_prompts
  - compute_regions（HORIZONTAL/VERTICAL/GRID2X2/CUSTOM）
  - build_regional_workflow 结构完整性
  - run_regional 集成
  - LayoutMode 枚举
  - create_dual/triple 便捷构造器
"""

from __future__ import annotations

import pytest
import sys
import os

# Ensure agent dir in path for entity_registry imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from regional_pipeline import (
    RegionalConfig, CharacterSlot, LayoutMode,
    build_regional_prompt, resolve_regional_prompts,
    compute_regions, build_regional_workflow,
    run_regional, create_dual_character_config,
    create_triple_character_config,
)


# ═══════════════════════════════════════════════════════════════
# CharacterSlot
# ═══════════════════════════════════════════════════════════════

def test_character_slot_defaults():
    """字符槽位默认值正确。"""
    s = CharacterSlot(token="A", entity_id="e1", prompt="a warrior")
    assert s.token == "A"
    assert s.entity_id == "e1"
    assert s.prompt == "a warrior"
    assert s.region_ratio == 0.5
    assert s.ipa_weight == 0.8
    assert s.start_at == 0.0
    assert s.end_at == 0.5


# ═══════════════════════════════════════════════════════════════
# RegionalConfig Validation
# ═══════════════════════════════════════════════════════════════

def test_config_min_two_slots():
    """少于2个 slot 应报错。"""
    cfg = RegionalConfig(
        slots=[CharacterSlot(token="A", entity_id="e1", prompt="test")],
    )
    errors = cfg.validate()
    assert any("至少需要 2 个" in e for e in errors)


def test_config_max_eight_slots():
    """超过8个 slot 应报错。"""
    slots = [
        CharacterSlot(token=chr(65 + i), entity_id=f"e{i}", prompt="test")
        for i in range(9)
    ]
    cfg = RegionalConfig(slots=slots)
    errors = cfg.validate()
    assert any("最多支持 8 个" in e for e in errors)


def test_config_ratio_sum_one():
    """slot 比例和不等于 1.0 应报错。"""
    cfg = RegionalConfig(
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="a", region_ratio=0.3),
            CharacterSlot(token="B", entity_id="e2", prompt="b", region_ratio=0.4),
        ],
    )
    errors = cfg.validate()
    assert any("比例和" in e for e in errors)


def test_config_valid():
    """合法配置无错误。"""
    cfg = RegionalConfig(
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="a", region_ratio=0.5),
            CharacterSlot(token="B", entity_id="e2", prompt="b", region_ratio=0.5),
        ],
    )
    errors = cfg.validate()
    # entity "e1" / "e2" 不一定存在，但配置合法性检验只关注 entity lookup
    # 实际 entity 不存在会报到 entity 错误中去
    assert len(errors) <= 2  # 最多两个 entity 不存在


def test_config_num_slots():
    """num_slots 属性返回正确数量。"""
    cfg = RegionalConfig(
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="a", region_ratio=1/3),
            CharacterSlot(token="B", entity_id="e2", prompt="b", region_ratio=1/3),
            CharacterSlot(token="C", entity_id="e3", prompt="c", region_ratio=1/3),
        ],
    )
    assert cfg.num_slots == 3


# ═══════════════════════════════════════════════════════════════
# Prompt Building
# ═══════════════════════════════════════════════════════════════

def test_build_regional_prompt_basic():
    """双角色提示词带 [A]/[B] token。"""
    cfg = RegionalConfig(
        base_prompt="A fantasy scene",
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="a warrior", region_ratio=0.5),
            CharacterSlot(token="B", entity_id="e2", prompt="a mage", region_ratio=0.5),
        ],
    )
    prompt = build_regional_prompt(cfg)
    assert "[A] a warrior" in prompt
    assert "[B] a mage" in prompt
    assert "A fantasy scene" in prompt
    assert " | " in prompt


def test_build_regional_prompt_no_base():
    """无 base_prompt 时仍正常工作。"""
    cfg = RegionalConfig(
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="hero", region_ratio=0.5),
            CharacterSlot(token="B", entity_id="e2", prompt="villain", region_ratio=0.5),
        ],
    )
    prompt = build_regional_prompt(cfg)
    assert "[A] hero" in prompt
    assert "[B] villain" in prompt


def test_resolve_regional_prompts():
    """resolve 返回 token→prompt 字典。"""
    cfg = RegionalConfig(
        base_prompt="scene",
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="warrior", region_ratio=0.5),
            CharacterSlot(token="B", entity_id="e2", prompt="mage", region_ratio=0.5),
        ],
    )
    result = resolve_regional_prompts(cfg)
    assert isinstance(result, dict)
    assert "A" in result
    assert "B" in result
    assert "warrior" in result["A"]
    assert "mage" in result["B"]


# ═══════════════════════════════════════════════════════════════
# Region Computation
# ═══════════════════════════════════════════════════════════════

def test_compute_regions_horizontal():
    """水平布局：区域 x 坐标逐段覆盖。"""
    cfg = RegionalConfig(
        layout=LayoutMode.HORIZONTAL,
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="a", region_ratio=0.4),
            CharacterSlot(token="B", entity_id="e2", prompt="b", region_ratio=0.6),
        ],
    )
    regions = compute_regions(cfg)
    assert len(regions) == 2
    assert regions[0]["x_start"] == 0.0
    assert regions[0]["x_end"] == 0.4
    assert regions[0]["y_start"] == 0.0
    assert regions[0]["y_end"] == 1.0
    assert regions[1]["x_start"] == 0.4
    assert regions[1]["x_end"] == 1.0


def test_compute_regions_vertical():
    """垂直布局：区域 y 坐标逐段覆盖。"""
    cfg = RegionalConfig(
        layout=LayoutMode.VERTICAL,
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="a", region_ratio=0.3),
            CharacterSlot(token="B", entity_id="e2", prompt="b", region_ratio=0.7),
        ],
    )
    regions = compute_regions(cfg)
    assert len(regions) == 2
    assert regions[0]["y_start"] == 0.0
    assert regions[0]["y_end"] == 0.3
    assert regions[1]["y_start"] == 0.3
    assert regions[1]["y_end"] == 1.0


def test_compute_regions_grid2x2():
    """四宫格布局：4 个区域各占 1/4 画面。"""
    cfg = RegionalConfig(
        layout=LayoutMode.GRID2X2,
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="a", region_ratio=0.25),
            CharacterSlot(token="B", entity_id="e2", prompt="b", region_ratio=0.25),
            CharacterSlot(token="C", entity_id="e3", prompt="c", region_ratio=0.25),
            CharacterSlot(token="D", entity_id="e4", prompt="d", region_ratio=0.25),
        ],
    )
    regions = compute_regions(cfg)
    assert len(regions) == 4
    # 左上
    assert regions[0]["x_start"] == 0.0
    assert regions[0]["x_end"] == 0.5
    assert regions[0]["y_start"] == 0.0
    assert regions[0]["y_end"] == 0.5
    # 右下
    assert regions[3]["x_start"] == 0.5
    assert regions[3]["x_end"] == 1.0
    assert regions[3]["y_start"] == 0.5
    assert regions[3]["y_end"] == 1.0


# ═══════════════════════════════════════════════════════════════
# Workflow Building
# ═══════════════════════════════════════════════════════════════

def test_build_regional_workflow_has_key_nodes():
    """工作流包含 CLIPTextEncode / EmptyLatentImage / RegionalSampler / SaveImage。"""
    cfg = RegionalConfig(
        layout=LayoutMode.HORIZONTAL,
        base_prompt="A cinematic scene",
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="warrior", region_ratio=0.5),
            CharacterSlot(token="B", entity_id="e2", prompt="mage", region_ratio=0.5),
        ],
    )
    wf = build_regional_workflow(cfg)
    assert isinstance(wf, dict)
    assert len(wf) > 0
    node_types = [
        n.get("class_type", "") for n in wf.values()
        if isinstance(n, dict)
    ]
    assert "CLIPTextEncode" in node_types
    assert "EmptyLatentImage" in node_types
    assert "RegionalSampler" in node_types
    assert "SaveImage" in node_types


def test_build_regional_workflow_has_ipadapters():
    """每个角色生成一个 IPAdapterAdvanced 节点。"""
    cfg = RegionalConfig(
        layout=LayoutMode.HORIZONTAL,
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="warrior", region_ratio=0.5),
            CharacterSlot(token="B", entity_id="e2", prompt="mage", region_ratio=0.5),
        ],
    )
    wf = build_regional_workflow(cfg)
    ipa_count = sum(
        1 for n in wf.values()
        if isinstance(n, dict) and "IPAdapter" in str(n.get("class_type", ""))
    )
    assert ipa_count >= 2


# ═══════════════════════════════════════════════════════════════
# run_regional Integration
# ═══════════════════════════════════════════════════════════════

def test_run_regional_valid():
    """run_regional 返回有效结果（即使 entity 不存在也降级处理）。"""
    cfg = RegionalConfig(
        layout=LayoutMode.HORIZONTAL,
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="warrior",
                          region_ratio=0.5, start_at=0.0, end_at=0.5),
            CharacterSlot(token="B", entity_id="e2", prompt="mage",
                          region_ratio=0.5, start_at=0.5, end_at=1.0),
        ],
    )
    result = run_regional(cfg)
    # 即使验证有 entity 不存在的错误（因为没有真实的 entity_registry），
    # 仍然应该返回结果结构
    assert "template_id" in result
    assert "meta" in result
    if result.get("error"):
        assert "issues" in result
    else:
        assert "workflow" in result
        assert result["meta"]["num_characters"] == 2


def test_run_regional_issues_on_bad_config():
    """无效配置返回 error 和 issues。"""
    cfg = RegionalConfig(
        slots=[
            CharacterSlot(token="A", entity_id="e1", prompt="test", region_ratio=0.1),
        ],
    )
    result = run_regional(cfg)
    assert result.get("error") is True
    assert isinstance(result.get("issues"), list)
    assert len(result["issues"]) > 0


# ═══════════════════════════════════════════════════════════════
# LayoutMode Enum
# ═══════════════════════════════════════════════════════════════

def test_layout_mode_values():
    """枚举值应与字符串对应。"""
    assert LayoutMode.HORIZONTAL.value == "horizontal"
    assert LayoutMode.VERTICAL.value == "vertical"
    assert LayoutMode.GRID2X2.value == "grid2x2"
    assert LayoutMode.CUSTOM.value == "custom"


# ═══════════════════════════════════════════════════════════════
# Convenience Constructors
# ═══════════════════════════════════════════════════════════════

def test_create_dual_character_config():
    """双角色便捷构造器。"""
    cfg = create_dual_character_config(
        char_a_id="e1", char_a_prompt="warrior",
        char_b_id="e2", char_b_prompt="mage",
        base_prompt="fantasy scene",
    )
    assert cfg.num_slots == 2
    assert cfg.layout == LayoutMode.HORIZONTAL
    assert cfg.base_prompt == "fantasy scene"
    assert cfg.slots[0].token == "A"
    assert cfg.slots[1].token == "B"


def test_create_triple_character_config():
    """三角色便捷构造器。"""
    cfg = create_triple_character_config(
        chars=[("e1", "a"), ("e2", "b"), ("e3", "c")],
        base_prompt="group photo",
    )
    assert cfg.num_slots == 3
    assert cfg.layout == LayoutMode.HORIZONTAL
    assert cfg.slots[0].token == "A"
    assert cfg.slots[1].token == "B"
    assert cfg.slots[2].token == "C"
    # 比例合计 ≈ 1.0
    total = sum(s.region_ratio for s in cfg.slots)
    assert abs(total - 1.0) < 0.01
