# 无限画布 · Infinite Canvas

自然语言驱动的 AI 无限画布：输入一句中文/英文描述 → 意图解析 → 本机 ComfyUI 真实出图 →
在可平移/缩放/拖拽的无限画布上以图片节点呈现。支持文生图、图生图、批量生成、参数调节、
撤销/重做与本地存档。

```
自然语言  →  /api/intent (DeepSeek v4，退化自愈兜底)  →  结构化意图
          →  /api/generate (意图→模板→参数→ComfyUI 真实出图)
          →  /api/image (同源代理 ComfyUI /view)  →  Konva 画布节点
```

## 架构

| 层 | 技术 | 目录 |
|---|---|---|
| 前端 | Vite + React 18 + TypeScript(strict) + Konva + zustand | `frontend/` |
| 后端 | FastAPI + uvicorn（纯 urllib 调 ComfyUI，规避代理 502） | `agent/` |
| 生成引擎 | 本机原生 ComfyUI（Qwen-Image 2.0 fp8 / NoobAI-XL） | 外部 :8188 |
| 意图 LLM | DeepSeek `deepseek-v4-flash`（离线兜底 Ollama qwen2.5） | — |

## 功能

- **文生图**：自然语言 → 高质量出图；模型可选（自动 / Qwen-Image / NoobAI-XL）
- **图生图**：上传图片或选中画布节点作为输入 + `denoise` 重绘幅度
- **视频生成（Phase 9）**：文生视频 / 图生视频（Wan2.2 双噪蒸馏采样，帧数 17–81 / FPS 8–30，推荐 832×480）；画布视频节点用 `<video>` 原生播放 mp4，并抽首帧作静态缩略图
- **参数面板**：画幅（方/横/竖）、步数、CFG、批量张数（1~4）、负向提示词、随机/固定种子
- **无限画布**：拖空白平移、以指针为中心滚轮缩放（0.2~4x）、节点拖拽摆放、小地图导航
- **编辑**：撤销 `Ctrl+Z` / 重做 `Ctrl+Shift+Z` / 删除 `Del`
- **存档**：画布自动本地保存（localStorage）+ 导出/导入 JSON

## 快速开始

前置：本机 ComfyUI 运行于 `:8188`；`agent/.env` 配置 `DEEPSEEK_API_KEY`（可选，缺失时走中文兜底）。

```powershell
# 1) 后端虚拟环境（首次）
python -m venv agent/.venv
agent/.venv/Scripts/pip install -r agent/requirements.txt

# 2) 前端依赖（首次）
cd frontend; npm install; cd ..

# 3) 一键启动（后端 :8000 + 前端 :5173）
./start.ps1
```

浏览器打开 <http://localhost:5173>：左侧输入描述 → 选参数 → 点「生成」。

## API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/status` | 服务与 ComfyUI 连通状态 |
| POST | `/api/intent` | `{user_input}` → 结构化意图 |
| POST | `/api/generate` | `{intent, wait, seed, batch_size, input_image, denoise, frames, fps, ...}` → 出图/视频文件名 |
| POST | `/api/upload` | `{filename, data_base64}` → ComfyUI input 文件名（图生图输入） |
| GET | `/api/image/{filename}` | 代理 ComfyUI 输出图（防路径穿越） |

## 测试

```powershell
./test.ps1          # 一键：后端 pytest + 前端构建 + vitest
```

分别运行：

```powershell
# 后端
cd agent; .venv/Scripts/python -m pytest -q
# 前端
cd frontend; npm run test        # 单元
npm run build                     # tsc strict + 打包
```

CI：`.github/workflows/ci.yml`（push/PR 自动跑后端 pytest + 前端构建与 vitest）。

## 目录

```
infinite-canvas/
├─ agent/            # FastAPI 后端
│  ├─ main.py        # 路由：status/intent/generate/upload/image
│  ├─ deepseek.py    # 意图解析（DeepSeek + 退化自愈兜底）
│  ├─ intent_map.py  # 意图→模板→workflow
│  ├─ comfy_client.py# ComfyUI 工作流构造 + 提交 + 取图 + 上传
│  └─ test_agent.py  # pytest
├─ frontend/         # React + Konva 画布
│  └─ src/{App,Canvas,ControlPanel,api,store,types}.tsx/ts
├─ start.ps1  test.ps1
└─ .github/workflows/ci.yml
```
