---
name: infinite-canvas
description: This skill should be used when the user wants AI-generated images, videos, audio (TTS/music), or storyboards placed on an infinite canvas workspace. It wraps the full Canvas Agent API (LLM intent routing → ComfyUI workflow → result display). Use it whenever the user asks to "generate an image of...", "create a video of...", "make a storyboard", "design a character", "produce music for...", or any visual/audio creation task on the canvas. Also use it to manage canvas entities (characters, props, scenes) or execute linked node workflows.
---

# 无限画布 (Infinite Canvas) AI 创作引擎

## 目的

让 AI 助手通过自然语言驱动无限画布生成图像、视频、音频和分镜。画布后端将用户意图路由到 ComfyUI 工作流执行，结果以可视化卡片形式呈现在前端画布上。

## 何时使用

- 用户说"生成一张...图片"、"画一个..."、"做一个...视频"
- 用户说"分镜...""故事板...""镜头..."
- 用户说"创建角色...""添加道具...""管理素材..."
- 用户说"配音...""配乐...""语音合成..."
- 用户说"按顺序生成..."需要多节点流水线执行
- 用户提及"画布""无限画布""canvas"相关操作

## 架构概览

```
用户自然语言 → Agent CLI / MCP Server → Canvas API (FastAPI :5180)
                                          ↓
                                    intent_map (意图路由)
                                          ↓
                                    蓝图函数 (txt2img/img2img/video/audio)
                                          ↓
                                    ComfyUI (本地 :8188)
                                          ↓
                                    结果 → 画布节点卡片
```

## 核心概念

### 节点类型 (NodeKind)
画布上每个可视化元素是一个"节点"：

| Kind | 说明 | 蓝图函数 |
|------|------|----------|
| `txt2img` | 文生图 | Flux/SD 蓝图 |
| `img2img` | 图生图/ControlNet | SD + ControlNet 蓝图 |
| `video` | 文生视频/图生视频 | Wan2.2 Bernini 蓝图 |
| `audio` | TTS/音乐/音效 | CosyVoice2/MusicGen 蓝图 |
| `entity` | 角色/道具/场景 | 元数据节点 |
| `text` | 纯文本节点 | LLM 处理 |
| `storyboard` | 分镜容器 | 编排蓝图 |

### 端口连线 (PortEdges)
节点上的端口可通过"连线"建立数据依赖：上游节点的输出图片/音频自动作为下游节点的输入。

### 工作流执行 (WorkflowExecutor)
按端口连线的拓扑顺序自动执行节点链：BFS 拓扑排序 → 为每个节点构建 ComfyUI 蓝图 → 合并为单个工作流 → 提交 ComfyUI 执行。

## API 端点速查

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/llm/intent` | 自然语言 → 结构化意图（解析用户输入） |
| POST | `/api/llm/generate` | 意图/提示词 → ComfyUI 工作流 → 提交生成 |
| POST | `/api/nodes` | 创建画布节点 |
| GET | `/api/nodes` | 获取所有节点 |
| DELETE | `/api/nodes/{id}` | 删除节点 |
| POST | `/api/storyboard` | 分镜编排（批量提示词并行生成） |
| POST | `/api/workflow/execute-chain` | 拓扑执行节点链 |
| POST | `/api/port-edges` | 批量保存端口连线 |
| GET | `/api/port-edges` | 获取全部连线 |
| POST | `/api/audio/generate` | TTS 语音合成 |
| POST | `/api/audio/music` | 音乐生成 |
| GET | `/api/image/{filename}` | 图片代理（加载 ComfyUI 输出） |
| GET | `/api/workflow/status/{prompt_id}` | 查询工作流执行状态 |

## 操作指南

### 1. 图像生成
解析用户意图 → 调用 `POST /api/llm/generate`：
```json
{
  "prompt": "a cat sitting on a moonlit rooftop, anime style",
  "width": 1024, "height": 1024,
  "steps": 20, "cfg": 7.0,
  "checkpoint": "flux1DevHyper8step_fp16.safetensors"
}
```
返回 `{ prompt_id, status, images[], workflow: { nodes[] } }`。images 中的图片可通过 `/api/image/{filename}` 加载显示。

### 2. 视频生成
添加 `frames` 和 `fps` 字段：
```json
{
  "prompt": "a cat walking across a moonlit rooftop, cinematic",
  "frames": 33, "fps": 16,
  "video_quality": "speed",
  "width": 1024, "height": 576
}
```
使用 Wan2.2 Bernini 14B 模型。视频文件可通过 `/api/image/{filename}` 获取。

### 3. 分镜编排
```json
POST /api/storyboard
{
  "prompts": ["镜头1: 远景，月光下的城市", "镜头2: 中景，猫跳上屋顶"],
  "width": 1024, "height": 1024
}
```
返回 `{ total, done, results: [{ index, label, images[] }] }`。

### 4. 角色/实体管理
创建角色节点：
```json
POST /api/nodes
{
  "kind": "entity",
  "label": "小明",
  "prompt": "a young boy with black hair and glasses, anime style",
  "properties": { "type": "角色", "name": "小明" }
}
```
实体节点可在后续图生图中作为 `input_image` 引用实现角色一致性。

### 5. 工作流链执行
当画布上已有多个相连节点时，按拓扑执行：
```json
POST /api/workflow/execute-chain
{
  "node_ids": ["node-1", "node-2", "node-3"],
  "params": {}
}
```
WorkflowExecutor 自动解析端口连线依赖、拓扑排序、构建蓝图、提交 ComfyUI。

### 6. 音频生成
TTS：
```json
POST /api/audio/generate
{ "text": "你好世界", "speaker": "default" }
```
音乐：
```json
POST /api/audio/music
{ "prompt": "epic orchestral cinematic", "duration": 60 }
```

## 调用方式

### 方式 A：Agent CLI（命令行）
```bash
# 生成图片
python agent_cli.py generate "a cat on a rooftop" --width 512 --height 512

# 分镜编排
python agent_cli.py storyboard "镜头1描述, 镜头2描述"

# 创建角色
python agent_cli.py entity add 角色 --name "小明"

# 列出实体
python agent_cli.py entity list

# TTS
python agent_cli.py audio tts "你好世界"

# 工作流执行
python agent_cli.py workflow execute "node-1,node-2"
```

### 方式 B：MCP Server（Agent 工具调用）
启动 MCP Server：
```bash
python mcp_server.py
```
MCP 客户端配置（Claude Desktop / VS Code）：
```json
{
  "mcpServers": {
    "infinite-canvas": {
      "command": "python",
      "args": ["path/to/mcp_server.py"],
      "cwd": "path/to/infinite-canvas/agent"
    }
  }
}
```
工具名称：`generate_image`, `generate_video`, `storyboard`, `create_entity`, `list_entities`, `delete_entity`, `execute_workflow`, `tts`, `music`, `canvas_status`

### 方式 C：直接 HTTP（REST）
API 后端运行在 `http://127.0.0.1:5180`，可直接用 `curl` / `fetch` 调用任意端点。

## 前置条件

1. Canvas API 服务已启动：`cd agent && python main.py`（监听 :5180）
2. ComfyUI 服务已启动：默认 `http://127.0.0.1:8188`
3. 模型已下载到 `C:\ai_comfyui_dd\models`（参考 `references/shared_models.md`）
