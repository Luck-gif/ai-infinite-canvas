# 无限画布 · Infinite Canvas v5.3

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

## API（27+ 端点）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/env` | 环境诊断 |
| POST | `/api/intent` | 自然语言 → 结构化意图 |
| POST | `/api/generate` | 意图 → 工作流 → 14 action 出图/出视频 |
| POST | `/api/video` | 文生视频 / 图生视频 |
| POST | `/api/consistency` | 角色/风格/场景/道具 4 模式一致性 |
| POST | `/api/storyboard` | 分镜并行生成 |
| POST | `/api/storyboard/plan` | 分镜自动规划 |
| GET | `/api/progress/{id}` | WebSocket 进度 |
| POST | `/api/workflow/*` | 工作流库 CRUD |
| POST | `/api/workflows/generate` | NL→工作流自动组装 |
| GET | `/api/blueprints` | 蓝图库查询 |
| POST | `/api/pipeline/run` | 多Agent管线执行 |
| POST | `/api/pipeline/storyboard` | 故事板管线 |
| POST | `/api/entities/*` | 实体注册表 CRUD (7 endpoints) |
| POST | `/api/text/produce` | 多Agent写作管线 |
| POST | `/api/regional/generate` | 多角色同框生成 |
| POST | `/api/review/consistency` | 一致性审查 |
| POST | `/api/review/quality` | 节点质量标记 |
| POST | `/api/review/batch-quality` | 批量质量标记 |
| GET | `/api/review/quality-stats` | 审核统计 |
| POST | `/api/guard/ip-check` | IP相似度检测 |
| POST | `/api/guard/ip-register` | IP嵌入注册 |
| GET | `/api/guard/ip-library` | IP嵌入库状态 |
| POST | `/api/export/zip` | ZIP 打包导出 |
| GET | `/api/image/{filename}` | 代理 ComfyUI 输出 |

## 功能

- **14 种 action**：txt2img / img2img / inpaint / outpaint / lora / controlnet / 4 一致性模式 / txt2vid / img2vid / regional / lightx2v
- **画布**：三层切换（策划/生成/输出）/ 平移/缩放/框选/连线/血缘图/懒加载/视口裁剪
- **视频**：Wan2.2 (81帧) + LightX2V 蒸馏加速 (2-4步) / 视频节点播放 + 分镜时间轴 + 视频拼接
- **实体系统**：角色/场景/道具/风格 CRUD + 实体浏览器 + 画布引用绑定
- **工作流**：用户自定义保存/加载 + NL→蓝图组装 + DAG可视化
- **管线**：7-Agent 编排 / 多Agent写作 / 多角色同框 / StoryDiffusion 17合1 一致性
- **审核**：节点质量四态标记 / 批量审核 / CLIP一致性审查 / IP相似度预警
- **存储**：localStorage 自动保存 + JSON 导出 + ZIP 打包

## 测试

**258 pytest + 40 vitest 全绿 · tsc 0 error · Python 3.12**

## 开发依据

**唯一标准 → [`../1.技术开发方案执行标准.md`](../1.技术开发方案执行标准.md)**
含模型选型、代码规范、测试、循环开发、部署、合规。开发前必读。

## 许可证

本项目 Apache 2.0。模型许可证详见[执行标准第十章](../1.技术开发方案执行标准.md#十合规与许可证)。
