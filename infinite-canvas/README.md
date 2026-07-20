# 无限画布 · Infinite Canvas v5.0

**LLM 驱动的 AI 漫剧全链路生产平台**

```
自然语言/小说 → DeepSeek v4 意图解析 → 34+ 工作流蓝图组装
             → ComfyUI 出图/出视频 → Konva 三层画布呈现
```

## 快速开始

```powershell
# 1. 环境诊断
cd agent && python env_check.py

# 2. 配置 API Key（首次）
cp agent/.env.example agent/.env  # 填入 DEEPSEEK_API_KEY

# 3. 安装依赖
cd agent && pip install -r requirements.txt
cd ../frontend && npm install && cd ..

# 4. 启动
start agent: cd agent && uvicorn main:app --port 5180
start frontend: cd frontend && npm run dev

# 访问 http://localhost:5173
```

## 架构

| 层 | 技术 | 端口 |
|---|---|---|
| 前端 | React 18 + TypeScript(strict) + Konva + Zustand + Vite | 5173 |
| Agent | FastAPI + Pydantic（urllib 直调 ComfyUI） | 5180 |
| 引擎 | ComfyUI（2257 节点 + 9 自定义） | 8188 |
| LLM | DeepSeek v4-flash（主）/ Ollama qwen2.5:14b（兜底） | — |

## API（19 端点）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/env` | 环境诊断 |
| POST | `/api/intent` | 自然语言 → 结构化意图 |
| POST | `/api/generate` | 意图 → 工作流 → 12 action 出图 |
| POST | `/api/video` | 文生视频 / 图生视频 |
| POST | `/api/consistency` | 角色/风格/场景/道具 4 模式 |
| POST | `/api/storyboard` | 分镜并行生成 |
| GET | `/api/progress/{id}` | WebSocket 进度 |
| POST | `/api/workflow/*` | 工作流库 CRUD |
| POST | `/api/export/zip` | ZIP 打包导出 |
| GET | `/api/image/{filename}` | 代理 ComfyUI 输出 |

## 功能

- **12 种 action**：txt2img / img2img / inpaint / outpaint / lora / controlnet / 4 一致性模式 / txt2vid / img2vid
- **画布**：无拖拽/缩放/框选/连线/血缘图/懒加载/视口裁剪
- **视频**：Wan2.2 双噪蒸馏（81 帧/FPS 8-30）/ 视频节点 mp4 播放 + 分镜时间轴 + 视频拼接
- **存档**：localStorage 自动保存 + JSON 导出 + ZIP 打包

## 开发依据

**唯一标准 → [`../1.技术开发方案执行标准.md`](../1.技术开发方案执行标准.md)**
含模型选型、代码规范、测试、循环开发、部署、合规。开发前必读。

## 许可证

本项目 Apache 2.0。模型许可证详见[执行标准第十章](../1.技术开发方案执行标准.md#十合规与许可证)。
