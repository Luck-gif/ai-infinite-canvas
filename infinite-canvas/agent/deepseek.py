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

# action 白名单（与 §6.0.2 的 18 个令牌一致）
ACTION_WHITELIST = {
    "txt2img", "img2img", "outpainting", "inpainting", "multi_reference",
    "pose_control", "depth_control", "canny_control", "ipadapter_face",
    "txt2vid", "img2vid", "frame2vid", "image_variation", "video_extension",
    "video_editing", "speech2text", "text_to_speech", "music",
}

_SYSTEM_PROMPT = (
    "你是「无限画布」的意图解析器。用户用中文或英文描述想生成的画面，你只输出严格 JSON，禁止 JSON 外任何内容。\n"
    "必须输出以下字段（不得增删）：\n"
    "{\n"
    '  "action": "txt2img",\n'
    '  "subject": "画面主体（简短具体，如『红色狐狸』；禁止 unknown/空）",\n'
    '  "style": "画面风格（如『赛博朋克』『写实摄影』『动漫』；无则空字符串）",\n'
    '  "elements": ["元素1", "元素2"],\n'
    '  "params": {\n'
    '    "model": "qwen2|sdxl|flux_klein（仅用户显式指定才填，否则省略）",\n'
    '    "width": 整数(竖图 height>width 如 768, 横图 width>height 如 1024, 方图 1024; 不确定省略),\n'
    '    "height": 整数(同理),\n'
    '    "steps": 整数(20-30; 不确定省略),\n'
    '    "cfg": 浮点(7.0; 不确定省略),\n'
    '    "prompt": "高质量英文正向提示词，基于用户描述扩展（主体+风格+光线+构图）；绝不能是占位符或空",\n'
    '    "negative_prompt": "英文负向提示词；无则空字符串"\n'
    "  }\n"
    "}\n"
    "规则：\n"
    "1. action 固定为 txt2img（本版本仅支持文生图）。\n"
    "2. subject 必须从用户描述提取具体主体，禁止 unknown。\n"
    "3. prompt 必须是有信息量的英文描述；若用户用中文，请翻译并扩展为英文提示词。禁止 'An image with...'、占位符、空字符串。\n"
    "4. 中文提示词也会被引擎接受，但英文质量更佳。"
)

# 中文→JSON 的 few-shot 示例（显著提升 deepseek-v4-flash 对中文的遵循度）
_FEWSHOT: list[dict[str, str]] = [
    {"role": "user", "content": "画一座宁静的雪山湖泊，写实摄影风格，横图"},
    {"role": "assistant", "content": json.dumps({
        "action": "txt2img", "subject": "雪山湖泊", "style": "写实摄影",
        "elements": ["雪山", "湖泊"],
        "params": {"width": 1024, "height": 576,
                   "prompt": "a serene snow mountain lake, realistic photography, calm water reflection, soft natural light, highly detailed",
                   "negative_prompt": "cartoon, low quality, watermark"}})},
    {"role": "user", "content": "用 Qwen-Image 画一只在星空下奔跑的红色狐狸，赛博朋克风格，竖图"},
    {"role": "assistant", "content": json.dumps({
        "action": "txt2img", "subject": "红色狐狸", "style": "赛博朋克",
        "elements": ["星空", "奔跑"],
        "params": {"model": "qwen2", "width": 768, "height": 1024,
                   "prompt": "a red fox running under a starry sky, cyberpunk, neon glow, dynamic motion, highly detailed",
                   "negative_prompt": "blurry, low quality"}})},
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
    """规整意图：强制字段存在、action 命中白名单、params 为 dict。

    退化兜底：DeepSeek v4 对中文结构化输出**不稳定**（时而高质量英文、时而泛化
    占位、时而直接回中文）。策略：
      - prompt：若 LLM 给的英文具体（≥20 字符且无泛化词）则用之；否则回退用户
        原始中文输入（NoobAI/SDXL 中文 clip 实测可用），保证出图不退化。
      - subject：退化（unknown/泛化）则用 user_input 截断兜底。
    目标：无论 LLM 如何波动，「自然语言→真实出图」闭环不破（§14.3 自愈）。
    """
    intent.setdefault("action", "txt2img")
    intent.setdefault("subject", "")
    intent.setdefault("style", "")
    intent.setdefault("elements", [])
    params = intent.get("params")
    if not isinstance(params, dict):
        params = {}
    user_input = (user_input or "").strip()
    llm_prompt = str(params.get("prompt") or "").strip()
    # 泛化/退化词表（DeepSeek v4 偶发占位）
    _GENERIC = [
        "question mark", "unknown", "an image with", "placeholder", "暂无", "无 ", "n/a",
        "beautiful landscape", "beautiful scene", "beautiful image", "a picture of",
        "an artistic", "soft gradients", "geometric shapes", "high quality, photorealistic",
        "masterpiece only",
    ]
    _use_llm = (
        bool(llm_prompt)
        and len(llm_prompt) >= 20
        and not any(b in llm_prompt.lower() for b in _GENERIC)
    )
    prompt = llm_prompt if _use_llm else (user_input or "a beautiful scenery")
    params["prompt"] = prompt
    params.setdefault("negative_prompt", "")
    intent["params"] = params
    subj = str(intent.get("subject", "")).strip()
    if subj.lower() in ("", "unknown") or any(b in subj.lower() for b in _GENERIC):
        intent["subject"] = (user_input[:24] if user_input else "scene")
    # action 白名单约束（§6.0.2）；未知 action 一律按 txt2img 兜底（仅 MVP 已支持）
    if intent["action"] not in ACTION_WHITELIST:
        intent["action"] = "txt2img"
    return intent
