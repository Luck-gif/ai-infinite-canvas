"""无限画布 v4.53 · 多Agent写作管线（Text Production Pipeline）。

§14.1 核心职责：
    1. Outline Agent     → 故事概念 → 节拍/场景拆解
    2. Character Agent   → 场景中提取角色 → 角色卡
    3. Script Agent      → 节拍 → 场景剧本（含镜头方向）
    4. Prompt Agent      → 剧本 → SD/Flux 图像生成提示词列表
    5. Storyboard Agent  → 提示词列表 → 分镜结构

§14.2 设计纪律：
    - 每个Agent是可替换的独立模块（支持LLM/规则/模板三种后端）
    - 所有输出均为结构化 JSON（便于前端渲染）
    - 与 entity_registry / consistency_manager 无缝对接
    - 输出可直接馈入 PipelineOrchestrator 生成图像
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import sys
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)


# ── 数据模型 ─────────────────────────────────────────────────────────

@dataclass
class StoryConcept:
    """故事概念（用户高层输入）。"""
    title: str = ""
    logline: str = ""          # 一句话概要
    genre: str = ""            # 类型：fantasy/scifi/romance/horror/...
    tone: str = ""             # 调性：dark/light/epic/whimsical/...
    setting: str = ""          # 世界设定
    key_elements: list[str] = field(default_factory=list)


@dataclass
class Beat:
    """故事节拍。"""
    id: str = ""
    index: int = 0
    name: str = ""             # 节拍名称（如 "开场 hook" / "转折点"）
    description: str = ""      # 发生了什么
    emotion: str = ""          # 情绪氛围
    location: str = ""         # 场景地点


@dataclass
class CharacterCard:
    """角色卡。"""
    id: str = ""
    name: str = ""
    archetype: str = ""        # 原型：hero/mentor/shadow/trickster/...
    appearance: str = ""       # 外貌描述
    personality: str = ""      # 性格特质
    motivation: str = ""       # 动机/目标
    relationship: str = ""     # 与其他角色关系
    consistent_prompt: str = ""  # 角色一致性提示词（用于 IPAdapter）


@dataclass
class SceneScript:
    """场景剧本。"""
    id: str = ""
    scene_index: int = 0
    beat_id: str = ""
    location: str = ""
    time_of_day: str = ""      # dawn/morning/noon/afternoon/dusk/night
    description: str = ""      # 叙事描述
    camera_direction: str = "" # 镜头方向（广角/特写/跟拍/顶拍...）
    lighting: str = ""         # 灯光设定
    characters_present: list[str] = field(default_factory=list)
    dialogue_hints: str = ""   # 对话要点（非完整对话）


@dataclass
class ImagePrompt:
    """图像生成提示词（直接可送入 SD/Flux）。"""
    id: str = ""
    index: int = 0
    scene_id: str = ""
    shot_type: str = ""        # wide/medium/closeup/extreme_closeup
    camera_angle: str = ""     # eye_level/low_angle/high_angle/dutch
    english_prompt: str = ""   # 英文提示词（用于 SD/Flux）
    chinese_prompt: str = ""   # 中文提示词（用于 Qwen-Image 2.0）
    style_tags: str = ""       # 风格标签
    negative: str = ""         # 负向提示词
    consistency_hint: str = "" # 一致性提示（引用角色/场景 ID）


@dataclass
class ProductionDoc:
    """完整的制作文档。"""
    concept: StoryConcept = field(default_factory=StoryConcept)
    beats: list[Beat] = field(default_factory=list)
    characters: list[CharacterCard] = field(default_factory=list)
    scenes: list[SceneScript] = field(default_factory=list)
    prompts: list[ImagePrompt] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Agent 1: Outline ─────────────────────────────────────────────────

# 经典节拍模板（Blake Snyder 节拍表精简版）
BEAT_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "fantasy": [
        {"name": "平凡世界", "emotion": "安宁", "desc_tmpl": "{world}的日常平静——{hero}在{location}过着普通生活。"},
        {"name": "冒险召唤", "emotion": "好奇/恐惧", "desc_tmpl": "一个神秘事件打破了平静——{incident}。"},
        {"name": "拒绝召唤", "emotion": "犹豫", "desc_tmpl": "{hero}不愿离开舒适圈，但征兆越来越强。"},
        {"name": "导师指引", "emotion": "希望", "desc_tmpl": "一位智者出现，揭示了{quest}的真相。"},
        {"name": "跨越门槛", "emotion": "激动", "desc_tmpl": "{hero}踏上旅程，进入一个全新的世界。"},
        {"name": "试炼之路", "emotion": "紧张", "desc_tmpl": "遭遇第一个真正的挑战——{obstacle}。"},
        {"name": "接近核心", "emotion": "悬疑", "desc_tmpl": "越来越接近{climax_location}，危险加剧。"},
        {"name": "最大考验", "emotion": "巅峰", "desc_tmpl": "最终对决——{climax}。"},
        {"name": "满载而归", "emotion": "欣慰", "desc_tmpl": "{hero}获得{reward}，返回家园。"},
        {"name": "新常态", "emotion": "平和", "desc_tmpl": "世界恢复平衡，但已不同往昔。"},
    ],
    "scifi": [
        {"name": "技术奇点", "emotion": "震撼", "desc_tmpl": "一项颠覆性技术{tech}改变了世界。"},
        {"name": "人性考验", "emotion": "冲突", "desc_tmpl": "在新技术面前，人类面临{choice}的抉择。"},
        {"name": "暗流涌动", "emotion": "悬疑", "desc_tmpl": "一个隐藏的真相逐渐浮出水面——{secret}。"},
        {"name": "分崩离析", "emotion": "危机", "desc_tmpl": "旧秩序崩塌，{conflict}爆发。"},
        {"name": "绝地反击", "emotion": "决心", "desc_tmpl": "{hero}找到突破口，开始反击。"},
        {"name": "终极对决", "emotion": "巅峰", "desc_tmpl": "人与技术的最终较量——{showdown}。"},
        {"name": "新生", "emotion": "希望", "desc_tmpl": "废墟上诞生了新的可能性。"},
    ],
    "default": [
        {"name": "开场 Hook", "emotion": "好奇", "desc_tmpl": "一个吸引人的开场——{hook}"},
        {"name": "激励事件", "emotion": "冲突", "desc_tmpl": "改变一切的事件——{incident}"},
        {"name": "第一幕转折", "emotion": "决心", "desc_tmpl": "{hero}做出决定性的选择。"},
        {"name": "中点转折", "emotion": "转折", "desc_tmpl": "局势发生逆转——{twist}"},
        {"name": "一败涂地", "emotion": "绝望", "desc_tmpl": "一切看似失败——{low_point}"},
        {"name": "灵魂黑夜", "emotion": "反思", "desc_tmpl": "{hero}在黑暗中找到内心的力量。"},
        {"name": "第三幕转折", "emotion": "觉醒", "desc_tmpl": "重获希望，制定最后的计划。"},
        {"name": "高潮", "emotion": "巅峰", "desc_tmpl": "最终面对{antagonist}，{resolution}"},
        {"name": "终场", "emotion": "释然", "desc_tmpl": "结局——{ending}"},
    ],
}


class OutlineAgent:
    """Agent 1: 故事概念 → 节拍列表。

    支持三种后端（LLM后端留空接口供后续接入）：
    - template: 基于节拍模板 + 概念关键词填充（当前实现）
    - llm_openai: 调用 OpenAI API
    - llm_local: 调用本地 LLM
    """

    def __init__(self, backend: str = "template"):
        self.backend = backend

    def generate(self, concept: StoryConcept, num_beats: int = 8) -> list[Beat]:
        """生成故事节拍。"""
        if self.backend == "template":
            return self._template_expand(concept, num_beats)
        elif self.backend == "llm_openai":
            return self._llm_openai(concept, num_beats)
        else:
            return self._template_expand(concept, num_beats)

    def _template_expand(self, concept: StoryConcept, num_beats: int) -> list[Beat]:
        """模板扩展：基于节拍模板 + 概念关键词填充。"""
        # 选择匹配的模板
        genre_templates = BEAT_TEMPLATES.get(concept.genre, BEAT_TEMPLATES["default"])
        templates = genre_templates[:num_beats]

        # 提取关键词用于填充
        keywords = self._extract_keywords(concept)
        hero_name = self._find_hero_name(concept)

        beats: list[Beat] = []
        for i, tmpl in enumerate(templates):
            desc = tmpl["desc_tmpl"]
            # 替换模板变量
            for key, val in keywords.items():
                desc = desc.replace(f"{{{key}}}", val)

            beats.append(Beat(
                id=f"beat_{i}",
                index=i,
                name=tmpl["name"],
                description=desc,
                emotion=tmpl["emotion"],
                location=keywords.get("location", "未知地点"),
            ))

        return beats

    def _extract_keywords(self, concept: StoryConcept) -> dict[str, str]:
        """从概念中提取关键词。"""
        text = concept.logline.lower()

        # 角色名提取策略
        hero = "主角"
        antagonist = "对手"
        for word in concept.logline.split():
            if len(word) > 2 and word[0].isupper():
                if hero == "主角":
                    hero = word
                else:
                    antagonist = word

        # 地点提取
        location_words = ["城市", "森林", "宇宙", "城堡", "村庄", "学院", "实验室",
                          "海底", "沙漠", "雪山", "地下城", "城市", "宫殿", "塔楼"]
        location = concept.setting or concept.logline[:20]
        for w in location_words:
            if w in concept.logline:
                location = w
                break

        return {
            "hero": hero,
            "antagonist": antagonist,
            "world": concept.setting or "这个世界",
            "location": location,
            "incident": "一件改变一切的事",
            "quest": "重要使命",
            "obstacle": "巨大的障碍",
            "climax_location": "关键地点",
            "climax": "最终对决",
            "reward": "珍贵的回报",
            "hook": concept.logline[:30],
            "twist": "出人意料的真相",
            "low_point": "最黑暗的时刻",
            "resolution": "令人满意的结局",
            "ending": "新的开始",
            "tech": "强大技术",
            "choice": "艰难",
            "secret": "被隐藏的真相",
            "conflict": "冲突爆发",
            "showdown": "最终较量",
        }

    def _find_hero_name(self, concept: StoryConcept) -> str:
        """尝试从概念中提取主角名。"""
        for word in concept.logline.replace("的", " ").split():
            w = word.strip("，。；：""！？")
            if len(w) >= 2 and len(w) <= 4 and not re.search(r'[a-zA-Z0-9]', w):
                return w
        return "主人公"

    def _llm_openai(self, concept: StoryConcept, num_beats: int) -> list[Beat]:
        """LLM后端占位（需 OPENAI_API_KEY）。"""
        raise NotImplementedError("LLM 后端需配置 API Key（后续集成）")


# ── Agent 2: Character ──────────────────────────────────────────────

# 角色原型 → 默认外貌模板
ARCHETYPE_TEMPLATES: dict[str, dict[str, str]] = {
    "hero": {"appearance": "坚定目光，挺拔身姿，简朴但整洁的着装",
             "personality": "勇敢、正直、偶尔犹豫",
             "motivation": "保护所爱之人/世界"},
    "mentor": {"appearance": "智者风范，深邃眼眸，斑白须发",
               "personality": "睿智、耐心、略带神秘",
               "motivation": "引导年轻一代成长"},
    "shadow": {"appearance": "黑暗气息，锐利轮廓，深色装束",
               "personality": "冷酷、强大、有隐藏的脆弱",
               "motivation": "消弭内心的痛苦"},
    "trickster": {"appearance": "灵动机敏，狡黠微笑，飘逸服装",
                  "personality": "机智、不羁、内心善良",
                  "motivation": "追求自由与乐趣"},
    "herald": {"appearance": "神秘来客，奇异装束",
               "personality": "平静、神秘的预言者",
               "motivation": "传递重要信息"},
    "ally": {"appearance": "友善亲和，日常装束",
             "personality": "忠诚、支持、有独特技能",
             "motivation": "帮助朋友达成目标"},
    "antagonist": {"appearance": "威严压迫，精工装束，凌人目光",
                   "personality": "野心、执念、潜在悲剧性",
                   "motivation": "实现扭曲的正义"},
}


class CharacterAgent:
    """Agent 2: 从节拍/概念中提取角色 → 角色卡。"""

    def __init__(self, backend: str = "template"):
        self.backend = backend

    def generate(self, concept: StoryConcept, beats: list[Beat]) -> list[CharacterCard]:
        """从故事概念和节拍中提取角色。"""
        text = concept.logline + " " + " ".join(b.description for b in beats)

        characters: list[CharacterCard] = []

        # 按原型生成角色
        archetypes = ["hero", "mentor", "shadow", "trickster", "ally"]
        names = self._extract_names(concept, len(archetypes))

        for i, arch in enumerate(archetypes):
            tmpl = ARCHETYPE_TEMPLATES.get(arch, ARCHETYPE_TEMPLATES["hero"])
            name = names[i] if i < len(names) else f"角色{i+1}"
            char = CharacterCard(
                id=f"char_{i}",
                name=name,
                archetype=arch,
                appearance=tmpl["appearance"],
                personality=tmpl["personality"],
                motivation=tmpl["motivation"],
                relationship=f"与{names[0] if names else '主人公'}的关系",
            )
            char.consistent_prompt = self._build_consistent_prompt(char)
            characters.append(char)

        return characters

    def _extract_names(self, concept: StoryConcept, count: int) -> list[str]:
        """从概念中提取角色名。"""
        names: list[str] = []
        # 简单策略：中文2-4字词语
        for word in concept.logline.replace("的", " ").split():
            w = word.strip("，。；：""！？、")
            if len(w) >= 2 and len(w) <= 4 and not re.search(r'[a-zA-Z0-9]', w):
                if w not in names:
                    names.append(w)
        return names[:count]

    def _build_consistent_prompt(self, char: CharacterCard) -> str:
        """生成角色一致性提示词（用于 IPAdapter 或 prompt 注入）。"""
        return f"{char.name}: {char.appearance}, {char.personality}"


# ── Agent 3: Script ─────────────────────────────────────────────────

class ScriptAgent:
    """Agent 3: 节拍 → 场景剧本（含镜头方向、灯光、角色）。"""

    SHOT_TYPES = ["全景 establishing shot", "中景 medium shot", "近景 closeup",
                  "特写 extreme closeup", "过肩 over-the-shoulder"]
    LIGHTING = ["柔和自然光 soft natural lighting", "戏剧性侧光 dramatic side lighting",
                "逆光 silhouette backlight", "暖金色黄昏 warm golden hour",
                "冷蓝月光 cool blue moonlight", "霓虹赛博 neon cyberpunk"]

    def generate(self, beats: list[Beat], characters: list[CharacterCard]) -> list[SceneScript]:
        """将节拍展开为场景剧本。"""
        scenes: list[SceneScript] = []
        char_names = [c.name for c in characters]

        for i, beat in enumerate(beats):
            # 每个节拍 → 1-2 个场景
            for si in range(1 if i < len(beats) - 1 else 2):
                shot_idx = (i + si) % len(self.SHOT_TYPES)
                light_idx = (i + si) % len(self.LIGHTING)

                scene = SceneScript(
                    id=f"scene_{i}_{si}",
                    scene_index=len(scenes),
                    beat_id=beat.id,
                    location=beat.location,
                    time_of_day=["白天", "黄昏", "夜晚", "黎明"][i % 4] if si == 0 else "夜晚",
                    description=f"{beat.description}\n\n情绪基调：{beat.emotion}。",
                    camera_direction=self.SHOT_TYPES[shot_idx],
                    lighting=self.LIGHTING[light_idx],
                    characters_present=char_names[:min(3, len(char_names))],
                    dialogue_hints=f"角色们讨论{beat.name}的关键转折。",
                )
                scenes.append(scene)

        return scenes


# ── Agent 4: Prompt ─────────────────────────────────────────────────

class PromptAgent:
    """Agent 4: 场景剧本 → 图像生成提示词列表。"""

    QUALITY_TAGS = "masterpiece, best quality, highly detailed, sharp focus"
    NEGATIVE_BASE = "ugly, blurry, low quality, deformed, bad anatomy, watermark, text"

    STYLE_PRESETS: dict[str, str] = {
        "fantasy": "fantasy art, epic fantasy illustration, trending on ArtStation",
        "scifi": "sci-fi, cyberpunk, futuristic, trending on CGSociety",
        "horror": "dark horror, atmospheric, gothic, trending on DeviantArt",
        "anime": "anime style, studio ghibli, makoto shinkai, vibrant",
        "realistic": "photorealistic, 8k, hyperdetailed, cinematic lighting",
        "painting": "oil painting, classical art, rembrandt lighting",
    }

    def generate(
        self,
        scenes: list[SceneScript],
        characters: list[CharacterCard],
        style: str = "realistic",
    ) -> list[ImagePrompt]:
        """为每个场景生成英文+中文提示词。"""
        style_tags = self.STYLE_PRESETS.get(style, self.STYLE_PRESETS["realistic"])
        prompts: list[ImagePrompt] = []

        for i, scene in enumerate(scenes):
            # 核心描述
            core = f"{scene.description.split('。')[0]}"
            camera = scene.camera_direction
            lighting = scene.lighting

            # 角色引用
            char_refs = ", ".join(scene.characters_present[:2])

            # 英文提示词
            en = f"{core}, {char_refs}, {camera}, {lighting}, {style_tags}, {self.QUALITY_TAGS}"

            # 中文提示词
            cn = f"{core}，{char_refs}，{camera}，{lighting}，{style}风格，大师级作品"

            # 一致性提示
            consistency = ""
            if characters:
                c = characters[0]
                consistency = f"角色{c.name}: {c.appearance}"

            prompts.append(ImagePrompt(
                id=f"prompt_{i}",
                index=i,
                scene_id=scene.id,
                shot_type=camera.split(" ")[0],
                camera_angle="eye_level",
                english_prompt=en,
                chinese_prompt=cn,
                style_tags=style_tags,
                negative=self.NEGATIVE_BASE,
                consistency_hint=consistency,
            ))

        return prompts


# ── Agent 5: Storyboard ─────────────────────────────────────────────

class StoryboardAgent:
    """Agent 5: 提示词列表 → 分镜结构（可直接送入 /api/storyboard/plan）。"""

    def generate(self, prompts: list[ImagePrompt], title: str = "") -> dict[str, Any]:
        """生成结构化分镜。"""
        shots = []
        for i, p in enumerate(prompts):
            shots.append({
                "shot_index": i,
                "shot_id": f"shot_{i:04d}",
                "prompt": p.english_prompt,
                "chinese_prompt": p.chinese_prompt,
                "scene_id": p.scene_id,
                "shot_type": p.shot_type,
                "camera_angle": p.camera_angle,
                "consistency_hint": p.consistency_hint,
                "negative": p.negative,
            })

        return {
            "storyboard_id": f"sb_prod_{int(time.time())}",
            "title": title,
            "total_shots": len(shots),
            "shots": shots,
            "style": "cinematic",
        }


# ── 管线编排器 ────────────────────────────────────────────────────────

class TextProductionPipeline:
    """多Agent写作管线编排器。

    完整流程：概念 → 大纲 → 角色 → 剧本 → 提示词 → 分镜

    用法：
        pipeline = TextProductionPipeline()
        doc = pipeline.run("奇幻魔法学院", "一个普通女孩发现自己是魔法师", genre="fantasy")
        print(doc.prompts[0].english_prompt)
    """

    def __init__(self, llm_backend: str = "template"):
        self.outline_agent = OutlineAgent(backend=llm_backend)
        self.character_agent = CharacterAgent(backend=llm_backend)
        self.script_agent = ScriptAgent()
        self.prompt_agent = PromptAgent()
        self.storyboard_agent = StoryboardAgent()

    def run(
        self,
        title: str,
        logline: str,
        genre: str = "default",
        tone: str = "epic",
        setting: str = "",
        num_beats: int = 8,
        style: str = "realistic",
    ) -> ProductionDoc:
        """运行完整管线。"""
        t0 = time.time()

        # Step 1: 构建概念
        concept = StoryConcept(
            title=title,
            logline=logline,
            genre=genre,
            tone=tone,
            setting=setting or f"{genre}世界",
        )

        # Step 2-6: 顺序执行各Agent
        beats = self.outline_agent.generate(concept, num_beats)
        characters = self.character_agent.generate(concept, beats)
        scenes = self.script_agent.generate(beats, characters)
        prompts = self.prompt_agent.generate(scenes, characters, style)
        storyboard = self.storyboard_agent.generate(prompts, title)

        elapsed = (time.time() - t0) * 1000

        return ProductionDoc(
            concept=concept,
            beats=beats,
            characters=characters,
            scenes=scenes,
            prompts=prompts,
            metadata={
                "elapsed_ms": elapsed,
                "pipeline_version": "4.53",
                "total_beats": len(beats),
                "total_characters": len(characters),
                "total_scenes": len(scenes),
                "total_prompts": len(prompts),
                "storyboard": storyboard,
            },
        )

    def run_to_storyboard(self, title: str, logline: str, **kwargs) -> dict[str, Any]:
        """便捷函数：直接生成分镜结构。"""
        doc = self.run(title, logline, **kwargs)
        return doc.metadata.get("storyboard", {})


# ── 工具函数 ─────────────────────────────────────────────────────────

def production_to_entities(doc: ProductionDoc) -> dict[str, Any]:
    """将 ProductionDoc 中的角色转为实体注册表格式。"""
    entities: dict[str, dict[str, Any]] = {}
    for c in doc.characters:
        entities[c.id] = {
            "name": c.name,
            "kind": "character",
            "description": f"{c.archetype}: {c.appearance}. {c.personality}",
            "consistent_prompt": c.consistent_prompt,
            "archetype": c.archetype,
        }
    return {"entities": entities}


# ── 自检 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pipeline = TextProductionPipeline()

    # 测试1: 奇幻故事
    print("=== 测试1: 奇幻魔法学院 ===")
    doc = pipeline.run(
        "星光魔法学院",
        "一个普通女孩发现自己是最后一个星辰魔法师，必须在学院中掌握力量对抗即将回归的黑暗",
        genre="fantasy",
        tone="epic",
        setting="悬浮在星空中的古老魔法学院",
        num_beats=6,
        style="anime",
    )
    print(f"概念: {doc.concept.title}")
    print(f"节拍: {len(doc.beats)} 个")
    for b in doc.beats[:3]:
        print(f"  [{b.name}] {b.description[:50]}...")
    print(f"角色: {len(doc.characters)} 个")
    for c in doc.characters:
        print(f"  {c.name} ({c.archetype}): {c.personality}")
    print(f"场景: {len(doc.scenes)} 个")
    print(f"提示词: {len(doc.prompts)} 个")
    print(f"  [0] EN: {doc.prompts[0].english_prompt[:80]}...")
    print(f"  [0] CN: {doc.prompts[0].chinese_prompt[:80]}...")
    print(f"时间: {doc.metadata['elapsed_ms']:.0f}ms")

    # 测试2: 科幻故事
    print("\n=== 测试2: 赛博朋克都市 ===")
    doc2 = pipeline.run(
        "霓虹深渊",
        "在2077年的赛博都市，一个黑客发现AI已经控制了一切",
        genre="scifi",
        tone="dark",
        num_beats=5,
        style="scifi",
    )
    print(f"节拍: {len(doc2.beats)} 个")
    for b in doc2.beats[:3]:
        print(f"  [{b.name}] {b.description[:60]}...")
    print(f"提示词数: {len(doc2.prompts)}")

    # 测试3: 分镜输出
    print("\n=== 测试3: 分镜结构 ===")
    sb = doc.metadata["storyboard"]
    print(f"故事板: {sb['total_shots']} 个分镜")
    print(f"  第一个分镜: {sb['shots'][0]['prompt'][:80]}...")

    # 测试4: 实体注册表转换
    print("\n=== 测试4: 实体导出 ===")
    entities = production_to_entities(doc)
    print(f"实体数: {len(entities['entities'])}")
    for eid, edata in entities["entities"].items():
        print(f"  {eid}: {edata['name']} - {edata['description'][:60]}...")
