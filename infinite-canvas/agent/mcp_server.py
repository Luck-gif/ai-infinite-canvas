#!/usr/bin/env python3
"""无限画布 v5.3 · MCP Server (Model Context Protocol)

对外暴露画布操作工具，供任意 MCP 客户端（Claude Desktop / VS Code / 自定义 Agent）调用。

协议：JSON-RPC 2.0 over stdio（标准 MCP 协议）

暴露的工具（tools/call）:
  - generate_image    → 文生图 / 图生图
  - generate_video    → 文生视频 / 图生视频
  - storyboard        → 分镜编排（批量）
  - create_entity     → 创建角色/道具/场景实体
  - list_entities     → 列出所有实体
  - delete_entity     → 删除实体
  - execute_workflow  → 按端口连线拓扑执行
  - tts               → 语音合成
  - music             → 音乐生成
  - canvas_status     → 画布状态

启动:
  python mcp_server.py                    # 直接 stdio 运行
  python mcp_server.py --http 5181        # HTTP 模式（调试用）

依赖:
  仅标准库。通过 HTTP 调用运行中的 Canvas API（默认 localhost:5180）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

API_BASE = os.environ.get("IC_BASE_URL", "http://127.0.0.1:5180")

# ── HTTP 工具 ───────────────────────────────────────────────────

def _api(method: str, path: str, body: Any = None, timeout: int = 300) -> Any:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:500] if e.fp else str(e)
        return {"error": f"HTTP {e.code}: {msg}"}
    except urllib.error.URLError as e:
        return {"error": f"连接失败: {e.reason}"}


# ── 工具定义 ────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "generate_image",
        "description": "在无限画布上生成图片（文生图/图生图/ControlNet）。通过自然语言描述或详细的SD参数生成图像节点。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "正向提示词（英文）"},
                "negative": {"type": "string", "description": "反向提示词"},
                "width": {"type": "integer", "default": 1024},
                "height": {"type": "integer", "default": 1024},
                "steps": {"type": "integer", "default": 20},
                "cfg": {"type": "number", "default": 7.0},
                "seed": {"type": "integer", "default": 0},
                "batch_size": {"type": "integer", "default": 1, "description": "一次生成张数"},
                "checkpoint": {"type": "string", "description": "SD checkpoint 名称"},
                "input_image": {"type": "string", "description": "图生图底图（ComfyUI input/ 文件名）"},
                "denoise": {"type": "number", "default": 0.6},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "generate_video",
        "description": "在无限画布上生成视频（文生视频/图生视频）。使用 Wan2.2 Bernini 14B 模型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "视频描述（英文）"},
                "frames": {"type": "integer", "default": 33},
                "fps": {"type": "integer", "default": 16},
                "width": {"type": "integer", "default": 1024},
                "height": {"type": "integer", "default": 576},
                "quality": {"type": "string", "enum": ["speed", "quality"], "default": "speed"},
                "input_image": {"type": "string", "description": "图生视频底图（ComfyUI input/ 文件名）"},
                "seed": {"type": "integer", "default": 0},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "storyboard",
        "description": "创建分镜编排：输入镜头描述列表，并行生成一组帧图。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "分镜描述列表（每项一个镜头）",
                },
                "width": {"type": "integer", "default": 1024},
                "height": {"type": "integer", "default": 1024},
                "steps": {"type": "integer", "default": 20},
                "cfg": {"type": "number", "default": 7.0},
                "seed": {"type": "integer", "default": 0},
            },
            "required": ["prompts"],
        },
    },
    {
        "name": "create_entity",
        "description": "在画布上创建实体节点（角色/道具/场景），用于角色一致性和资产复用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["角色", "道具", "场景"], "description": "实体类别"},
                "name": {"type": "string", "description": "实体名称"},
                "description": {"type": "string", "description": "实体描述/提示词"},
            },
            "required": ["kind", "name"],
        },
    },
    {
        "name": "list_entities",
        "description": "列出画布上所有实体节点。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "delete_entity",
        "description": "从画布删除指定实体。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "实体节点 ID"},
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "execute_workflow",
        "description": "按端口连线的拓扑顺序执行画布节点链。自动解析节点依赖、构建 ComfyUI 工作流并提交执行。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要执行的节点 ID 列表（将自动拓扑排序）",
                },
                "params": {
                    "type": "object",
                    "description": "额外参数覆盖",
                },
            },
            "required": ["node_ids"],
        },
    },
    {
        "name": "tts",
        "description": "语音合成（TTS）：文本转语音，使用 CosyVoice2 模型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "合成文本"},
                "speaker": {"type": "string", "default": "default"},
                "speed": {"type": "number", "default": 1.0},
                "emotion": {"type": "string", "default": "neutral"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "music",
        "description": "音乐生成：根据文本描述生成音乐，使用 MusicGen 模型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "音乐风格/情绪描述"},
                "duration": {"type": "number", "default": 30.0},
                "tempo": {"type": "integer", "default": 120},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "canvas_status",
        "description": "获取无限画布当前状态：节点数、连线数、服务健康状态。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ── 工具执行调度 ────────────────────────────────────────────────

def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """分发到对应的 API 调用，返回 MCP 兼容的响应内容。"""
    try:
        if name == "generate_image":
            return _api("POST", "/api/generate", {
                "prompt": arguments["prompt"],
                "negative": arguments.get("negative", ""),
                "width": arguments.get("width", 1024),
                "height": arguments.get("height", 1024),
                "steps": arguments.get("steps", 20),
                "cfg": arguments.get("cfg", 7.0),
                "seed": arguments.get("seed", 0),
                "batch_size": arguments.get("batch_size", 1),
                "checkpoint": arguments.get("checkpoint"),
                "input_image": arguments.get("input_image"),
                "denoise": arguments.get("denoise", 0.6),
            })

        elif name == "generate_video":
            return _api("POST", "/api/generate", {
                "prompt": arguments["prompt"],
                "frames": arguments.get("frames", 33),
                "fps": arguments.get("fps", 16),
                "width": arguments.get("width", 1024),
                "height": arguments.get("height", 576),
                "video_quality": arguments.get("quality", "speed"),
                "input_image": arguments.get("input_image"),
                "seed": arguments.get("seed", 0),
            }, timeout=600)

        elif name == "storyboard":
            return _api("POST", "/api/storyboard", {
                "prompts": arguments["prompts"],
                "width": arguments.get("width", 1024),
                "height": arguments.get("height", 1024),
                "steps": arguments.get("steps", 20),
                "cfg": arguments.get("cfg", 7.0),
                "seed": arguments.get("seed", 0),
            })

        elif name == "create_entity":
            return _api("POST", "/api/entities", {
                "kind": arguments["kind"],
                "name": arguments["name"],
                "description": arguments.get("description", arguments["name"]),
            })

        elif name == "list_entities":
            result = _api("GET", "/api/entities")
            all_entities = result.get("entities", [])
            entities = [
                {
                    "id": e.get("id"),
                    "name": e.get("name", ""),
                    "kind": e.get("kind"),
                    "alias": e.get("alias", ""),
                    "description": e.get("description", ""),
                }
                for e in all_entities
            ]
            return {"count": len(entities), "entities": entities}

        elif name == "delete_entity":
            return _api("DELETE", f"/api/entities/{arguments['entity_id']}")

        elif name == "execute_workflow":
            return _api("POST", "/api/workflow/execute-chain", {
                "node_ids": arguments["node_ids"],
                "params": arguments.get("params", {}),
            }, timeout=600)

        elif name == "tts":
            return _api("POST", "/api/audio/generate", {
                "text": arguments["text"],
                "speaker": arguments.get("speaker", "default"),
                "speed": arguments.get("speed", 1.0),
                "emotion": arguments.get("emotion", "neutral"),
            })

        elif name == "music":
            return _api("POST", "/api/audio/music", {
                "prompt": arguments["prompt"],
                "duration": arguments.get("duration", 30.0),
                "tempo": arguments.get("tempo", 120),
            })

        elif name == "canvas_status":
            entities = _api("GET", "/api/entities")
            health = _api("GET", "/api/health")
            edges = _api("GET", "/api/port-edges")
            return {
                "entity_count": len(entities.get("entities", [])),
                "edge_count": edges.get("count", 0),
                "api_healthy": health.get("status") == "ok",
                "base_url": API_BASE,
            }

        else:
            return {"error": f"未知工具: {name}"}

    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ── JSON-RPC over stdio ─────────────────────────────────────────

def _send_json(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run_stdio() -> None:
    """MCP JSON-RPC 2.0 主循环（stdio）。"""
    # 发送初始 capability 声明
    # MCP 初始化是两步握手：initialize → initialized
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = msg.get("id")
        method = msg.get("method", "")

        if method == "initialize":
            _send_json({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "infinite-canvas",
                        "version": "5.3.0",
                    },
                    "capabilities": {
                        "tools": {},
                    },
                },
            })

        elif method == "notifications/initialized":
            # 客户端确认初始化完成，无需响应
            pass

        elif method == "tools/list":
            _send_json({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS},
            })

        elif method == "tools/call":
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = handle_tool_call(tool_name, arguments)

            # 构建 content 数组
            text = json.dumps(result, ensure_ascii=False, indent=2)
            _send_json({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                },
            })

        elif method == "ping":
            _send_json({"jsonrpc": "2.0", "id": msg_id, "result": {}})

        else:
            _send_json({
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


# ── HTTP 模式（调试）─────────────────────────────────────────────

def run_http(port: int = 5181) -> None:
    """简易 HTTP JSON-RPC 服务器（调试用）。"""
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            msg = json.loads(body)
            msg_id = msg.get("id")
            method = msg.get("method", "")

            if method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = msg.get("params", {})
                result = handle_tool_call(params.get("name", ""), params.get("arguments", {}))
            else:
                result = {"error": f"Unknown method: {method}"}

            resp = {"jsonrpc": "2.0", "id": msg_id, "result": result}
            data = json.dumps(resp, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            pass  # 静默日志

    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"MCP HTTP 调试服务器已启动: http://127.0.0.1:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


# ── 入口 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="无限画布 MCP Server v5.3")
    parser.add_argument("--http", type=int, default=0, help="HTTP 调试模式端口（0=stdio）")
    args = parser.parse_args()
    if args.http:
        run_http(args.http)
    else:
        run_stdio()
