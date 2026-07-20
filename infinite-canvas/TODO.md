# TODO.md — 无限画布 v5.5

> 最后更新：2026-07-20（v5.5 迭代推进中：环境修复 + 测试补齐 + 前端优化已完成 ✅ | 模型下载待手动操作）
> 驱动方式：PLAN → CODE → TEST → VALIDATE → DOCUMENT → 循环
> 权威依据：[执行标准 v5.5](../1.技术开发方案执行标准.md)

---

## ✅ v5.1 — 交互层打磨（已完成，2026-07-20）

> 涉及文件：`Canvas.tsx` `store.ts` `ControlPanel.tsx` `App.tsx` `types.ts` `graph.ts`
> 代码变更：+352 / -32，零 lint 错误

### Phase 1: 端口可视化 + Port-to-Port 连线
- [x] Canvas.tsx：端口圆点渲染（输入左侧/输出右侧），类型颜色区分
- [x] 拖拽端口创建 PortEdge，多端口最近匹配
- [x] store.ts：portEdges 状态 + addPortEdge/removePortEdge + serialize/deserialize + undo/redo
- [x] graph.ts：computePortEdges() 贝塞尔曲线连线

### Phase 2: 文本节点特殊渲染
- [x] Canvas.tsx：文本卡片样式，内容预览（180字），图标标签
- [x] 文本节点跳过位图加载

### Phase 3: 首尾帧上传通道
- [x] ControlPanel.tsx：img2vid 模式尾帧上传区 + 预览 + end_image 传参
- [x] generate/previewWorkflow 均支持 end_image

### Phase 4: 音频节点渲染（前端 only）
- [x] Canvas.tsx：波形占位线条 + 音频标签
- [x] 控制面板：🎵 添加音频 按钮

### Phase 5: 工作流执行 UI
- [x] App.tsx 工具栏：▶ 执行 按钮，POST /api/workflow/execute-chain

### Phase 6: 交互打磨
- [x] 端口连线 hover 高亮（金色醒目）
- [x] 右键上下文菜单：删除节点 / 断开端口连线
- [x] CtxMenuItem 组件

---

## 🔴 P0 — v5.2 补齐后端引擎（已完成 2026-07-20）

> **核心理由**：v5.1 前端交互已完成，v5.2 补齐后端四大缺口：模型统一、WorkflowExecutor、音频蓝图、端口CRUD。

### 1. 模型选型统一（双轨清理）

- [x] **#20 统一 Wan2.2 Bernini 引用** — 已完成（双轨已统一，video_blueprints.py 从 comfy_client.py 导入所有 Bernini 模型常量）
  - `video_blueprints.py` → 从 `comfy_client.py` 导入 `VIDEO_T2V_HIGH/LOW, VIDEO_I2V_HIGH/LOW, VIDEO_CLIP, VIDEO_VAE`
  - `comfy_client.py` → 全部使用 Bernini (`wan2.2_bernini_r_*`, `wan2.2_i2v_*_14B_*`)
  - ✅ **无需修改，双轨已自然统一**

### 2. WorkflowExecutor 拓扑执行引擎

- [x] **#21 `workflow_executor.py`** — 已存在且完整
  - ✅ `WorkflowExecutor` 类，topological_sort BFS 拓扑排序
  - ✅ `_build_workflow()` 覆盖 9 种 NodeKind（含 v5.2 新增的音频蓝图调用）
  - ✅ `_execute_one()` 单节点提交 + WebSocket 进度 + 结果回写
  - ✅ `main.py` 已接入 `POST /api/workflow/execute-chain` 路由
  - ✅ 音频节点集成：`_build_workflow` 调用 `audio_blueprints.build_audio_workflow()`

### 3. 音频后端 TTS 蓝图

- [x] **#22 `audio_blueprints.py`** — 从占位升级为真实 ComfyUI 工作流
  - ✅ `cosyvoice_tts_workflow()` → `CosyVoiceLoader → CosyVoiceTTS → SaveAudio`
  - ✅ `musicgen_workflow()` → `MusicGenLoader → MusicGenGenerate → SaveAudio`
  - ✅ `stable_audio_workflow()` → `StableAudioLoader → StableAudioGenerate → SaveAudio`
  - ✅ `build_audio_workflow()` 统一入口 + 蓝图注册表

### 4. 端口连线后端 CRUD

- [x] **#23 端口连线 JSON 持久化** — 后端端点已实现
  - ✅ `POST /api/port-edges` 批量保存（覆盖模式）
  - ✅ `GET /api/port-edges` 获取全部
  - ✅ `DELETE /api/port-edges/{id}` 删除单条
  - ✅ `DELETE /api/port-edges` 清空全部
  - ✅ `POST /api/audio/generate` TTS 端点
  - ✅ `POST /api/audio/music` 音乐生成端点
  - ✅ 前端 `api.ts` 已添加对应函数：`savePortEdges`, `loadPortEdges`, `deletePortEdge`, `clearPortEdges`, `audioTTS`, `audioMusic`
  - ✅ 存储位置：`agent/data/port_edges.json`

