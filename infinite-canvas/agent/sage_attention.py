"""无限画布 v5.0 · SageAttention 加速配置管理器。

SageAttention 是一种 INT8/FP8 量化注意力实现，可将扩散模型的
attention 计算加速 2-3x，同时降低约 30% 显存占用。

模块职责：
1. 检测 SageAttention 可用性
2. 管理环境变量配置
3. 向 ComfyUI sampler 节点注入 attention_mode 参数
4. 提供显存/加速比估算

参考：https://github.com/thu-ml/SageAttention
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SageConfig:
    """SageAttention 运行时配置。"""
    enabled: bool = False
    dtype: str = "fp8"          # fp8 | fp16
    tile_size: int = 16         # 分块大小（blkh）
    smooth_k: bool = True       # K 量化光滑
    backend: str = "auto"       # auto | triton | cuda

    def env_vars(self) -> dict[str, str]:
        """生成环境变量 dict。"""
        if not self.enabled:
            return {}
        return {
            "SAGEATTENTION": "1",
            "SAGE_DTYPE": self.dtype,
            "SAGE_TILE_SIZE": str(self.tile_size),
            "SAGE_SMOOTH_K": "1" if self.smooth_k else "0",
            "SAGE_BACKEND": self.backend,
        }

    def sampler_params(self) -> dict[str, Any]:
        """返回注入 ComfyUI sampler 节点的参数。"""
        if not self.enabled:
            return {}
        return {
            "attention_mode": "sage",
            "sage_dtype": self.dtype,
            "sage_blkh": self.tile_size,
        }

    @property
    def estimated_speedup(self) -> float:
        """估算加速比。fp8: ~2.5x, fp16: ~1.8x。"""
        if not self.enabled:
            return 1.0
        return 2.5 if self.dtype == "fp8" else 1.8

    @property
    def vram_saved_pct(self) -> int:
        """估算显存节省百分比。"""
        if not self.enabled:
            return 0
        return 28 if self.dtype == "fp8" else 15


def detect_sage() -> SageConfig:
    """自动检测 SageAttention 可用性并返回配置。

    检测顺序：
    1. 环境变量 SAGEATTENTION=1 → 启用
    2. import sageattention 成功 → 启用
    3. 其他 → 禁用
    """
    config = SageConfig()

    # 环境变量优先级最高
    env_enabled = os.environ.get("SAGEATTENTION", "")
    if env_enabled == "1":
        config.enabled = True
    elif env_enabled == "0":
        config.enabled = False
        return config
    else:
        # 尝试导入检测
        try:
            import sageattention  # noqa: F401
            config.enabled = True
        except ImportError:
            config.enabled = False
            return config

    # 读取额外配置
    config.dtype = os.environ.get("SAGE_DTYPE", "fp8")
    config.tile_size = int(os.environ.get("SAGE_TILE_SIZE", "16"))
    config.smooth_k = os.environ.get("SAGE_SMOOTH_K", "1") == "1"
    config.backend = os.environ.get("SAGE_BACKEND", "auto")

    return config


def enable_sage(dtype: str = "fp8") -> SageConfig:
    """显式启用 SageAttention（设置环境变量）。"""
    config = SageConfig(enabled=True, dtype=dtype)
    for k, v in config.env_vars().items():
        os.environ[k] = v
    return config


def disable_sage() -> SageConfig:
    """禁用 SageAttention。"""
    for key in ("SAGEATTENTION", "SAGE_DTYPE", "SAGE_TILE_SIZE",
                 "SAGE_SMOOTH_K", "SAGE_BACKEND"):
        os.environ.pop(key, None)
    return SageConfig(enabled=False)


def apply_to_workflow(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """向流程中所有 sampler 节点注入 SageAttention 参数。

    识别 class_type 含 'Sampler' 的节点并注入 attention_mode。
    如 SageAttention 未启用则不修改。
    """
    config = detect_sage()
    if not config.enabled:
        return nodes

    sage_params = config.sampler_params()
    for node in nodes:
        ct = str(node.get("class_type", ""))
        if "sampler" in ct.lower() or "Sampler" in ct:
            inputs = node.setdefault("inputs", {})
            for k, v in sage_params.items():
                if k not in inputs:
                    inputs[k] = v
                elif isinstance(inputs[k], dict):
                    pass  # linked input, skip
    return nodes


def status_report() -> str:
    """返回 SageAttention 状态摘要（日志用）。"""
    config = detect_sage()
    if not config.enabled:
        return "SageAttention: 未启用（安装 pip install sageattention 后设置 SAGEATTENTION=1）"
    return (
        f"SageAttention: 已启用 | "
        f"量化={config.dtype} | "
        f"分块={config.tile_size} | "
        f"估算加速={config.estimated_speedup}x | "
        f"显存节省~{config.vram_saved_pct}%"
    )


# 模块导入时打印状态
_print_status = os.environ.get("SAGE_LOG_STATUS", "0")
if _print_status == "1":
    print(f"[sage_attention] {status_report()}", file=sys.stderr)
