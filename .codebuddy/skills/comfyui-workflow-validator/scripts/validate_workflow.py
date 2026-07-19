#!/usr/bin/env python3
"""ComfyUI 工作流校验器（自包含，仅标准库）。

用途（§6.7.1 / §16.4 / §16.9）：在把工作流提交给 ComfyUI 前校验
  1) 每个节点 class_type 存在于运行中的 ComfyUI；
  2) 每个节点的「必需输入」都已提供（可捕获 SaveImage 缺 filename_prefix 这类 400 错误）；
  3) 可选 --submit：直接 POST /prompt 让 ComfyUI 自身做最终校验。

对接本机原生 ComfyUI Desktop（manager 代理偶发 502，已内置重试 + 核心节点降级）。
环境变量：COMFYUI_URL（默认 http://127.0.0.1:8188）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")

# ComfyUI 原生必含节点（/object_info 不可用时降级校验用）
CORE_NODES = {
    "KSampler", "KSamplerAdvanced", "CheckpointLoaderSimple", "CLIPLoader",
    "CLIPTextEncode", "EmptyLatentImage", "VAELoader", "VAEDecode",
    "SaveImage", "LoadImage", "UNETLoader",
}


def _get(url: str, timeout: int = 60, tries: int = 3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET {url} 失败: {last!r}")


def _post(url: str, payload: dict, timeout: int = 120, tries: int = 3):
    last = None
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode()), None
        except urllib.error.HTTPError as e:
            return None, e.read().decode()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"POST {url} 失败: {last!r}")


def validate(wf: dict, check_required: bool = True):
    """返回 (issues: list[str], degraded: bool)。"""
    issues: list[str] = []
    try:
        info = _get(f"{COMFYUI_URL}/object_info")
        degraded = False
    except RuntimeError as e:
        print(f"[warn] /object_info 不可用，降级到核心节点白名单：{e}", file=sys.stderr)
        info = None
        degraded = True

    for nid, node in wf.items():
        ct = node.get("class_type")
        if not ct:
            issues.append(f"节点 {nid}: 缺 class_type")
            continue
        if info is not None:
            if ct not in info:
                issues.append(f"节点 {nid}: class_type '{ct}' 在运行中的 ComfyUI 不存在")
                continue
            if check_required:
                req = (info[ct].get("input", {}) or {}).get("required", {}) or {}
                for iname in req:
                    if iname not in node.get("inputs", {}):
                        issues.append(f"节点 {nid} ({ct}): 缺必需输入 '{iname}'")
        else:
            if ct not in CORE_NODES:
                issues.append(f"节点 {nid}: '{ct}' 不在核心节点白名单（/object_info 不可用降级）")
    return issues, degraded


def main() -> None:
    ap = argparse.ArgumentParser(description="ComfyUI 工作流校验器")
    ap.add_argument("workflow", help="工作流 JSON 文件（ComfyUI 格式：{node_id: {class_type, inputs}}）")
    ap.add_argument("--submit", action="store_true", help="额外提交到 /prompt 让 ComfyUI 自身做最终校验")
    ap.add_argument("--client-id", default="workflow-validator")
    a = ap.parse_args()

    with open(a.workflow, encoding="utf-8") as f:
        wf = json.load(f)

    issues, degraded = validate(wf)
    if issues:
        print("❌ 静态校验失败：")
        for x in issues:
            print("  -", x)
    else:
        print("✅ 静态校验通过" + ("（降级模式）" if degraded else ""))

    if a.submit:
        resp, err = _post(f"{COMFYUI_URL}/prompt", {"prompt": wf, "client_id": a.client_id})
        if err:
            print("❌ /prompt 被 ComfyUI 拒绝：")
            print("  ", err[:800])
            issues.append("submit_rejected")
        elif resp and "prompt_id" in resp:
            print(f"✅ /prompt 接受，prompt_id={resp['prompt_id']}")

    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