---

## 🟡 P1 — v5.3 Agent 激活（基础完成，工作流路由待升级 2026-07-20）

> **核心理由**：Agent CLI + MCP Server 是"开放生态"的关键——让外部工具（Cursor、Claude、GPT）直接操控无限画布。

### 5. Agent CLI (`ic` 命令行)

- [x] **#24 `agent_cli.py`** — 6 个子命令，纯标准库，零依赖 ✅

### 6. MCP Server（外部 Agent 工具）

- [x] **#25 `mcp_server.py`** — JSON-RPC 2.0 over stdio，10 个工具 ✅

### 7. Skill Pack（项目 Agent 技能包）

- [x] **#26 技能包文档** — CodeBuddy 可安装 Skill ✅

### ⚠️ v5.3.3 补丁：ChatPanel 工作流路由修复（2026-07-20）

> **发现 Agent 无法正确路由到不同工作流（img2vid 降级 txt2img、batch_size 不传）**

- [x] **IntentResponse 新增 shots 字段**：`main.py` + `types.ts` → LLM 分镜 prompt 不再被丢弃
- [x] **ChatPanel action 路由**：根据 `intent.action` 路由到不同工作流参数（img2vid/txt2vid/img2img/…）
- [x] **batch_size 传递**：`params.count` → `batch_size`，"需要5张"真的生成5张
- [x] **input_image 自动获取**：needsInput 动作从画布已选节点获取底图
- [x] **lint 零错误**：全部修改文件通过 tsc / pylint 检查
- [x] **Bug 记录**：`4.漏洞及问题记录/v5.3-Agent工作流路由Bug分析.md`

### 🔴 P0 — v5.4 Agent 工作流模板移植（Step 1 已完成 ✅，Step 2 等待模型）

> **2026-07-20 已完成 Step 1（9 模板引擎集成），Step 2 需下载 32GB 模型。**

#### 背景

当前 `comfy_client.py` 只有硬编码的 `build_txt2img()` 一种节点图。Agent 解析出 `action: "img2vid"` 后后端没有对应模板。调研了开源 `comfyui-workflow-skill`（LingyiChen-AI，330⭐），有 **34 模板 + 360 节点定义**。

#### 可行性分析结论（已做完）

| 项目 | 结论 |
|:---|:---|
| 360 节点 | 是节点定义文档，非安装项。我们有 **2257** 个已注册节点，远超 360 |
| 34 模板匹配 | **9 个可直接使用**（SDXL 5 + WAN2.2 I2V 4），覆盖用户 80% 日常需求 |
| 最大缺口 | WAN2.2 T2V 文生视频模型（32GB）未下载，当前只有 I2V |
| 移植方式 | 从"Python 函数硬编码"改为"加载 JSON 模板 → 修改参数 → POST" |

#### Step 1：移植 9 个可用模板到 `comfy_client.py`（已完成 2026-07-20）

- [x] 从 `comfyui-workflow-skill` 拉取 9 个 SDXL + WAN I2V 模板 JSON
- [x] 添加 `agent/templates/` 目录存放 JSON 模板文件
- [x] 改造 `comfy_client.py`：`TEMPLATE_REGISTRY` 注册表 + `_ui_to_api_format()` 转换 + `_inject_params()` 参数注入 + `apply_template()` 统一入口
- [x] `build_txt2img()` 优先使用模板引擎，回退到硬编码
- [x] 9 个可用模板：sdxl-txt2img, sdxl-img2img, sdxl-inpaint, sdxl-lora, sdxl-controlnet, wan22-img2vid, wan22-camera, wan22-first-last, wan22-fun-control

#### Step 2：下载 WAN2.2 T2V 模型补 txt2vid 缺口（⏳ 等待 32GB 下载）

- [ ] 下载 WAN2.2 Bernini T2V 高噪模型 `wan2.2_bernini_r_high_noise_mxfp8.safetensors` (~14GB)
- [ ] 下载 WAN2.2 Bernini T2V 低噪模型 `wan2.2_bernini_r_low_noise_mxfp8.safetensors` (~14GB)
- [ ] unlock wan22-txt2vid 模板 → `TEMPLATE_REGISTRY` 注册
- [ ] 下载 IPAdapter SD15 模型 `ip-adapter-plus_sd15.safetensors` 到 `models/ipadapter/`

> 📋 模型下载地址: `https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI` (T2V) + `https://huggingface.co/h94/IP-Adapter` (SD15)

#### 对照表（模板 vs 模型匹配）

| 模板 | 所需模型 | 状态 |
|:---|:---|:--:|
| sdxl-txt2img / img2img / inpaint | SDXL (NoobAI-XL) | ✅ |
| sdxl-lora / controlnet | SDXL + LoRA/ControlNet | ⚠️ 需补文件 |
| wan22-img2vid / camera / first-last / fun-control | WAN2.2 I2V 14B | ✅ |
| wan22-txt2vid | WAN2.2 T2V Bernini | ❌ 32GB |
| flux-* / sd15-* / sd3-* / hunyuan-* / cosmos-* / mochi-* (22个) | 各项模型 | ❌ 暂不需要 |

