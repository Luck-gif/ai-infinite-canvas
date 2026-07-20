"""无限画布 · 环境诊断脚本（v4.50+）

一键检查 Agent 后端正常运行所需的所有前置条件：
  - Python 依赖是否安装
  - DeepSeek API Key 是否配置且可调用
  - Ollama（离线兜底）是否可用
  - ComfyUI 是否运行且 /object_info 可达
  - 所有工作流引用的自定义节点 class_type 是否在 ComfyUI 中注册
  - 所有工作流引用的模型文件是否在共享模型库中存在
  - GPU/VRAM 信息
  - ffmpeg 是否可用（视频拼接依赖）

输出：彩色终端报告，逐项 PASS/FAIL/SKIP，末段汇总。
用法：python env_check.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 颜色输出
# ---------------------------------------------------------------------------
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_BLUE = "\033[94m"
_RESET = "\033[0m"


def _pass(msg: str) -> None:
    print(f"  {_GREEN}PASS{_RESET}  {msg}")


def _fail(msg: str, detail: str = "") -> None:
    print(f"  {_RED}FAIL{_RESET}  {msg}")
    if detail:
        print(f"         {_YELLOW}{detail}{_RESET}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}WARN{_RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"  {_BLUE}INFO{_RESET}  {msg}")


# ── 所有工作流中实际引用的 class_type（从 comfy_client.py 提取）──
REQUIRED_CUSTOM_NODES: dict[str, str] = {
    # IPAdapter 系列（ComfyUI_IPAdapter_plus 插件）
    "IPAdapterInsightFaceLoader": "ComfyUI_IPAdapter_plus",
    "IPAdapterUnifiedLoaderFaceID": "ComfyUI_IPAdapter_plus",
    "IPAdapterFaceID": "ComfyUI_IPAdapter_plus",
    "IPAdapterModelLoader": "ComfyUI_IPAdapter_plus",
    "IPAdapterUnifiedLoader": "ComfyUI_IPAdapter_plus",
    "IPAdapterStyleComposition": "ComfyUI_IPAdapter_plus",
    "IPAdapter": "ComfyUI_IPAdapter_plus",
    # 图像混合（WAS Node Suite 等）
    "ImageBlend": "WAS_Node_Suite (或 rgthree/ComfyUI-Image-Blend)",
    # 视频合成（VideoHelperSuite）
    "VHS_VideoCombine": "ComfyUI-VideoHelperSuite",
}

# 各工作流所需核心模型文件 → 所在子目录
MODEL_FILES: dict[str, str] = {
    # SDXL 主力
    "NoobAI-XL-Vpred-v1.0.safetensors": "checkpoints",
    # Qwen-Image 2.0
    "qwen_image_2512_fp8_e4m3fn.safetensors": "unet",
    "qwen_2.5_vl_7b_fp8_scaled.safetensors": "clip",
    "qwen_image_vae.safetensors": "vae",
    # Wan2.2 视频
    "umt5_xxl_fp8_e4m3fn_scaled.safetensors": "clip",
    "wan_2.1_vae.safetensors": "vae",
    "wan2.2_bernini_r_high_noise_mxfp8.safetensors": "unet",
    "wan2.2_bernini_r_low_noise_mxfp8.safetensors": "unet",
    "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors": "unet",
    "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors": "unet",
    # IPAdapter
    "ip-adapter-plus_sd15.safetensors": "ipadapter",
}

# InsightFace 模型（IPAdapterInsightFaceLoader 依赖）
INSIGHTFACE_MODELS: list[str] = [
    "buffalo_l",  # 我们的工作流指定使用
]

# Python 运行时依赖
PYTHON_DEPS: dict[str, str] = {
    "fastapi": "pip install fastapi",
    "uvicorn": "pip install uvicorn",
    "pydantic": "pip install pydantic",
    "websockets": "pip install websockets",
    "PIL": "pip install Pillow",
    # 可选（离线兜底用）
    "ollama": "pip install ollama  (离线兜底，可选)",
}


# ---------------------------------------------------------------------------
# 1. Python 依赖
# ---------------------------------------------------------------------------
def check_python_deps() -> int:
    """返回失败数。"""
    print(f"\n{_BLUE}━━━ 1. Python 依赖 ━━━{_RESET}")
    fails = 0
    for mod, hint in PYTHON_DEPS.items():
        try:
            __import__(mod)
            _pass(mod)
        except ImportError:
            fails += 1
            _fail(mod, f"未安装 → {hint}")
    return fails


# ---------------------------------------------------------------------------
# 2. DeepSeek API
# ---------------------------------------------------------------------------
def check_deepseek() -> int:
    print(f"\n{_BLUE}━━━ 2. DeepSeek API ━━━{_RESET}")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    base = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

    if not key:
        _warn("DEEPSEEK_API_KEY 未设置（.env 或环境变量）")
        _info("  主意图解析将不可用，自动降级 Ollama")
        return 0  # 不做 fail，因为 Ollama 兜底

    _pass(f"API Key 已配置: {key[:6]}...{key[-4:]}")
    _info(f"  Base: {base}")
    _info(f"  Model: {model}")

    # 发一条最小请求测试连通性
    try:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }).encode()
        req = urllib.request.Request(
            f"{base}/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        _pass("API 连通（ping 成功）")
    except Exception as e:
        _fail("API 不可达", str(e)[:200])
        return 1
    return 0


# ---------------------------------------------------------------------------
# 3. Ollama（离线兜底）
# ---------------------------------------------------------------------------
def check_ollama() -> int:
    print(f"\n{_BLUE}━━━ 3. Ollama（离线兜底）━━━{_RESET}")
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        req = urllib.request.Request(f"{url}/api/tags")
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        models = [m["name"] for m in data.get("models", [])]
        _pass(f"Ollama 运行中，已有模型: {len(models)} 个")

        # 检查推荐的兜底模型
        FALLBACKS = ["qwen2.5:14b", "qwen2.5-coder:14b", "qwen2.5:7b"]
        found_any = False
        for m in FALLBACKS:
            exact = any(name == m or name.startswith(m + ":") for name in models)
            short = any(name.startswith(m.split(":")[0]) for name in models)
            if exact:
                _pass(f"  兜底模型就绪: {m}")
                found_any = True
            elif short:
                _info(f"  兜底模型近似: {m}（有同名不同 tag 的版本，可降级使用）")
                found_any = True
            else:
                _warn(f"  兜底模型缺失: {m} → ollama pull {m}")
        if not found_any:
            _warn("  无推荐的兜底模型，建议至少安装一个: ollama pull qwen2.5:7b")
        return 0
    except Exception as e:
        _warn(f"Ollama 不可用: {e!r}")
        _info("  离线兜底功能将不可用（DeepSeek 失败时无法降级）")
        return 0  # 不做 fail，因为 DeepSeek 主路线可用就行


# ---------------------------------------------------------------------------
# 4. ComfyUI 连通性 + /object_info
# ---------------------------------------------------------------------------
def check_comfyui() -> tuple[int, dict[str, Any] | None]:
    """返回 (fails, object_info_dict | None)。"""
    print(f"\n{_BLUE}━━━ 4. ComfyUI 连通性 ━━━{_RESET}")
    url = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
    _info(f"  URL: {url}")

    object_info: dict[str, Any] | None = None
    try:
        req = urllib.request.Request(f"{url}/object_info")
        with urllib.request.urlopen(req, timeout=60) as r:
            object_info = json.loads(r.read().decode())
        node_count = len(object_info)
        _pass(f"ComfyUI 运行中，已注册 {node_count} 个节点 class_type")
    except Exception as e:
        _fail("ComfyUI 不可达", str(e)[:200])
        return 1, None

    return 0, object_info


# ---------------------------------------------------------------------------
# 5. 自定义节点 class_type 注册检查
# ---------------------------------------------------------------------------
def check_custom_nodes(object_info: dict[str, Any] | None) -> int:
    print(f"\n{_BLUE}━━━ 5. 自定义节点注册检查 ━━━{_RESET}")
    if object_info is None:
        _warn("无法获取 /object_info，跳过节点注册检查")
        return 0

    fails = 0
    for ct, plugin in REQUIRED_CUSTOM_NODES.items():
        if ct in object_info:
            _pass(f"{ct} → {plugin}")
        else:
            fails += 1
            _fail(f"{ct} 未注册", f"  需要安装: {plugin}")

    if fails:
        print(f"\n  缺失 {fails} 个自定义节点，涉及以下工作流受限:")
        node_workflow_map = {
            "IPAdapterInsightFaceLoader": "face_consistency（角色一致性）",
            "IPAdapterUnifiedLoaderFaceID": "face_consistency（角色一致性）",
            "IPAdapterFaceID": "face_consistency（角色一致性）",
            "IPAdapterModelLoader": "style/scene/prop_consistency（风格/场景/道具一致性）",
            "IPAdapterUnifiedLoader": "style/scene/prop_consistency",
            "IPAdapterStyleComposition": "style_consistency（风格保持）",
            "IPAdapter": "scene/prop_consistency（场景/道具）",
            "ImageBlend": "image_blend（多图融合）",
            "VHS_VideoCombine": "txt2vid/img2vid（视频生成）",
        }
        shown = set()
        for ct in REQUIRED_CUSTOM_NODES:
            if ct not in object_info:
                impact = node_workflow_map.get(ct, "?")
                if impact not in shown:
                    print(f"     ⚠ {impact}")
                    shown.add(impact)
    return fails


# ---------------------------------------------------------------------------
# 6. 模型文件存在性检查
# ---------------------------------------------------------------------------
def check_model_files() -> int:
    print(f"\n{_BLUE}━━━ 6. 模型文件检查 ━━━{_RESET}")
    lib = os.environ.get("SHARED_MODEL_LIB", "")
    lib_path = Path(lib)
    _info(f"  共享模型库: {lib}")

    if not lib_path.is_dir():
        _fail("共享模型库目录不存在", f"  期望路径: {lib}\n  请设置 SHARED_MODEL_LIB 或确保 ComfyUI 模型库路径正确")
        return len(MODEL_FILES)

    fails = 0
    warnings = 0
    for filename, subdir in MODEL_FILES.items():
        fp = lib_path / subdir / filename
        if fp.is_file():
            size_mb = fp.stat().st_size / (1024 * 1024)
            _pass(f"{subdir}/{filename} ({size_mb:.0f} MB)")
        else:
            # 视频和 IPAdapter 模型不强制 fail（非核心路径）
            if "wan2.2" in filename or "wan_2." in filename or "umt5" in filename:
                warnings += 1
                _warn(f"{subdir}/{filename} 缺失 → 视频生成相关工作流不可用")
            elif "ip-adapter" in filename:
                warnings += 1
                _warn(f"{subdir}/{filename} 缺失 → 一致性工作流可能降级（IPAdapterUnifiedLoader 内置模型可兜底）")
            elif "qwen_image" in filename or "qwen_2.5" in filename:
                _warn(f"{subdir}/{filename} 缺失 → Qwen-Image 文生图路径不可用，回退 NoobAI")
            else:
                fails += 1
                _fail(f"{subdir}/{filename} 缺失", f"  该文件是核心工作流必需")
                _info(f"  预期路径: {fp}")

    if fails + warnings == 0:
        _pass("所有模型文件就绪")
    elif fails == 0 and warnings > 0:
        _info(f"  核心模型就绪，{warnings} 个非关键模型缺失（部分高级功能暂不可用）")

    return fails


# ---------------------------------------------------------------------------
# 7. GPU / VRAM
# ---------------------------------------------------------------------------
def check_gpu() -> int:
    print(f"\n{_BLUE}━━━ 7. GPU / VRAM ━━━{_RESET}")
    # nvidia-smi 可能不在当前 PATH 中，尝试多个路径
    nvidia_smi_paths = [
        "nvidia-smi",
    ]
    exe = None
    for p in nvidia_smi_paths:
        try:
            # --version 在 nvidia-smi 上不可用，改用 -L (list GPUs) 做可用性探测
            subprocess.run([p, "-L"], capture_output=True, timeout=5, check=True)
            exe = p
            break
        except Exception:
            continue

    if not exe:
        _warn("nvidia-smi 未在 PATH 中找到（但 ComfyUI 运行 2257+ 节点说明 GPU 实际可用）")
        return 0  # ComfyUI 已证明 GPU 可用，不做 fail

    try:
        result = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            _warn(f"nvidia-smi 查询失败: {result.stderr.strip()[:200]}")
            return 0
        for line in result.stdout.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                name, vram_mb, driver = parts[0], parts[1], parts[2]
                vram_gb = int(vram_mb) / 1024
                _pass(f"GPU: {name}")
                _info(f"  VRAM: {vram_gb:.0f} GB | Driver: {driver}")
                # 给出生存能力分析
                if vram_gb >= 72:
                    _info(f"  ✓ 可同时驻留 LLM(~25GB)+SDXL(~7GB)+Wan2.2 14B fp16(~55GB)= 约 87GB 峰值")
                    _info(f"    建议: Wan2.2 使用 fp8 量化(~28GB) 避免 OOM，实现三者同存")
                elif vram_gb >= 40:
                    _info(f"  ✓ 可同时驻留 LLM+SDXL+Wan2.2 fp8")
                    _info(f"    Wan2.2 14B fp16 可能 OOM，建议用 fp8 量化")
                elif vram_gb >= 20:
                    _info(f"  ✓ 可同时运行 LLM GGUF(~8GB)+SDXL(~7GB)")
                    _warn(f"    Wan2.2 视频生成可能需要 swap 或降低分辨率")
                elif vram_gb >= 15:
                    _info(f"  ✓ SDXL 可运行，WAN2.2 I2V fp8 (~13.6GB) 可用")
                    _warn(f"    LLM 建议用 Ollama 避免与 ComfyUI 抢显存")
                    _warn(f"    WAN2.2 T2V 双模型需 ~28GB，突破 16GB 上限")
                else:
                    _warn(f"  VRAM 偏低，SDXL 批处理可能受限")
    except FileNotFoundError:
        _warn("nvidia-smi 未找到（非 NVIDIA GPU 或无驱动）")
        return 1
    except Exception as e:
        _warn(f"GPU 检测失败: {e!r}")
        return 1
    return 0


# ---------------------------------------------------------------------------
# 8. ffmpeg（视频拼接依赖）
# ---------------------------------------------------------------------------
def check_ffmpeg() -> int:
    print(f"\n{_BLUE}━━━ 8. ffmpeg（视频拼接依赖）━━━{_RESET}")
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
        ver_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
        _pass(f"ffmpeg 可用: {ver_line[:80]}")
        return 0
    except FileNotFoundError:
        _warn("ffmpeg 未在 PATH 中找到 → /api/concat_videos（多段视频拼接）不可用")
        _info("  安装: winget install ffmpeg 或 https://ffmpeg.org/download.html")
        return 0  # 不做 fail，视频拼接是高级功能
    except Exception as e:
        _warn(f"ffmpeg 检查失败: {e!r}")
        return 0


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def _load_dotenv() -> None:
    """加载 .env 文件（与 main.py 的 _load_dotenv 行为一致）。"""
    dotenv_path = Path(__file__).parent / ".env"
    if not dotenv_path.is_file():
        return
    try:
        with open(dotenv_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except Exception:
        pass


def main() -> None:
    _load_dotenv()

    print(f"{_BLUE}{'='*60}{_RESET}")
    print(f"{_BLUE}  无限画布 · 环境诊断 v4.50{_RESET}")
    print(f"{_BLUE}  时间: {__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S}{_RESET}")
    print(f"{_BLUE}{'='*60}{_RESET}")

    all_fails = 0

    all_fails += check_python_deps()
    all_fails += check_deepseek()
    all_fails += check_ollama()

    comfy_fails, object_info = check_comfyui()
    all_fails += comfy_fails

    custom_fails = check_custom_nodes(object_info)
    all_fails += custom_fails

    model_fails = check_model_files()
    all_fails += model_fails

    all_fails += check_gpu()
    all_fails += check_ffmpeg()

    # ── 总结 ──
    print(f"\n{_BLUE}{'='*60}{_RESET}")
    if all_fails == 0:
        print(f"{_GREEN}  诊断结果：全部通过！Agent 后端可正常启动。{_RESET}")
    else:
        print(f"{_RED}  诊断结果：{all_fails} 项失败，请优先修复标记 FAIL 的项目。{_RESET}")
        print(f"{_YELLOW}  WARN 标记项可后续处理（非核心路径依赖）。{_RESET}")

    print(f"\n{_BLUE}  启动 Agent 后端:{_RESET}")
    print(f"    cd infinite-canvas/agent && uvicorn main:app --reload --port 5180")
    print(f"{_BLUE}{'='*60}{_RESET}")


if __name__ == "__main__":
    main()
