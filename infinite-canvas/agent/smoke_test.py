"""端到端冒烟测试：验证 agent → 原生 ComfyUI(8188) → 共享库 真实出图。

运行：cd infinite-canvas/agent && .venv\\Scripts\\python.exe smoke_test.py
判据：用共享库已装 checkpoint 提交真实工作流，/history 完成后输出目录新增 PNG。
"""
from __future__ import annotations

import glob
import os
import sys

import comfy_client as cc

# 原生 ComfyUI 的 --output-directory（来自 shared_model_paths 启动参数）
OUT_DIR = r"C:\Users\17660\Downloads\Lora训练集\output_comfyui"


def main() -> int:
    print(f"[1] ComfyUI 目标: {cc.COMFYUI_URL}")
    print(f"[2] 共享模型库: {cc.SHARED_MODEL_LIB}")

    ckpts = cc.list_checkpoints()
    print(f"[3] 共享库 checkpoints ({len(ckpts)}): {ckpts}")
    if not ckpts:
        print("❌ 无可用 checkpoint"); return 1
    ckpt = next((c for c in ckpts if "NoobAI" in c), ckpts[0])
    print(f"[4] 选用: {ckpt}")

    wf = cc.build_txt2img(
        checkpoint=ckpt,
        prompt="a cute cat sitting on a desk, masterpiece, high quality",
        negative="blurry, low quality, deformed",
        width=512, height=512, steps=20, cfg=6.0,
    )
    ok, issues = cc.validate_workflow(wf)
    print(f"[5] /object_info 校验: ok={ok} issues={issues}")
    if not ok:
        print("❌ 工作流校验失败"); return 1

    before = set(glob.glob(os.path.join(OUT_DIR, "**", "*.png"), recursive=True))
    pid = cc.submit_workflow(wf)
    print(f"[6] 已提交 prompt_id={pid}，等待生成...")

    res = cc.wait_for_result(pid, timeout=600)
    status = (res.get("status") or {}).get("status_str") or res.get("status")
    print(f"[7] 完成 status={status}")

    after = set(glob.glob(os.path.join(OUT_DIR, "**", "*.png"), recursive=True))
    new = sorted(after - before)
    print(f"[8] 新增输出图片 ({len(new)}): {new}")
    if not new:
        print("❌ 未产生输出图片"); return 1

    print("✅ SMOKE TEST PASS —— 真实出图成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