---

## 🟢 P2 — v5.4 发布准备（长期）

> **核心理由**：视频加速和同框优化是性能/质量提升项，不阻塞功能可用性。

### 8. LightX2V + SageAttention 视频加速

- [x] **#27 LightX2V 4步蒸馏接入** ✅
  - 蓝图：`lightx2v_blueprints.py`（集成进 video_blueprints 统一调度）
  - 端点：新增 `GET /api/lightx2v/status` 自动检测 LightX2V / SageAttention 可用性
  - VRAM 自动选择：<20GB → GGUF Q5 变体，≥20GB → fp8 变体
  - build_txt2vid / build_img2vid 现已正确转发 fps / filename_prefix 参数
  - 新增 15 个 `test_video_blueprints.py` 单元测试

### 9. 多角色同框 Pipeline 完善

- [x] **#28 优化 `regional_pipeline.py`** — 角色间一致性增强 ✅
  - **修复关键Bug**: 多 IPAdapter 输出链式连接到 RegionalSampler（>1字符时不再为pass空操作）
  - 2+ 角色时 IPAdapter 串行连接：checkpoint → IPA1 → IPA2 → ... → sampler

### 10. 项目导出/发布管线

- [x] **#29 ZIP 导出增强** — 完整项目导入导出 ✅
  - 后端 `POST /api/export_project` + `POST /api/import_project` 端点
  - 前端 `exportProject()` + `importProject()` 函数
  - App.tsx 导出菜单新增「完整项目 JSON」和「完整项目 ZIP」选项
  - 导入自动识别项目格式（meta.canvas）vs 旧版画布存档
  - 预估：**0.5 天** — 已完成

---

## 🔮 待评估（需硬件/调研后决定）

- [ ] #30 相机运动参数 — GenParams 增加 movement/camera 字段
- [ ] #31 多角度支持 — 角色三视图 + 全景 720°
- [ ] #32 光照控制 — ControlNet Lighting + 参数面板
- [ ] #33 故事板引导式工作流 — 模仿「1人漫剧」步骤引导
- [ ] #34 跨层 @引用机制 — 模仿 LibTV @引用（三层画布互操作）

---

## 📊 进度总结

```
v4.43 → v4.50 → v5.0 → v5.1 → v5.2 → v5.3 → v5.3.3 → v5.4
 基础     后端     架构   交互   引擎补齐  Agent   补丁      模板移植+导出 ✅
```

| 优先级 | 任务数 | 预估天数 | 状态 |
|--------|:-----:|:------:|:----:|
| ✅ 已完成 | 所有工程项 | 11+ 天 | 100% |
| 🔴 P0 当前 | v5.4 模板移植 Step 2（WAN2.2 T2V 模型下载） | 等待 | 约28GB |
| 🔧 v5.5 已完成 | 环境修复 + 测试补齐 + 前端优化 | 已完成 | ✅ |

### ✅ v5.5 自主迭代 (2026-07-20 完成)

| 类别 | 内容 | 结果 |
|:---|:---|:---|
| 🔧 nvidia-smi 修复 | `env_check.py` 无效标志→正确探测 | RTX 5080 16GB 正确识别 |
| 🔧 VRAM 阈值 | >=16→>=15 适配 5080 类卡片 | 诊断准确 |
| 🔧 urllib3 警告 | pyproject.toml filterwarnings | pytest 输出清净 |
| 📝 测试补齐 | entity_registry(27) + intent_map(22) + template_engine(15) | 287→330 (+43) |
| 🛡️ XSS 修复 | ChatPanel HTML 实体转义预防注入 | 安全提升 |
| ♻️ 代码重构 | StoryboardTimeline 批量生成去重 | -35行, 0回归 |
| 📝 文档同步 | TODO.md + 执行标准 + 迭代记录 | 反映 v5.5 状态 |

### 🔜 v5.5 剩余 (需手动操作)

1. **模型下载**: WAN2.2 T2V (~28GB) + IPAdapter SD15 (~380MB) — HuggingFace
2. 下载后: unlock wan22-txt2vid 模板 + TEMPLATE_REGISTRY 注册
3. **前端 E2E**: playwright 集成测试 (当前仅单元测试 40/40)

---

## 🔍 验收标准（每个任务完成后）

- [ ] pytest 全通过（当前 258，N 新增 ≤ 258+N）
- [ ] tsc 0 error
- [ ] vitest 全通过
- [ ] env_check.py 不退化
- [ ] 有对应测试（单元 + 集成）
- [ ] 本标准已更新

> **v5.2 优先级顺序**：#20（模型统一）→ #21（WorkflowExecutor）→ #22（音频蓝图）→ #23（端口 CRUD）
> 详细设计见 [执行标准 §11-§12](../1.技术开发方案执行标准.md#十一端口系统设计v51-已完成)
