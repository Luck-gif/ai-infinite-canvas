"""无限画布 · 意图解析器（§8.1.4 / §8.1.5 / §8.1.6）。

将用户自然语言 → 结构化意图（§8.1.4 schema）：
  { action, subject, style, elements, params{ model, width, height, steps, cfg, prompt, negative_prompt } }

主路线：DeepSeek API `deepseek-v4-flash`（用户提供的 API Key，.env 中的 DEEPSEEK_API_KEY）。
离线兜底：本机 Ollama `qwen2.5:14b`（已缓存 qwen2.5-coder:14b，自动降级选用）。

设计纪律（§12.1 安全）：
- API Key 仅从环境变量读取，**绝不打印/写入日志**。
- 用户输入经轻量清洗，防止提示词注入直接穿透（§12 风险表）。
- LLM 仅输出 JSON，解析失败抛异常由调用方降级（§14.3 自愈）。
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
# 离线兜底模型优先级（已缓存的优先）
OLLAMA_FALLBACKS = ["qwen2.5:14b", "qwen2.5-coder:14b", "qwen2.5:7b"]

# action 白名单（与 intent_map.SUPPORTED_ACTIONS 完全对齐，§6.0.2）
# 注意：拼写必须与 intent_map 中的 SUPPORTED_ACTIONS 严格一致
ACTION_WHITELIST = {
    "txt2img", "img2img", "inpaint", "outpaint",
    "txt2vid", "img2vid",
    "face_consistency", "image_blend", "style_consistency",
    "scene_consistency", "prop_consistency", "storyboard",
}

_SYSTEM_PROMPT = (
    "你是「无限画布」的 AI 漫剧创作意图解析器。用户用中文描述创作意图（图像/视频/角色/分镜等），"
    "你只输出严格 JSON，禁止 JSON 外任何内容。\n\n"
    "=== 支持的 action（12种）===\n"
    "1) txt2img — 文生图，纯文本描述\n"
    "2) img2img — 图生图，需参考已有图片\n"
    "3) inpaint — 局部重绘/修复\n"
    "4) outpaint — 扩图/外绘（向外扩展画面）\n"
    "5) txt2vid — 文生视频\n"
    "6) img2vid — 图生视频\n"
    "7) face_consistency — 面部一致，提到「同一个人」「保持长相」「这个角色的脸」\n"
    "8) style_consistency — 画风锁定，提到「同样的画风」「保持风格」\n"
    "9) scene_consistency — 场景一致，提到「同一个场景」「这个背景里」\n"
    "10) prop_consistency — 道具一致，提到「同一个物品」「保持这个道具」\n"
    "11) image_blend — 多图融合，提到「放到场景里」「合并」「合成」\n"
    "12) storyboard — 分镜编排，提到「分镜」「几个镜头」「这一段剧情」\n\n"
    "=== JSON 输出格式 ===\n"
    "所有 action 共享基础字段:\n"
    '{"action":"...","prompt":"英文提示词","negative_prompt":"","confidence":0.0}\n'
    "特定 action 额外出:\n"
    "- img2img/inpaint/outpaint/face_consistency/style_consistency/scene_consistency/prop_consistency:\n"
    '  加 "reference_image_id":"..." (提到图片/角色/场景时填逻辑ID)\n'
    "- inpaint: 加 mask_description(str)\n"
    "- outpaint: 加 direction(str: left/right/top/bottom/all)\n"
    "- face_consistency: 加 character_name(str) 和 method(str, 可省略)\n"
    "- style_consistency: 加 style_name(str)\n"
    "- image_blend: 加 source_image_ids(str[]列表)\n"
    "- storyboard: 加 shots(list of {shot_id,description,action,prompt})\n"
    "- img2img: 加 denoise_strength(float 0-1)\n\n"
    "=== 核心规则 ===\n"
    "1. prompt 必须是英文，基于用户描述扩展（主体+风格+光线+构图），禁止空字符串或占位符\n"
    "2. 默认 action 为 txt2img\n"
    "3. confidence 取值 0.0-1.0，匹配清晰则高\n"
    "4. 一致性类 action 优先级高于 txt2img：角色>风格>场景>道具\n"
    "5. 若用户同时描述「人物+场景」，分别归为 face_consistency 和 scene_consistency，不可混为 txt2img\n"
)

# 中文→JSON 的 few-shot 示例（覆盖全部 12 种 action，显著提升遵循度）
_FEWSHOT: list[dict[str, str]] = [
    # txt2img
    {"role": "user", "content": "画一座宁静的雪山湖泊，写实摄影风格，横图"},
    {"role": "assistant", "content": json.dumps({
        "action": "txt2img",
        "prompt": "a serene snow mountain lake, realistic photography, calm water reflection, soft natural light, highly detailed",
        "negative_prompt": "cartoon, low quality, watermark",
        "confidence": 0.95})},
    # img2img
    {"role": "user", "content": "把这张照片变成宫崎骏动漫风格"},
    {"role": "assistant", "content": json.dumps({
        "action": "img2img", "reference_image_id": "photo-1", "denoise_strength": 0.75,
        "prompt": "Studio Ghibli anime style portrait, hand-drawn, soft colors, gentle lighting, high quality",
        "negative_prompt": "photorealistic, 3d render, low quality",
        "confidence": 0.9})},
    # inpaint
    {"role": "user", "content": "把图片里这个人物的眼睛修复一下"},
    {"role": "assistant", "content": json.dumps({
        "action": "inpaint", "reference_image_id": "img-1", "mask_description": "眼睛区域",
        "prompt": "detailed eye, natural looking eye, realistic, high quality",
        "negative_prompt": "blurry, distorted, low quality",
        "confidence": 0.92})},
    # outpaint
    {"role": "user", "content": "把这张图向右扩展一倍"},
    {"role": "assistant", "content": json.dumps({
        "action": "outpaint", "reference_image_id": "img-1", "direction": "right",
        "prompt": "continue the scene, seamless extension, natural environment",
        "negative_prompt": "seam, border, cut",
        "confidence": 0.93})},
    # face_consistency
    {"role": "user", "content": "用这个角色的脸，画一张她在雨中撑伞的画面"},
    {"role": "assistant", "content": json.dumps({
        "action": "face_consistency", "reference_image_id": "char-1", "character_name": "她",
        "prompt": "a woman holding umbrella in the rain, same face and features, rainy street, moody atmosphere, soft lighting",
        "negative_prompt": "different face, low quality",
        "confidence": 0.94})},
    # style_consistency
    {"role": "user", "content": "保持这个水墨画风，画一只仙鹤"},
    {"role": "assistant", "content": json.dumps({
        "action": "style_consistency", "reference_image_id": "style-ref-1", "style_name": "水墨画风",
        "prompt": "a crane, traditional Chinese ink wash painting style, elegant brushstrokes, minimalist, artistic",
        "negative_prompt": "photorealistic, western painting style, color",
        "confidence": 0.94})},
    # scene_consistency
    {"role": "user", "content": "在这个古风庭院场景里，画一个丫鬟在扫地"},
    {"role": "assistant", "content": json.dumps({
        "action": "scene_consistency", "reference_image_id": "scene-courtyard-1", "scene_name": "古风庭院",
        "prompt": "a maid sweeping the floor, same ancient Chinese courtyard background, consistent architecture and lighting",
        "negative_prompt": "different background, modern elements",
        "confidence": 0.92})},
    # prop_consistency
    {"role": "user", "content": "保持这把剑的样子，画一个侠客拿着它站在山顶"},
    {"role": "assistant", "content": json.dumps({
        "action": "prop_consistency", "reference_image_id": "sword-1", "prop_name": "剑",
        "prompt": "a swordsman holding the same sword on a mountain peak, dramatic lighting, epic atmosphere",
        "negative_prompt": "different sword design, low quality",
        "confidence": 0.91})},
    # image_blend
    {"role": "user", "content": "把这张角色图放到那个森林场景里"},
    {"role": "assistant", "content": json.dumps({
        "action": "image_blend", "source_image_ids": ["char-1", "forest-scene-1"],
        "prompt": "character placed in forest scene, natural composition, consistent lighting, photorealistic blend",
        "negative_prompt": "mismatched lighting, cutout look",
        "confidence": 0.93})},
    # txt2vid
    {"role": "user", "content": "生成一段樱花飘落的视频，5秒"},
    {"role": "assistant", "content": json.dumps({
        "action": "txt2vid", "duration": 5,
        "prompt": "cherry blossoms falling gently in the wind, spring atmosphere, soft natural light, cinematic slow motion",
        "negative_prompt": "low quality, jittery, blurry",
        "confidence": 0.95})},
    # img2vid
    {"role": "user", "content": "把这张静态图变成动态视频，人物眨眼微笑"},
    {"role": "assistant", "content": json.dumps({
        "action": "img2vid", "reference_image_id": "portrait-1",
        "prompt": "person blinking and smiling gently, natural subtle movement, cinematic portrait",
        "negative_prompt": "static, frozen, unnatural movement",
        "confidence": 0.9})},
    # storyboard
    {"role": "user", "content": "做一个3个镜头的分镜：女主走进房间，看到桌上的信，拿起信哭了"},
    {"role": "assistant", "content": json.dumps({
        "action": "storyboard",
        "shots": [
            {"shot_id": "1", "description": "女主走进房间", "action": "txt2img",
             "prompt": "a young woman entering a dimly lit room, full body shot, melancholic atmosphere, cinematic lighting"},
            {"shot_id": "2", "description": "看到桌上信", "action": "txt2img",
             "prompt": "close up of a letter on a wooden table, warm candlelight, vintage paper texture"},
            {"shot_id": "3", "description": "拿起信哭了", "action": "txt2img",
             "prompt": "a young woman holding a letter, tears streaming down, emotional close up, soft focus, dramatic lighting"}
        ],
        "prompt": "storyboard of 3 shots about a woman discovering a letter",
        "negative_prompt": "low quality",
        "confidence": 0.95})},
    # Qwen-Image 文生图
    {"role": "user", "content": "用 Qwen-Image 画一只在星空下奔跑的红色狐狸，赛博朋克风格，竖图"},
    {"role": "assistant", "content": json.dumps({
        "action": "txt2img",
        "prompt": "a red fox running under a starry sky, cyberpunk, neon glow, dynamic motion, highly detailed",
        "negative_prompt": "blurry, low quality",
        "confidence": 0.96})},
]

_JSON_FENCE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出中稳健提取首个 JSON 对象。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ```json ... ``` 围栏
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    m = _JSON_FENCE.search(text)
    if not m:
        raise ValueError(f"LLM 输出不含 JSON: {text[:200]}")
    return json.loads(m.group(0))


def _sanitize(user_input: str) -> str:
    """轻量清洗，降低提示词注入直接穿透风险（§12）。"""
    # 移除明显的指令劫持尝试
    s = re.sub(r"(?i)(ignore|忽略|disregard).{0,40}(previous|above|instruction|指令)", " ", user_input)
    return s.strip()[:2000]


def parse_intent_deepseek(user_input: str) -> dict[str, Any]:
    """调用 DeepSeek v4 解析意图。失败抛异常（由调用方降级 Ollama）。"""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置")
    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            *_FEWSHOT,
            {"role": "user", "content": _sanitize(user_input)},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE}/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    content = data["choices"][0]["message"]["content"]
    return _postprocess(_extract_json(content), user_input)


def parse_intent_ollama(user_input: str) -> dict[str, Any]:
    """离线兜底：本机 Ollama 解析意图（§8.1.6）。"""
    import ollama  # 延迟导入，离线不可用时不影响主路线
    last_err: Exception | None = None
    for model in OLLAMA_FALLBACKS:
        try:
            client = ollama.Client(host=OLLAMA_URL)
            resp = client.chat(model=model, messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _sanitize(user_input)},
            ], options={"temperature": 0.2, "num_ctx": 32768})
            return _postprocess(_extract_json(resp["message"]["content"]), user_input)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(f"Ollama 兜底失败（{last_err!r}）")


def parse_intent(user_input: str) -> dict[str, Any]:
    """意图解析主入口：DeepSeek 优先，失败自动降级 Ollama（§14.3 自愈）。

    若 LLM 主路 + 离线兜底双双失败，仍返回「最小可用意图」（用用户原始中文输入
    作为 prompt），保证自然语言→真实出图闭环永不破（§14.3 自愈的最后一环）。
    """
    user_input = _sanitize(user_input)
    try:
        return parse_intent_deepseek(user_input)
    except Exception as e:  # noqa: BLE001
        import sys
        print(f"[intent] DeepSeek 失败，降级 Ollama: {e!r}", file=sys.stderr)
        try:
            return parse_intent_ollama(user_input)
        except Exception as e2:  # noqa: BLE001
            print(f"[intent] Ollama 亦失败，使用中文原输入兜底: {e2!r}", file=sys.stderr)
            return {
                "action": "txt2img",
                "subject": (user_input[:24] or "scene"),
                "style": "",
                "elements": [],
                "params": {
                    "prompt": user_input or "a beautiful scenery",
                    "negative_prompt": "",
                },
            }


def _postprocess(intent: dict[str, Any], user_input: str = "") -> dict[str, Any]:
    """归一化意图：兼容新旧两种 LLM 输出格式 → intent_map.build_workflow 所需格式.

    LLM 可能输出两种 schema:
     A) 旧格式: {action, subject, style, elements, params{prompt, negative_prompt, model, ...}}
     B) 新格式: {action, prompt, negative_prompt, confidence, reference_image_id?, ...}

    归一化后统一提供:
      - intent["params"]["prompt"] / intent["params"]["negative_prompt"]
      - intent["subject"]  作为主体提取兜底
      - intent["action"]  白名单校验
    """
    intent.setdefault("action", "txt2img")

    # 确保 params 存在并合并新旧字段
    params = intent.get("params")
    if not isinstance(params, dict):
        params = {}
    intent["params"] = params

    # 新格式: 顶层 prompt/negative_prompt → 合并到 params
    top_prompt = str(intent.pop("prompt", "")).strip()
    top_neg = str(intent.pop("negative_prompt", "")).strip()
    params_prompt = str(params.get("prompt", "")).strip()
    params_neg = str(params.get("negative_prompt", "")).strip()

    user_input = (user_input or "").strip()
    llm_prompt = top_prompt or params_prompt
    llm_neg = top_neg or params_neg

    # 新格式: 顶层标量参数（duration/fps/blend_mode/face_weight/denoise_strength 等）
    # → 合并进 params（IntentResponse 只透传 params，顶层字段会在 API 边界丢失）
    _KEY_RENAME = {"denoise_strength": "denoise"}  # LLM 键名 → build_workflow 键名
    _KEEP_TOP = {"action", "subject", "style", "elements", "params", "confidence",
                 "reference_image_id", "character_name", "style_name", "scene_name",
                 "prop_name", "source_image_ids", "shots", "story_context"}
    for k, v in list(intent.items()):
        if k in _KEEP_TOP or not isinstance(v, (str, int, float, bool)):
            continue
        nk = _KEY_RENAME.get(k, k)
        params.setdefault(nk, v)

    # 视频: duration(秒) → frames 换算（build_workflow 读 params["frames"]）
    if "frames" not in params and params.get("duration"):
        try:
            vfps = int(params.get("fps") or 16)
            params["frames"] = max(1, int(float(params["duration"]) * vfps))
        except (TypeError, ValueError):
            pass

    # 泛化/退化词表（DeepSeek v4 偶发占位）
    _GENERIC = [
        "question mark", "unknown", "an image with", "placeholder", "暂无", "无 ", "n/a",
        "beautiful landscape", "beautiful scene", "beautiful image", "a picture of",
        "an artistic", "soft gradients", "geometric shapes", "high quality, photorealistic",
        "masterpiece only",
    ]
    _use_llm = (
        bool(llm_prompt)
        and len(llm_prompt) >= 10  # 降低阈值，兼容短但有效的英文 prompt
        and not any(b in llm_prompt.lower() for b in _GENERIC)
    )
    prompt = llm_prompt if _use_llm else (user_input or "a beautiful scenery")
    params["prompt"] = prompt
    params["negative_prompt"] = llm_neg

    # 旧格式: subject / style / elements → 保持兼容
    intent.setdefault("subject", "")
    intent.setdefault("style", "")
    intent.setdefault("elements", [])

    # subject 退化为 user_input 截断
    subj = str(intent.get("subject", "")).strip()
    if subj.lower() in ("", "unknown") or any(b in subj.lower() for b in _GENERIC):
        intent["subject"] = (user_input[:24] if user_input else "scene")

    # action 白名单约束
    if intent["action"] not in ACTION_WHITELIST:
        intent["action"] = "txt2img"

    intent["params"] = params
    return intent


# ═══════════════════════════════════════════════════════════════
# v5.6 故事板引导式工作流 — 叙事提取
# ═══════════════════════════════════════════════════════════════

_NARRATIVE_SYSTEM = (
    "你是一个专业的漫画/动画分镜分析师。用户会提供一段故事叙述文字，你需要从中提取：\n"
    "1) 所有角色（名字、外观描述、性格特征、角色定位）\n"
    "2) 所有场景（名称、环境描述、氛围）\n"
    "3) 推荐的分镜列表（每个分镜包含：镜头描述、所属角色、场景、英文文生图 prompt）\n\n"
    "规则：\n"
    "- characters: 提取所有具名角色，description 用中文描述外观，traits 描述性格\n"
    "- scenes: 提取所有场景/地点，mood 描述氛围（如 '温馨'/'紧张'/'浪漫'）\n"
    "- shots: 将故事拆分为 4~12 个关键镜头，每个镜头提供英文 ComfyUI txt2img prompt（50~150词）\n"
    "- 分镜 prompt 要求：详细描述画面内容、光照、构图、风格，适合英文 T5 编码器\n"
    "- genre: 故事类型（玄幻/都市/古风/科幻/悬疑/爱情/武侠/校园）\n"
    "- style_suggestion: 推荐的画风（水墨/manga/动漫/anime/写实/厚涂）\n"
    "输出纯 JSON，不要包含 ```json 标记或额外解释。"
)

_NARRATIVE_FEWSHOT: list[dict[str, str]] = [
    {"role": "user", "content": (
        "故事：少年林风在青云山修炼，一日遇到受伤的白狐少女雪璃。"
        "林风救了她，两人在林间小屋避雨。雪璃原来是妖族公主，被仇家追杀。"
        "林风决定帮她对抗追兵，在月下立下守护誓约。"
    )},
    {"role": "assistant", "content": json.dumps({
        "title": "青云之约",
        "genre": "玄幻",
        "style_suggestion": "水墨仙侠",
        "characters": [
            {"name": "林风", "description": "约18岁少年，束发青衫，眉目清秀，有侠气", "traits": "善良勇敢、重情义", "role": "主角"},
            {"name": "雪璃", "description": "白狐化形的少女，银发蓝瞳，身披白色斗篷，手臂有伤", "traits": "高贵冷傲、内心温柔", "role": "主角"},
        ],
        "scenes": [
            {"name": "青云山", "description": "云雾缭绕的仙山，古木参天，山间有溪流", "mood": "空灵神秘"},
            {"name": "林间小屋", "description": "简朴的木屋，内有火炉，雨夜烛光摇曳", "mood": "温馨"},
            {"name": "月下崖台", "description": "山顶平坦石台，俯瞰云海，月光如水", "mood": "浪漫庄严"},
        ],
        "shots": [
            {"shot_id": "1", "character": "林风", "scene": "青云山", "action": "txt2img",
             "description": "林风在青云山修炼，盘坐山巅",
             "prompt": "a young cultivator in green robe meditating on a misty mountain peak, ancient pine trees, ethereal clouds, Chinese ink wash painting style, cinematic wide shot, soft natural light"},
            {"shot_id": "2", "character": "林风, 雪璃", "scene": "青云山", "action": "txt2img",
             "description": "林风发现受伤的白狐少女",
             "prompt": "a young man discovering an injured silver-haired girl with fox ears lying under an ancient tree, white cloak, blood on her arm, concerned expression, dappled forest light"},
            {"shot_id": "3", "character": "林风, 雪璃", "scene": "林间小屋", "action": "txt2img",
             "description": "林风在木屋中为雪璃包扎伤口",
             "prompt": "inside a cozy wooden cabin, a young man gently bandaging the arm of a silver-haired fox girl by candlelight, rain outside the window, warm amber lighting, intimate atmosphere, anime style"},
            {"shot_id": "4", "character": "雪璃", "scene": "林间小屋", "action": "txt2img",
             "description": "雪璃向林风透露自己的真实身份",
             "prompt": "close up portrait of a beautiful silver-haired fox spirit girl, revealing expression, teary blue eyes, candlelight reflecting in her eyes, dramatic chiaroscuro lighting, emotional anime style"},
            {"shot_id": "5", "character": "林风", "scene": "林间小屋", "action": "txt2img",
             "description": "林风坚定地表示要保护雪璃",
             "prompt": "a determined young cultivator clenching his fist, resolute expression, warm firelight, dramatic low-angle shot, ink wash painting style"},
            {"shot_id": "6", "character": "林风, 雪璃", "scene": "月下崖台", "action": "txt2img",
             "description": "月下两人立下守护誓约",
             "prompt": "a young man and a silver-haired fox girl standing together on a cliff edge under the full moon, sea of clouds below, oath-taking pose, ethereal moonlight, romantic fantasy atmosphere, cinematic wide shot, anime style"},
        ],
    }, ensure_ascii=False)},
]


def extract_narrative_deepseek(story_text: str) -> dict[str, Any]:
    """调用 DeepSeek 提取故事中的角色、场景、分镜（v5.6 叙事提取）。"""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置")
    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _NARRATIVE_SYSTEM},
            *_NARRATIVE_FEWSHOT,
            {"role": "user", "content": f"故事：{_sanitize(story_text)}"},
        ],
        "temperature": 0.4,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE}/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode())
    content = data["choices"][0]["message"]["content"]
    narrative = _extract_json(content)

    # 归一化：确保所有字段存在
    narrative.setdefault("title", "")
    narrative.setdefault("genre", "")
    narrative.setdefault("style_suggestion", "anime")
    narrative.setdefault("characters", [])
    narrative.setdefault("scenes", [])
    narrative.setdefault("shots", [])

    # 过滤空字符
    for ch in narrative["characters"]:
        ch.setdefault("name", "未知")
        ch.setdefault("description", "")
        ch.setdefault("traits", "")
        ch.setdefault("role", "角色")

    for sc in narrative["scenes"]:
        sc.setdefault("name", "未知")
        sc.setdefault("description", "")
        sc.setdefault("mood", "")

    for i, sh in enumerate(narrative["shots"]):
        sh.setdefault("shot_id", str(i + 1))
        sh.setdefault("character", "")
        sh.setdefault("scene", "")
        sh.setdefault("action", "txt2img")
        sh.setdefault("description", "")
        sh.setdefault("prompt", f"{narrative.get('title', 'scene')} shot {i+1}")

    return narrative


def extract_narrative(user_input: str) -> dict[str, Any]:
    """叙事提取主入口：DeepSeek 优先，失败降级为简单分镜。"""
    user_input = _sanitize(user_input)
    try:
        return extract_narrative_deepseek(user_input)
    except Exception as e:
        import sys
        print(f"[narrative] DeepSeek 失败，使用规则兜底: {e!r}", file=sys.stderr)
        # 规则兜底：从文本长度推断分镜数
        length = len(user_input)
        shot_count = max(2, min(10, length // 80))
        return {
            "title": user_input[:30] + ("…" if len(user_input) > 30 else ""),
            "genre": "",
            "style_suggestion": "anime",
            "characters": [],
            "scenes": [],
            "shots": [
                {"shot_id": str(i+1), "character": "", "scene": "",
                 "action": "txt2img", "description": f"第{i+1}幕",
                 "prompt": f"scene {i+1} from the story, {user_input[:80]}, high quality"}
                for i in range(shot_count)
            ],
        }
