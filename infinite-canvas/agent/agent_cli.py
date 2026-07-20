#!/usr/bin/env python3
"""无限画布 v5.3 · Agent CLI (`ic` 命令行入口)

用法:
  ic generate "一只猫在月光下"                # 文生图
  ic storyboard "第一幕...", "第二幕..."      # 分镜编排
  ic entity list                            # 列出实体
  ic entity add 角色 --name "小明"           # 创建实体
  ic entity remove <id>                     # 删除实体
  ic status                                 # 查看服务状态
  ic workflow execute <node_id>             # 执行工作流链
  ic audio tts "你好世界"                    # TTS 语音合成
  ic audio music "epic cinematic"           # 音乐生成

环境变量:
  IC_BASE_URL    API 基址（默认 http://127.0.0.1:5180）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE_URL = os.environ.get("IC_BASE_URL", "http://127.0.0.1:5180")


# ── HTTP 工具 ───────────────────────────────────────────────────

def _api(method: str, path: str, body: Any = None) -> Any:
    """发送 HTTP 请求到 Canvas API，返回解析后的 JSON。"""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json") if data else None
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:500] if e.fp else str(e)
        print(f"  ✗ HTTP {e.code}: {msg}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"  ✗ 连接失败: {e.reason}", file=sys.stderr)
        sys.exit(1)


# ── 子命令 ──────────────────────────────────────────────────────

def cmd_generate(args: argparse.Namespace) -> None:
    """调用 /api/generate 生成图像/视频。"""
    payload: dict[str, Any] = {
        "prompt": args.prompt,
        "width": args.width,
        "height": args.height,
        "steps": args.steps,
        "cfg": args.cfg,
        "seed": args.seed,
        "batch_size": args.batch,
        "checkpoint": args.checkpoint or None,
    }
    if args.image:
        payload["input_image"] = args.image
        payload["denoise"] = args.denoise
    if args.frames:
        payload["frames"] = args.frames
        payload["fps"] = args.fps
    if args.video_quality:
        payload["video_quality"] = args.video_quality
    if args.negative:
        payload["negative"] = args.negative

    print(f"  → 生成中: {args.prompt[:60]}...")
    result = _api("POST", "/api/generate", payload)
    if result.get("status") == "submitted":
        print(f"  ✓ 已提交 prompt_id={result.get('prompt_id')}")
        for i, img in enumerate(result.get("images", [])):
            print(f"    [{i+1}] {img}")
        workflow = result.get("workflow")
        if workflow:
            print(f"  ✓ 画布节点 {len(workflow.get('nodes', []))} 个")
    else:
        print(f"  ✗ 失败: {result.get('status')}, {result.get('issues', [])}")


def cmd_storyboard(args: argparse.Namespace) -> None:
    """调用 /api/storyboard 分镜编排。"""
    prompts = [p.strip() for p in args.prompts.split(",") if p.strip()]
    if not prompts:
        print("  ✗ 请提供至少一个分镜提示词（逗号分隔）", file=sys.stderr)
        sys.exit(1)
    print(f"  → 分镜编排 {len(prompts)} 个镜头...")
    result = _api("POST", "/api/storyboard", {
        "prompts": prompts,
        "width": args.width,
        "height": args.height,
        "steps": args.steps,
        "cfg": args.cfg,
        "seed": args.seed,
    })
    print(f"  ✓ done={result.get('done')}/{result.get('total')}")
    for item in result.get("results", []):
        label = item.get("label", f"#{item.get('index', '?')}")
        img = (item.get("images") or [""])[0]
        print(f"    {label}: {img}")


def cmd_entity(args: argparse.Namespace) -> None:
    """实体管理（CRUD）。"""
    if args.action == "list":
        result = _api("GET", "/api/entities")
        entities = result.get("entities", [])
        print(f"  实体 ({len(entities)} 个):")
        for e in entities:
            print(f"    [{e.get('id')}] {e.get('name', e.get('alias', '?'))} ({e.get('kind', '?')})")
    elif args.action == "add":
        payload: dict[str, Any] = {
            "kind": args.kind,
            "name": args.name or args.kind,
            "description": f"{args.kind}: {args.name or ''}",
        }
        result = _api("POST", "/api/entities", payload)
        ent = result.get("entity", {})
        print(f"  ✓ 已创建实体 id={ent.get('id')}")
    elif args.action == "remove":
        _api("DELETE", f"/api/entities/{args.id}")
        print(f"  ✓ 已删除实体 {args.id}")
    else:
        print("  ✗ 未知操作", file=sys.stderr)
        sys.exit(1)


def cmd_status(_args: argparse.Namespace) -> None:
    """查看服务状态。"""
    try:
        entities = _api("GET", "/api/entities")
        health = _api("GET", "/api/health")
        print(f"  健康状态: {health.get('status', 'unknown')}")
        print(f"  实体数: {len(entities.get('entities', []))}")
    except SystemExit:
        print(f"  ✗ API 不可达 ({BASE_URL})")
        sys.exit(1)


def cmd_workflow_execute(args: argparse.Namespace) -> None:
    """执行工作流链。"""
    node_ids = [n.strip() for n in args.node_ids.split(",") if n.strip()]
    if not node_ids:
        print("  ✗ 请提供至少一个 node_id（逗号分隔）", file=sys.stderr)
        sys.exit(1)
    print(f"  → 执行工作流链: {node_ids}")
    payload: dict[str, Any] = {
        "node_ids": node_ids,
        "params": json.loads(args.params) if args.params else {},
    }
    result = _api("POST", "/api/workflow/execute-chain", payload)
    status = result.get("status", "unknown")
    if status == "completed":
        print(f"  ✓ 全部完成 ({result.get('completed', 0)}/{result.get('total', 0)})")
    elif status == "submitted":
        print(f"  → 已提交 prompt_id={result.get('prompt_id')}")
    else:
        print(f"  ✗ {status}: {result.get('error', '')}")


def cmd_audio(args: argparse.Namespace) -> None:
    """音频生成（TTS / 音乐）。"""
    if args.sub == "tts":
        print(f"  → TTS: {args.text[:60]}...")
        r = _api("POST", "/api/audio/generate", {
            "text": args.text,
            "speaker": args.speaker,
            "speed": args.speed,
            "emotion": args.emotion,
        })
    elif args.sub == "music":
        print(f"  → 音乐生成: {args.prompt[:60]}...")
        r = _api("POST", "/api/audio/music", {
            "prompt": args.prompt,
            "duration": args.duration,
            "tempo": args.tempo,
        })
    else:
        print(f"  ✗ 未知音频子命令: {args.sub}", file=sys.stderr)
        sys.exit(1)

    print(f"  {r.get('status')} prompt_id={r.get('prompt_id', 'N/A')}")


# ── 命令行解析 ──────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ic",
        description="无限画布 Agent CLI v5.3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate
    gen = subparsers.add_parser("generate", help="AI 生成图像/视频")
    gen.add_argument("prompt", help="正向提示词")
    gen.add_argument("-W", "--width", type=int, default=1024)
    gen.add_argument("-H", "--height", type=int, default=1024)
    gen.add_argument("--steps", type=int, default=20)
    gen.add_argument("--cfg", type=float, default=7.0)
    gen.add_argument("--seed", type=int, default=0)
    gen.add_argument("-n", "--batch", type=int, default=1, help="批量生成张数")
    gen.add_argument("--checkpoint", help="指定 SD 模型")
    gen.add_argument("--negative", default="", help="反向提示词")
    gen.add_argument("--image", help="图生图底图文件名（ComfyUI input/）")
    gen.add_argument("--denoise", type=float, default=0.6, help="图生图 denoise")
    gen.add_argument("--frames", type=int, default=0, help="视频帧数（>0 即视频模式）")
    gen.add_argument("--fps", type=int, default=16, help="视频帧率")
    gen.add_argument("--video-quality", choices=["speed", "quality"], default=None)
    gen.set_defaults(func=cmd_generate)

    # storyboard
    sb = subparsers.add_parser("storyboard", help="分镜编排（25宫格）")
    sb.add_argument("prompts", help="逗号分隔的分镜描述列表")
    sb.add_argument("-W", "--width", type=int, default=1024)
    sb.add_argument("-H", "--height", type=int, default=1024)
    sb.add_argument("--steps", type=int, default=20)
    sb.add_argument("--cfg", type=float, default=7.0)
    sb.add_argument("--seed", type=int, default=0)
    sb.set_defaults(func=cmd_storyboard)

    # entity
    ent = subparsers.add_parser("entity", help="实体管理（角色/道具/场景）")
    ent_sub = ent.add_subparsers(dest="action", required=True)
    ent_list = ent_sub.add_parser("list", help="列出所有实体")
    ent_list.set_defaults(func=cmd_entity)
    ent_add = ent_sub.add_parser("add", help="添加实体")
    ent_add.add_argument("kind", choices=["角色", "道具", "场景", "location", "prop"])
    ent_add.add_argument("--name", help="实体名称")
    ent_add.set_defaults(func=cmd_entity)
    ent_rm = ent_sub.add_parser("remove", help="删除实体")
    ent_rm.add_argument("id", help="实体节点 ID")
    ent_rm.set_defaults(func=cmd_entity)

    # status
    st = subparsers.add_parser("status", help="查看服务状态")
    st.set_defaults(func=cmd_status)

    # workflow execute
    wf = subparsers.add_parser("workflow", help="工作流执行")
    wf_sub = wf.add_subparsers(dest="sub", required=True)
    wf_exec = wf_sub.add_parser("execute", help="按拓扑执行节点链")
    wf_exec.add_argument("node_ids", help="逗号分隔的 node_id 列表")
    wf_exec.add_argument("--params", default="{}", help="额外执行参数 JSON")
    wf_exec.set_defaults(func=cmd_workflow_execute)

    # audio
    au = subparsers.add_parser("audio", help="音频生成（TTS/音乐）")
    au_sub = au.add_subparsers(dest="sub", required=True)
    au_tts = au_sub.add_parser("tts", help="TTS 语音合成 (CosyVoice2)")
    au_tts.add_argument("text", help="合成文本")
    au_tts.add_argument("--speaker", default="default")
    au_tts.add_argument("--speed", type=float, default=1.0)
    au_tts.add_argument("--emotion", default="neutral")
    au_tts.set_defaults(func=cmd_audio)
    au_mus = au_sub.add_parser("music", help="音乐生成 (MusicGen)")
    au_mus.add_argument("prompt", help="音乐描述")
    au_mus.add_argument("--duration", type=float, default=30.0)
    au_mus.add_argument("--tempo", type=int, default=120)
    au_mus.set_defaults(func=cmd_audio)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
