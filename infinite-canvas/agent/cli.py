#!/usr/bin/env python
"""无限画布 v5.0 · CLI 工具（Agent 入口）。

让 AI Agent/Copilot 可以直接调用 Infinite-Canvas：
  ic generate "一只猫在沙滩上散步" --mode txt2img
  ic generate "把这张图变成视频" --image cat.png --mode img2vid
  ic storyboard "三国演义第一回：桃园结义" --style realistic
  ic workflow generate "古风美女 古装 樱花树下 高清"
  ic serve                          # 启动 Web UI

安装：
  pip install -e .                 # 或 python agent/cli.py

Agent 集成（MCP 兼容）：
  工具名              → CLI 命令
  generate_image(p)   → ic generate p --mode txt2img
  generate_video(p,i) → ic generate p --image i --mode img2vid
  create_storyboard(s)→ ic storyboard s
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# 确保可导入 agent 包
_agent_dir = Path(__file__).resolve().parent
if str(_agent_dir) not in sys.path:
    sys.path.insert(0, str(_agent_dir))


# ── Click 可选依赖 ──────────────────────────────────────────────
try:
    import click
    HAS_CLICK = True
except ImportError:
    HAS_CLICK = False


# ── API 客户端 ───────────────────────────────────────────────────

class ICCLient:
    """Infinite-Canvas HTTP API 客户端（默认 http://localhost:8100）。"""

    def __init__(self, base_url: str = "http://localhost:8100"):
        self._base = base_url.rstrip("/")
        self._requests = None

    def _http(self):
        if self._requests is None:
            try:
                import requests  # type: ignore[import-untyped]
                self._requests = requests
            except ImportError:
                import urllib.request
                self._requests = "stdlib"
        return self._requests

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        if self._http() == "stdlib":
            import urllib.request as ur
            body = json.dumps(data).encode("utf-8")
            req = ur.Request(
                f"{self._base}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with ur.urlopen(req, timeout=600) as resp:
                return json.loads(resp.read().decode("utf-8"))
        r = self._http().post(f"{self._base}{path}", json=data, timeout=600)
        r.raise_for_status()
        return r.json()

    def _get(self, path: str) -> dict[str, Any]:
        if self._http() == "stdlib":
            import urllib.request as ur
            with ur.urlopen(f"{self._base}{path}", timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        r = self._http().get(f"{self._base}{path}", timeout=10)
        r.raise_for_status()
        return r.json()

    def health(self) -> dict[str, Any]:
        return self._get("/api/status")

    def list_models(self) -> dict[str, Any]:
        return self._get("/api/models")

    def list_templates(self) -> list[dict[str, Any]]:
        return self._get("/api/templates")

    def intent(self, user_input: str) -> dict[str, Any]:
        return self._post("/api/intent", {"user_input": user_input})

    def generate(
        self,
        prompt: str = "",
        action: str = "txt2img",
        model: str = "",
        image: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 4,
        cfg: float = 1.0,
        seed: int = 0,
        negative: str = "",
        wait: bool = True,
        intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative,
            "width": width, "height": height,
            "steps": steps, "cfg": cfg,
            "seed": seed, "wait": wait,
        }
        if action:
            payload["action"] = action
        if model:
            payload["checkpoint"] = model
        if image:
            payload["image"] = image
        if intent:
            payload["intent"] = intent
        return self._post("/api/generate", payload)

    def generate_video(
        self,
        prompt: str = "",
        image: str = "",
        end_image: str = "",
        width: int = 832,
        height: int = 480,
        frames: int = 33,
        fps: int = 16,
        seed: int = 0,
        wait: bool = True,
    ) -> dict[str, Any]:
        return self._post("/api/generate", {
            "prompt": prompt,
            "action": "img2vid" if image else "txt2vid",
            "image": image,
            "end_image": end_image,
            "width": width, "height": height,
            "length": frames, "fps": fps,
            "seed": seed, "wait": wait,
        })

    def storyboard(
        self,
        prompts: list[str],
        style: str = "realistic",
        width: int = 1024,
        height: int = 1024,
        seed: int = 0,
        steps: int = 4,
        cfg: float = 1.0,
    ) -> dict[str, Any]:
        return self._post("/api/storyboard/plan", {
            "prompts": prompts,
            "style": style,
            "width": width, "height": height,
            "seed": seed, "steps": steps, "cfg": cfg,
        })

    def workflow_generate(self, prompt: str, style: str = "") -> dict[str, Any]:
        return self._post("/api/workflows/generate", {
            "prompt": prompt,
            "style": style or "realistic",
        })

    def execute_chain(
        self,
        root_node_id: str,
        nodes: list[dict[str, Any]],
        port_edges: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._post("/api/workflow/execute-chain", {
            "root_node_id": root_node_id,
            "nodes": nodes,
            "port_edges": port_edges,
        })


# ── Click CLI ────────────────────────────────────────────────────

if HAS_CLICK:

    @click.group()
    @click.option("--base-url", envvar="IC_API_URL", default="http://localhost:8100",
                  help="Infinite-Canvas API 地址")
    @click.pass_context
    def cli(ctx: click.Context, base_url: str) -> None:
        """Infinite-Canvas CLI — 本地 AI 创作引擎

        \b
        用法：
          ic generate "一个场景描述"      # 生成图片
          ic generate --image a.png "描述"  # 图转视频
          ic storyboard "剧本片段"        # 生成分镜
          ic workflow generate "描述"     # 自然语言→工作流
          ic serve                       # 启动 Web UI
        """
        ctx.ensure_object(dict)
        ctx.obj["client"] = ICCLient(base_url)

    @cli.command()
    @click.argument("prompt")
    @click.option("--mode", "-m", default="txt2img",
                  type=click.Choice(["txt2img", "img2img", "txt2vid", "img2vid", "redraw", "expand"]),
                  help="生成模式")
    @click.option("--image", "-i", default=None, help="输入图片路径（img2img/img2vid/redraw 使用）")
    @click.option("--end-image", default=None, help="尾帧图片路径（img2vid 首尾帧模式）")
    @click.option("--model", default="", help="模型名（默认=共享库第一个）")
    @click.option("--width", "-W", type=int, default=1024, help="宽度")
    @click.option("--height", "-H", type=int, default=1024, help="高度")
    @click.option("--steps", type=int, default=4, help="采样步数")
    @click.option("--cfg", type=float, default=1.0, help="CFG scale")
    @click.option("--seed", "-s", type=int, default=0, help="随机种子")
    @click.option("--negative", default="", help="负向提示词")
    @click.option("--no-wait", is_flag=True, help="不等待生成完成")
    @click.option("--frames", type=int, default=33, help="视频帧数")
    @click.option("--fps", type=int, default=16, help="视频帧率")
    @click.pass_context
    def generate(
        ctx: click.Context,
        prompt: str, mode: str, image: str | None, end_image: str | None,
        model: str, width: int, height: int, steps: int, cfg: float,
        seed: int, negative: str, no_wait: bool, frames: int, fps: int,
    ) -> None:
        """从自然语言生成图片/视频。

        \b
        示例：
          ic generate "夕阳下的海滩"                    # 文生图
          ic generate --mode img2vid --image cat.png "猫在跑"  # 图生视频
          ic generate --mode img2vid --image start.png --end-image end.png "过渡"  # 首尾帧
        """
        client: ICCLient = ctx.obj["client"]

        if mode in ("txt2vid", "img2vid"):
            result = client.generate_video(
                prompt=prompt,
                image=image or "",
                end_image=end_image or "",
                width=width, height=height,
                frames=frames, fps=fps,
                seed=seed,
                wait=not no_wait,
            )
        else:
            result = client.generate(
                prompt=prompt, action=mode, model=model,
                image=image or "",
                width=width, height=height,
                steps=steps, cfg=cfg,
                seed=seed, negative=negative,
                wait=not no_wait,
            )

        if result.get("images"):
            click.echo(f"✅ 已生成 {len(result['images'])} 个文件：")
            for img in result["images"]:
                click.echo(f"   📁 {img}")
        elif result.get("validated") is False:
            click.echo(f"❌ 校验失败: {result.get('issues', [])}")
        else:
            click.echo(f"⏳ prompt_id={result.get('prompt_id', '?')} status={result.get('status', '?')}")

    @cli.command()
    @click.argument("script")
    @click.option("--style", default="realistic",
                  type=click.Choice(["anime", "realistic", "fantasy", "scifi", "cinematic"]),
                  help="视觉风格")
    @click.option("--width", type=int, default=1024)
    @click.option("--height", type=int, default=1024)
    @click.option("--seed", type=int, default=0)
    @click.option("--steps", type=int, default=4)
    @click.pass_context
    def storyboard(
        ctx: click.Context, script: str, style: str,
        width: int, height: int, seed: int, steps: int,
    ) -> None:
        """从剧本/故事描述自动生成分镜。

        示例：
          ic storyboard "一个武士在雨中决斗" --style cinematic
          ic storyboard "冬日暖阳下校园相遇" --style anime
        """
        client: ICCLient = ctx.obj["client"]

        # 走 5-Agent 写作管线：剧本 → 分镜提示词 → 批量生成
        result = client.storyboard(
            prompts=[script],  # 文本管线内部拆解
            style=style,
            width=width, height=height,
            seed=seed, steps=steps,
        )

        shots = result.get("shots", [])
        if shots:
            click.echo(f"✅ 已规划 {len(shots)} 个分镜：")
            for s in shots:
                click.echo(f"   🎬 #{s.get('index', '?')}  {s.get('description', '')[:80]}")
        else:
            click.echo("⚠️  分镜规划返回空，可能是服务端未启动")

    @cli.group()
    def workflow() -> None:
        """工作流管理。"""
        pass

    @workflow.command("generate")
    @click.argument("prompt")
    @click.option("--style", default="realistic", help="视觉风格")
    @click.pass_context
    def workflow_generate(ctx: click.Context, prompt: str, style: str) -> None:
        """自然语言 → 自动生成 ComfyUI 工作流 JSON。"""
        client: ICCLient = ctx.obj["client"]
        result = client.workflow_generate(prompt, style)
        if result.get("workflow"):
            click.echo("✅ 工作流已生成：")
            click.echo(json.dumps(result["workflow"], indent=2, ensure_ascii=False))
        else:
            click.echo(f"❌ 失败: {result.get('issues', [])}")

    @workflow.command("execute")
    @click.argument("root_node_id")
    @click.option("--nodes-file", default=None, help="JSON 文件：节点列表")
    @click.option("--edges-file", default=None, help="JSON 文件：端口连线列表")
    @click.pass_context
    def workflow_execute(
        ctx: click.Context, root_node_id: str,
        nodes_file: str | None, edges_file: str | None,
    ) -> None:
        """执行画布链路：从根节点沿端口连线全链路自动生成。

        ic workflow execute node-001 --nodes-file nodes.json --edges-file edges.json
        """
        client: ICCLient = ctx.obj["client"]

        nodes = []
        port_edges = []
        if nodes_file:
            with open(nodes_file, "r", encoding="utf-8") as f:
                nodes = json.load(f)
        if edges_file:
            with open(edges_file, "r", encoding="utf-8") as f:
                port_edges = json.load(f)

        result = client.execute_chain(root_node_id, nodes, port_edges)
        for r in result.get("results", []):
            status = r.get("status", "?")
            icon = "✅" if status == "generated" else ("⏭️" if status == "skipped" else "❌")
            click.echo(f"  {icon} {r['node_id']} → {status}")

    @cli.command()
    @click.option("--models", "-m", is_flag=True, help="列出可用模型")
    @click.option("--templates", "-t", is_flag=True, help="列出可用模板")
    @click.pass_context
    def list_cmd(ctx: click.Context, models: bool, templates: bool) -> None:
        """列出可用资源。"""
        client: ICCLient = ctx.obj["client"]
        if models:
            data = client.list_models()
            for ckpt in data.get("checkpoints", []):
                click.echo(f"   📦 {ckpt}")
        if templates:
            temps = client.list_templates()
            for t in temps:
                click.echo(f"   📋 {t.get('name', '?')}")

    @cli.command()
    @click.pass_context
    def serve(ctx: click.Context) -> None:
        """启动 Web UI（uvicorn 启动 FastAPI 服务）。"""
        click.echo("🚀 启动 Infinite-Canvas...")
        os.chdir(str(_agent_dir))
        import subprocess
        subprocess.run([sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"])

    @cli.command()
    @click.pass_context
    def health(ctx: click.Context) -> None:
        """健康检查。"""
        client: ICCLient = ctx.obj["client"]
        try:
            status = client.health()
            click.echo(f"🟢 ComfyUI: {status.get('comfyui', 'unknown')}")
        except Exception as e:
            click.echo(f"🔴 服务不可达: {e}")


# ── 无 Click 降级命令行 ──────────────────────────────────────────

def _run_no_click() -> None:
    print("Infinite-Canvas CLI (无 Click 模式)")
    print("请先安装: pip install click")
    print("或直接调用 Python API: from agent.cli import ICCLient")
    client = ICCLient()
    try:
        status = client.health()
        print(f"服务状态: {status}")
    except Exception as e:
        print(f"服务不可达: {e}")


if __name__ == "__main__":
    if HAS_CLICK:
        cli()
    else:
        _run_no_click()
