"""无限画布 v5.0 · 音频生成蓝图（对标 LibTV 第 4 类节点）。

模型选型（全开源，Apache 2.0 / MIT）：
  - TTS（文本→语音）：      ChatTTS / CosyVoice2-0.5B (Apache 2.0)
  - 音乐生成：               Stable Audio Open / MusicGen (MIT)
  - 音色克隆：               OpenVoice v2 (MIT) — 待后续集成

节点端口：
  text(in) → 文本/台词输入
  audio(out) → 音频输出（可流入视频节点作为 BGM/配音）

此蓝图当前为占位实现，实际模型接入需要用户安装对应 ComfyUI 自定义节点。
TODO: 对接 CosyVoice2 ComfyUI 节点或独立 API。
"""

from __future__ import annotations

from typing import Any


def cosyvoice_tts_workflow(
    text: str,
    speaker: str = "default",
    speed: float = 1.0,
    emotion: str = "neutral",
    output_format: str = "wav",
) -> dict[str, Any]:
    """CosyVoice2 TTS 蓝图（待 ComfyUI 自定义节点接入）。

    当前方案：调用独立 CosyVoice2 API 或 CLI。
    后续对接 ComfyUI-CosyVoice2 自定义节点后改为完整工作流 JSON。
    """
    # 占位：实际蓝图需在 CosyVoice2 ComfyUI 节点发布后填充
    return {
        "_blueprint": "cosyvoice_tts",
        "_status": "placeholder",
        "params": {
            "text": text,
            "speaker": speaker,
            "speed": speed,
            "emotion": emotion,
            "format": output_format,
        },
    }


def musicgen_workflow(
    prompt: str,
    duration: float = 30.0,
    tempo: int = 120,
    output_format: str = "wav",
) -> dict[str, Any]:
    """MusicGen 音乐生成蓝图（待 ComfyUI-MusicGen 节点接入）。"""
    return {
        "_blueprint": "musicgen",
        "_status": "placeholder",
        "params": {
            "prompt": prompt,
            "duration": duration,
            "tempo": tempo,
            "format": output_format,
        },
    }
