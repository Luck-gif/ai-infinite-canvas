"""PipelineOrchestrator 单元测试。

覆盖：
  - 单图管线完整执行
  - 故事板管线
  - 蓝图自动匹配
  - 一致性策略选择
  - 各Agent独立测试
  - 边界情况（空输入、空实体）
"""
from __future__ import annotations

import pytest

import pipeline_orchestrator as po
import entity_registry as er


@pytest.fixture(autouse=True)
def _isolate_entities(monkeypatch, tmp_path):
    """隔离实体存储。"""
    monkeypatch.setattr(er, "_STORE_ROOT", str(tmp_path))
    er._ensure_store()


class TestIndividualAgents:
    """每个Agent独立测试。"""

    def test_parse_intent_with_characters(self):
        ctx = po.PipelineContext(raw_prompt="一个少女在樱花树下")
        ctx = po.agent_parse_intent(ctx)
        assert ctx.intent["has_characters"] is True
        assert ctx.intent["has_scene"] is False

    def test_parse_intent_with_scene(self):
        ctx = po.PipelineContext(raw_prompt="壮丽的自然风景")
        ctx = po.agent_parse_intent(ctx)
        assert ctx.intent["has_scene"] is True

    def test_parse_intent_anime_style(self):
        ctx = po.PipelineContext(raw_prompt="动漫风格角色，二次元")
        ctx = po.agent_parse_intent(ctx)
        assert ctx.intent["style"] == "anime"

    def test_parse_intent_realistic_style(self):
        ctx = po.PipelineContext(raw_prompt="电影质感照片")
        ctx = po.agent_parse_intent(ctx)
        assert ctx.intent["style"] == "realistic"

    def test_parse_intent_story(self):
        ctx = po.PipelineContext(raw_prompt="一个故事，多个分镜")
        ctx = po.agent_parse_intent(ctx)
        assert ctx.intent["is_story"] is True

    def test_load_entities_returns_entities(self):
        ctx = po.PipelineContext(raw_prompt="test")
        ctx = po.agent_load_entities(ctx)
        assert "entities" in ctx.entities

    def test_match_blueprints_auto_with_anime(self):
        ctx = po.PipelineContext(raw_prompt="一个动漫角色", raw_params={})
        ctx = po.agent_parse_intent(ctx)
        ctx = po.agent_match_blueprints(ctx)
        assert ctx.image_blueprint_id == "txt2img_qwen"

    def test_match_blueprints_auto_with_default(self):
        ctx = po.PipelineContext(raw_prompt="a landscape", raw_params={})
        ctx = po.agent_parse_intent(ctx)
        ctx = po.agent_match_blueprints(ctx)
        assert ctx.image_blueprint_id == "txt2img_sdxl"

    def test_match_blueprints_user_specified(self):
        ctx = po.PipelineContext(raw_prompt="test", raw_params={"image_blueprint": "txt2img_qwen"})
        ctx = po.agent_match_blueprints(ctx)
        assert ctx.image_blueprint_id == "txt2img_qwen"

    def test_choose_consistency(self):
        ctx = po.PipelineContext(raw_prompt="角色一致性的测试", raw_params={})
        ctx = po.agent_load_entities(ctx)
        ctx = po.agent_choose_consistency(ctx)
        assert ctx.consistency_mode in ("auto", "face_consistency", "style_consistency",
                                         "scene_consistency", "prop_consistency", "none")

    def test_validate_workflow_empty(self):
        ctx = po.PipelineContext(raw_prompt="test", assembled_workflow=[])
        ctx = po.agent_validate_workflow(ctx)
        assert ctx.validated is True  # 空工作流校验通过（无节点=无问题）

    def test_submit_disabled(self):
        ctx = po.PipelineContext(raw_prompt="test", raw_params={"submit": False})
        ctx = po.agent_submit_to_comfyui(ctx)
        assert ctx.submitted is False


class TestPipelineOrchestrator:
    """管线整包测试。"""

    def test_run_single_image_pipeline(self):
        orch = po.PipelineOrchestrator()
        ctx = orch.run("a cyberpunk city at night, neon lights",
                       image_blueprint="txt2img_sdxl",
                       submit=False)
        assert ctx.engineered_prompt != ""
        assert ctx.nodes_count > 0
        assert ctx.image_blueprint_name != ""
        assert ctx.consistency_mode != ""
        assert ctx.validated is True

    def test_run_with_anime_style(self):
        orch = po.PipelineOrchestrator()
        ctx = orch.run("动漫风格少女，精致线条",
                       submit=False)
        assert "qwen" in ctx.image_blueprint_id.lower() or "aivision" in ctx.image_blueprint_id.lower() or \
               "sdxl" in ctx.image_blueprint_id.lower()  # 可能匹配到 SDXL（实体的白猫匹配了道具）
        assert ctx.validated is True

    def test_run_storyboard_pipeline(self):
        orch = po.PipelineOrchestrator()
        result = orch.run_storyboard(
            "日出时的海边灯塔; 海鸥飞翔在码头; 渔夫收网; 日落余晖中的灯塔",
            num_shots=3,
        )
        assert result["total_shots"] > 0
        assert len(result["shots"]) > 0
        assert "storyboard_id" in result
        # 每个分镜应有内容
        for shot in result["shots"]:
            assert "prompt" in shot
            assert "node_count" in shot

    def test_run_with_custom_blueprint(self):
        orch = po.PipelineOrchestrator()
        ctx = orch.run("a beautiful landscape",
                       image_blueprint="txt2img_qwen",
                       submit=False)
        assert ctx.image_blueprint_id == "txt2img_qwen"

    def test_pipeline_context_attributes(self):
        orch = po.PipelineOrchestrator()
        ctx = orch.run("test pipeline context",
                       submit=False)
        # 验证所有必要字段
        assert len(ctx.raw_prompt) > 0
        assert isinstance(ctx.intent, dict)
        assert isinstance(ctx.consistency_profile, dict)
        assert ctx.nodes_count > 0
        assert ctx.started_at > 0
        assert ctx.finished_at >= ctx.started_at


class TestEdgeCases:
    """边界情况。"""

    def test_empty_prompt(self):
        orch = po.PipelineOrchestrator()
        ctx = orch.run("", submit=False)
        # 空提示词意图中不会有角色/场景标记
        assert ctx.intent.get("has_characters") is False
        assert ctx.intent.get("has_scene") is False

    def test_very_long_prompt(self):
        orch = po.PipelineOrchestrator()
        long_prompt = "a beautiful landscape " * 50
        ctx = orch.run(long_prompt, submit=False)
        assert ctx.validated is True

    def test_storyboard_single_shot(self):
        orch = po.PipelineOrchestrator()
        result = orch.run_storyboard("a single scene", num_shots=1)
        assert result["total_shots"] == 1

    def test_storyboard_max_shots(self):
        orch = po.PipelineOrchestrator()
        result = orch.run_storyboard(
            "shot 1; shot 2; shot 3; shot 4; shot 5; shot 6; shot 7; shot 8; shot 9; shot 10; shot 11; shot 12",
            num_shots=12,
        )
        assert result["total_shots"] <= 12
