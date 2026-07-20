"""Text Production Pipeline 单元测试。"""
from __future__ import annotations

import pytest

import text_production as tp


class TestOutlineAgent:
    def test_template_expand_fantasy(self):
        agent = tp.OutlineAgent(backend="template")
        concept = tp.StoryConcept(
            title="测试故事",
            logline="一个少年在魔法森林里找到传说中的宝剑",
            genre="fantasy",
            tone="epic",
            setting="魔法森林",
        )
        beats = agent.generate(concept, num_beats=6)
        assert len(beats) == 6
        assert beats[0].name
        assert beats[0].description
        assert beats[0].emotion

    def test_template_expand_scifi(self):
        agent = tp.OutlineAgent()
        concept = tp.StoryConcept(
            title="星际",
            logline="一个宇航员在火星发现外星文明遗迹",
            genre="scifi",
            setting="火星",
        )
        beats = agent.generate(concept, num_beats=5)
        assert len(beats) == 5

    def test_template_expand_default(self):
        agent = tp.OutlineAgent()
        concept = tp.StoryConcept(
            title="日常",
            logline="一只猫的日常冒险",
            genre="slice_of_life",
        )
        beats = agent.generate(concept, num_beats=7)
        assert len(beats) == 7

    def test_keyword_extraction(self):
        agent = tp.OutlineAgent()
        concept = tp.StoryConcept(
            title="森林",
            logline="李白在森林里遇到了华山剑客张飞",
            setting="古老森林",
        )
        kw = agent._extract_keywords(concept)
        assert "location" in kw


class TestCharacterAgent:
    def test_generate_characters(self):
        agent = tp.CharacterAgent()
        concept = tp.StoryConcept(
            title="测试",
            logline="小明和小红一起探险",
        )
        outline = tp.OutlineAgent().generate(concept, num_beats=5)
        chars = agent.generate(concept, outline)
        assert len(chars) == 5
        assert chars[0].name
        assert chars[0].archetype
        assert chars[0].consistent_prompt

    def test_build_consistent_prompt(self):
        agent = tp.CharacterAgent()
        char = tp.CharacterCard(
            id="test", name="小明",
            appearance="红发，戴眼镜",
            personality="聪明好奇",
            archetype="hero",
        )
        prompt = agent._build_consistent_prompt(char)
        assert "小明" in prompt
        assert "红发" in prompt


class TestScriptAgent:
    def test_generate_scenes(self):
        agent = tp.ScriptAgent()
        concept = tp.StoryConcept(title="测试", logline="一个故事")
        beats = tp.OutlineAgent().generate(concept, num_beats=4)
        chars = tp.CharacterAgent().generate(concept, beats)
        scenes = agent.generate(beats, chars)
        assert len(scenes) > 0
        assert scenes[0].camera_direction
        assert scenes[0].lighting
        assert scenes[0].beat_id


class TestPromptAgent:
    def test_generate_prompts(self):
        agent = tp.PromptAgent()
        concept = tp.StoryConcept(title="测试", logline="一个故事")
        beats = tp.OutlineAgent().generate(concept, num_beats=3)
        chars = tp.CharacterAgent().generate(concept, beats)
        scenes = tp.ScriptAgent().generate(beats, chars)
        prompts = agent.generate(scenes, chars, style="anime")
        assert len(prompts) > 0
        assert prompts[0].english_prompt
        assert prompts[0].chinese_prompt
        assert prompts[0].negative
        assert prompts[0].style_tags


class TestStoryboardAgent:
    def test_generate_storyboard(self):
        agent = tp.StoryboardAgent()
        prompts = [
            tp.ImagePrompt(
                id="p0", index=0, scene_id="s0",
                english_prompt="a test image", chinese_prompt="测试图",
                style_tags="realistic", negative="blurry",
            ),
            tp.ImagePrompt(
                id="p1", index=1, scene_id="s1",
                english_prompt="another test", chinese_prompt="另一张",
                style_tags="realistic", negative="blurry",
            ),
        ]
        sb = agent.generate(prompts, title="测试")
        assert sb["total_shots"] == 2
        assert sb["shots"][0]["shot_index"] == 0
        assert "storyboard_id" in sb


class TestTextProductionPipeline:
    def test_full_pipeline(self):
        pipeline = tp.TextProductionPipeline()
        doc = pipeline.run(
            "火焰之心",
            "一个铁匠学徒在火山口发现了一把燃烧的锤子，从此踏上锻造传奇武器之旅",
            genre="fantasy",
            tone="epic",
            num_beats=5,
            style="realistic",
        )
        assert len(doc.beats) == 5
        assert len(doc.characters) == 5
        assert len(doc.scenes) > 0
        assert len(doc.prompts) > 0
        assert doc.metadata["pipeline_version"] == "4.53"
        assert doc.metadata["storyboard"]["total_shots"] > 0

    def test_pipeline_to_storyboard(self):
        pipeline = tp.TextProductionPipeline()
        sb = pipeline.run_to_storyboard(
            "赛博黎明",
            "一个黑客觉醒在数字深渊中",
            genre="scifi",
            num_beats=4,
        )
        assert "shots" in sb
        assert sb["total_shots"] > 0

    def test_production_to_entities(self):
        pipeline = tp.TextProductionPipeline()
        doc = pipeline.run("测试", "一个简单故事", num_beats=4)
        entities = tp.production_to_entities(doc)
        assert "entities" in entities
        assert len(entities["entities"]) > 0


class TestEdgeCases:
    def test_minimal_concept(self):
        pipeline = tp.TextProductionPipeline()
        doc = pipeline.run("A", "B", num_beats=3)
        assert len(doc.beats) == 3

    def test_max_beats(self):
        pipeline = tp.TextProductionPipeline()
        doc = pipeline.run("测试", "大故事", num_beats=10)
        # 模板节拍数有限，但应至少有 8 个（接近请求数）
        assert len(doc.beats) >= 8

    def test_japanese_anime_style(self):
        pipeline = tp.TextProductionPipeline()
        doc = pipeline.run(
            "樱花物语",
            "高校生の少女が桜の木の下で運命の出会いを果たす",
            genre="fantasy",
            style="anime",
            num_beats=5,
        )
        assert doc.prompts[0].style_tags
        assert "anime" in doc.prompts[0].style_tags
