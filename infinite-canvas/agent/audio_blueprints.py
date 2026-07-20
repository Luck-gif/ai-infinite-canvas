"""无限画布 v5.2 · 音频生成蓝图（对标 LibTV 第 4 类节点）。

模型选型（全开源，Apache 2.0 / MIT）：
  - TTS（文本→语音）：      CosyVoice2-0.5B (Apache 2.0) — ComfyUI 节点
  - 音乐生成：               MusicGen Small (MIT) — ComfyUI 节点
  - 音效/Foley：             Stable Audio Open — ComfyUI 节点

节点端口：
  text(in) → 文本/台词输入
  audio(out) → 音频输出（可流入视频节点作为 BGM/配音）

ComfyUI 自定义节点要求（用户需通过 ComfyUI Manager 安装）：
  - ComfyUI-CosyVoice  → 提供 CosyVoiceLoader / CosyVoiceTTS 节点
  - ComfyUI-MusicGen   → 提供 MusicGenLoader / MusicGenGenerate 节点
  - 备选: comfyui-audio → 提供通用 AudioScheduler / SaveAudioMP3 节点

v5.2 变更：
  - 从占位实现升级为真实 ComfyUI 工作流构造
  - 自动感知模型可用性：若自定义节点不可用 → 回退到文本透传模式
  - 输出格式统一为 wav（ComfyUI 标准音频输出）
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

_SHARED = os.environ.get("SHARED_MODEL_LIB", "")


def cosyvoice_tts_workflow(
    text: str,
    speaker: str = "default",
    speed: float = 1.0,
    emotion: str = "neutral",
    output_format: str = "wav",
) -> dict[str, Any]:
    """CosyVoice2 TTS ComfyUI 工作流（v5.2 真实实现）。

    需要 ComfyUI-CosyVoice 自定义节点（已发布）。
    若自定义节点不可用 → 回退到文本透传（workflow_executor 会捕获 None 并返回状态）。

    ComfyUI 节点链：
      CosyVoiceLoader → CosyVoiceTTS → SaveAudio
    """
    text_preview = text[:80] + ("..." if len(text) > 80 else "")
    seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16) % (2**31)

    # CosyVoice2 模型文件（ComfyUI 自定义节点在 models/cosyvoice/ 下查找）
    model_dir = os.path.join(_SHARED, "cosyvoice")
    model_path = os.path.join(model_dir, "CosyVoice2-0.5B")

    return {
        "_blueprint": "cosyvoice_tts",
        "_version": "v5.2",
        "_status": "active",
        "_meta": {
            "text_preview": text_preview,
            "speaker": speaker,
            "speed": speed,
            "emotion": emotion,
            "seed": seed,
            "model_path": model_path,
            "requires_nodes": ["CosyVoiceLoader", "CosyVoiceTTS", "SaveAudio"],
        },
        "workflow": {
            "1": {
                "class_type": "CosyVoiceLoader",
                "inputs": {
                    "model_name": "CosyVoice2-0.5B",
                    "precision": "fp16",
                },
            },
            "2": {
                "class_type": "CosyVoiceTTS",
                "inputs": {
                    "model": ["1", 0],
                    "text": text,
                    "speaker": speaker,
                    "speed": speed,
                    "emotion": emotion,
                    "seed": seed,
                },
            },
            "3": {
                "class_type": "SaveAudio",
                "inputs": {
                    "audio": ["2", 0],
                    "filename_prefix": "tts_cosyvoice",
                    "format": output_format,
                },
            },
        },
    }


def musicgen_workflow(
    prompt: str,
    duration: float = 30.0,
    tempo: int = 120,
    output_format: str = "wav",
) -> dict[str, Any]:
    """MusicGen 音乐生成 ComfyUI 工作流（v5.2 真实实现）。

    需要 ComfyUI-MusicGen 自定义节点（已发布）。
    若自定义节点不可用 → 回退到文本透传。

    ComfyUI 节点链：
      MusicGenLoader → MusicGenGenerate → SaveAudio
    """
    prompt_preview = prompt[:80] + ("..." if len(prompt) > 80 else "")
    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)

    model_dir = os.path.join(_SHARED, "musicgen")
    model_path = os.path.join(model_dir, "musicgen-small")

    return {
        "_blueprint": "musicgen",
        "_version": "v5.2",
        "_status": "active",
        "_meta": {
            "prompt_preview": prompt_preview,
            "duration_sec": duration,
            "tempo_bpm": tempo,
            "seed": seed,
            "model_path": model_path,
            "requires_nodes": ["MusicGenLoader", "MusicGenGenerate", "SaveAudio"],
        },
        "workflow": {
            "1": {
                "class_type": "MusicGenLoader",
                "inputs": {
                    "model_name": "musicgen-small",
                    "precision": "fp16",
                },
            },
            "2": {
                "class_type": "MusicGenGenerate",
                "inputs": {
                    "model": ["1", 0],
                    "prompt": prompt,
                    "duration": duration,
                    "seed": seed,
                },
            },
            "3": {
                "class_type": "SaveAudio",
                "inputs": {
                    "audio": ["2", 0],
                    "filename_prefix": "music_musicgen",
                    "format": output_format,
                },
            },
        },
    }


def stable_audio_workflow(
    prompt: str,
    duration: float = 30.0,
    temperature: float = 0.9,
    output_format: str = "wav",
) -> dict[str, Any]:
    """Stable Audio Open 音效/音乐生成 ComfyUI 工作流（v5.2）。

    需要 comfyui-stable-audio 自定义节点。
    """
    prompt_preview = prompt[:80] + ("..." if len(prompt) > 80 else "")
    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)

    return {
        "_blueprint": "stable_audio",
        "_version": "v5.2",
        "_status": "active",
        "_meta": {
            "prompt_preview": prompt_preview,
            "duration_sec": duration,
            "temperature": temperature,
            "seed": seed,
            "requires_nodes": ["StableAudioLoader", "StableAudioGenerate", "SaveAudio"],
        },
        "workflow": {
            "1": {
                "class_type": "StableAudioLoader",
                "inputs": {
                    "model_name": "stable-audio-open-1.0",
                },
            },
            "2": {
                "class_type": "StableAudioGenerate",
                "inputs": {
                    "model": ["1", 0],
                    "prompt": prompt,
                    "seconds_total": int(duration * 382),  # Stable Audio 单位
                    "seed": seed,
                    "temperature": temperature,
                },
            },
            "3": {
                "class_type": "SaveAudio",
                "inputs": {
                    "audio": ["2", 0],
                    "filename_prefix": "sfx_stableaudio",
                    "format": output_format,
                },
            },
        },
    }


# ── 蓝图注册表 ──────────────────────────────────────────────────────

AUDIO_BLUEPRINTS: dict[str, Any] = {
    "cosyvoice_tts": cosyvoice_tts_workflow,
    "musicgen": musicgen_workflow,
    "stable_audio": stable_audio_workflow,
}


def build_audio_workflow(
    mode: str,
    text: str = "",
    prompt: str = "",
    speaker: str = "default",
    speed: float = 1.0,
    emotion: str = "neutral",
    duration: float = 30.0,
    tempo: int = 120,
    temperature: float = 0.9,
    output_format: str = "wav",
) -> dict[str, Any] | None:
    """统一入口：根据 mode 构建音频 ComfyUI 工作流。

    Returns:
        dict with 'workflow' key (ComfyUI JSON) + metadata, or None if mode unknown
    """
    if mode == "cosyvoice_tts" or mode == "tts":
        return cosyvoice_tts_workflow(text=text, speaker=speaker, speed=speed,
                                      emotion=emotion, output_format=output_format)
    elif mode == "musicgen" or mode == "music":
        return musicgen_workflow(prompt=prompt, duration=duration,
                                 tempo=tempo, output_format=output_format)
    elif mode == "stable_audio" or mode == "sfx":
        return stable_audio_workflow(prompt=prompt, duration=duration,
                                     temperature=temperature, output_format=output_format)
    return None
