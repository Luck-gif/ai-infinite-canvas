# TODO.md — 无限画布 v5.2 任务队列

> 最后更新：2026-07-20 (v5.0 LightX2V 视频加速完成)
> 驱动方式：PLAN → CODE → TEST → VALIDATE → DOCUMENT → 循环
> 所有人请按优先级从上到下执行。

---

## ✅ P0 — v4.50 后端增强（48h 内，硬件升级前）

- [x] **#1 创建 `entity_registry.py`** — 角色/场景/道具/风格结构化注册表（JSON Schema）✅ 2026-07-20
- [x] **#2 新增 `/api/entities/*` CRUD** — 创建/读取/更新/删除实体 ✅ 2026-07-20
- [x] **#3 创建 `consistency_manager.py`** — StoryDiffusion 17 合 1 封装，按场景路由 ✅ 2026-07-20
- [x] **#4 创建 `workflow_planner.py`** — LLM 辅助工作流规划（蓝图匹配+DAG构造）✅ 2026-07-20
- [x] **#5 创建 `workflow_assembler.py`** — 蓝图参数填入+一致性策略自动注入+量化匹配 ✅ 2026-07-20
- [x] **#6 新增 `/api/workflows/generate` + `/api/storyboard/plan` + `/api/blueprints`** — 三个新端点 ✅ 2026-07-20
- [x] **#7 创建 `video_blueprints.py`** — Wan2.2 T2V/I2V (fp8/GGUF) + LTX 蓝图封装 ✅ 2026-07-20
- [x] **#7a 创建 `pipeline_orchestrator.py`** — 7-Agent 管线编排器（意图→蓝图→一致性→组装→校验→提交）✅ 2026-07-20
- [x] **#7b 前端面板集成** — WorkflowGeneratePanel + StoryboardPanel + 工具栏 ✅ 2026-07-20
- [x] **#7c 三层画布底层** — CanvasLayer 类型 + LayerPanel 切换组件 + Store 集成 ✅ 2026-07-20
- [x] **#7d API 扩展** — `/api/pipeline/run` + `/api/pipeline/storyboard` 管线端点 ✅ 2026-07-20
- [x] **#7e E2E 测试补齐** — 9 个管线端到端测试 (165 tests total) ✅ 2026-07-20

✅ **v4.50 全面完成！** 后端 + 前端面板 + 三层画布 + PipelineOrchestrator + 165 测试全绿。

## ✅ P1 — v5.0 前端三层画布（全部完成！）

- [x] **#8 ControlPanel.tsx 拆分** — 层级上下文提示条 + SegBtn 层级色彩标记 (v4.51) ✅
- [x] **#9 Canvas.tsx 重构** — 三种视图模式切换：节点过滤 + 层级统计栏 (v4.55) ✅
- [x] **#10 项目画布** — EntityBrowserPanel + 实体加载到策划层 + 描述字段 (v4.56) ✅
- [x] **#11 故事板画布** — 分镜编排 + 时间轴(拖拽排序) + 资产引用(实体绑定) + 批量生成 + Canvas 联动 (v4.57-v4.59) ✅
- [x] **#12 工作流画布** — 只读→可编辑：NodeEditPanel 参数编辑/重新生成/管线提交 (v4.54) ✅
- [x] **#13 types.ts + store.ts + api.ts 扩展** — 实体类型/层级映射/CanvasNode扩展 (v4.54-v4.56) ✅
- [x] **#14 创建 `text_production.py`** — 多 Agent 写作管线（大纲→章节→剧本→角色卡→提示词）(v4.53) ✅

## 🟢 P2 — v5.1 发布前增强（进行中）

- [x] **#15 LightX2V + SageAttention** 视频加速管线 ✅ 2026-07-20
- [x] **#16 多角色同框** Regional Pipeline ✅ 2026-07-20
  - `regional_pipeline.py` — Regional Sampler + 多 IPAdapter + 注意力掩码
  - 4种布局：水平2分/垂直2分/2×2四宫格/自由比例
  - [A]/[B] token 提示词解析 + 区域坐标计算
  - `/api/regional/generate` 端点 + GenerateRequest 模型
  - `intent_map.py` regional action + _build_regional 路径
  - 前端 GenMode 新增 'regional' + RegionalCharacterSlot 接口
  - 19 个新 pytest
- [x] **#17 一致性自动审查** — CLIP embedding 跨节点对比 ✅ 2026-07-20
  - `embedding_service.py` — CLIP ViT-L/14 嵌入提取 + 余弦相似度
  - `cross_node_consistency()` + `batch_consistency_summary()` + grade(A/B/C/D)
  - `/api/review/consistency` 端点：批量节点相似度审查
  - 阈值 0.75 通过，按 face/style/scene 分类统计
- [x] **#18 IP 相似度预警** — 角色嵌入库+阈值检测 ✅ 2026-07-20
  - `store_entity_embedding()` / `get_entity_embedding()` 嵌入索引持久化
  - `check_ip_similarity()` 三级预警（通过/轻度偏离/严重偏离）
  - `/api/guard/ip-check` + `/api/guard/ip-register` + `/api/guard/ip-library` 端点
  - 21 个新 pytest（含嵌入提取/一致性审查/IP预警）
- [x] **#19 基础审核** — 节点质量标记 + 批量浏览 ✅ 2026-07-20
  - `NodeQualityStatus`: unreviewed | approved | rejected | needs_regeneration
  - `/api/review/quality` 单节点标记 + `/api/review/batch-quality` 批量标记
  - `/api/review/quality-stats` 审核统计端点
  - CanvasNode → qualityStatus/qualityNote 字段
  - store → qualityFilter 过滤器 + markNodeQuality/batchMarkQuality
  - App.tsx: 顶部工具栏审核状态下拉过滤
  - NodeEditPanel: 审核快捷按钮（✅通过/❌驳回/🔄重生成）

---

## 📋 v4.56 当前能力清单

### API (27 endpoints)
```
POST /api/intent              意图解析（DeepSeek v4）
POST /api/generate            文生图/图生图/重绘/扩图
POST /api/video               文生视频/图生视频
POST /api/consistency         一致性生成（4 模式）
POST /api/storyboard          分镜并行生成
POST /api/workflow/*          工作流 CRUD
GET  /api/workflows           工作流列表
POST /api/workflows/generate  NL→工作流自动组装
POST /api/storyboard/plan     分镜规划
GET  /api/blueprints          蓝图库查询
POST /api/pipeline/run        多Agent管线执行
POST /api/pipeline/storyboard 故事板管线
POST /api/entities/*          实体注册表 CRUD
GET  /api/entities            实体列表（按kind过滤）
GET  /api/entities/search     实体搜索
GET  /api/entities/{id}/prompt 实体提示词
POST /api/text/produce        多Agent写作管线
GET  /api/progress/{id}       实时进度
POST /api/export/zip          ZIP 导出
GET  /api/env                 环境诊断
GET  /api/health              健康检查
```

### 测试
```
258 pytest — 全绿
TypeScript: tsc 0 error
```

### 进度
```
P0: 6/6 ✅  P1: 7/7 ✅  P2: 5/5 ✅  🎉
总版本: v5.3 · P0/P1/P2 全部完成！
```

### 新增模块（v4.50-v5.1）
```
pipeline_orchestrator.py   — 7-Agent管线编排器
workflow_assembler.py      — 蓝图组装引擎
video_blueprints.py        — 视频蓝图库 (+ LightX2V 集成)
consistency_manager.py     — 一致性策略路由
entity_registry.py         — 实体注册表
text_production.py         — 多Agent写作管线
lightx2v_blueprints.py     — LightX2V 4步/2步蒸馏蓝图 (v5.0)
sage_attention.py          — SageAttention 量化加速配置 (v5.0)
regional_pipeline.py       — 多角色同框 Regional Sampler (v5.1)
embedding_service.py        — CLIP 嵌入服务 + 一致性审查 + IP 预警 (v5.2)
+ 审核 API 端点             — quality/batch-quality/quality-stats (v5.3)
+ 质量过滤 UI               — App.tsx 下拉 + NodeEditPanel 标记 (v5.3)
LayerPanel.tsx              — 三层画布切换
WorkflowGeneratePanel.tsx   — NL→工作流生成面板
StoryboardPanel.tsx         — 分镜规划面板
NodeEditPanel.tsx           — 节点属性编辑（重新生成/管线提交/预览）
EntityBrowserPanel.tsx      — 实体浏览与画布加载
StoryboardTimeline.tsx      — 故事板时间轴（拖拽排序+资产绑定+批量生成）
```

---

## 📋 硬件升级后的验证清单

- [ ] 新 GPU 加载 → `python env_check.py` 全项通过
- [ ] Wan2.2 fp8 → fp16 迁移（质量提升 15-25%）
- [ ] Qwen-Image 2.0 加载更大变体
- [ ] 全量回归：`pytest tests/ -q` + `npx vitest run` + `npx tsc --noEmit`
- [ ] E2E 全链路：`pytest tests/e2e/test_pipeline.py -q`

---

## ✅ 已完成（v4.43 之前）

- [x] 12 种 action 全覆盖意图解析
- [x] IPAdapter 四类一致性（角色/风格/场景/道具）
- [x] 文生视频 + 图生视频（Wan2.2）
- [x] 分镜编排 + 时间轴 + 视频拼接
- [x] ZIP 导出 + 视口裁剪 + 懒加载
- [x] 工作流库 CRUD + LLM 辅助创建
- [x] env_check.py 环境自诊断
- [x] 项目文件清理（临时文件/日志/冗余代码）
- [x] 模型选型锁定
- [x] v5.0 执行标准制定
- [x] 被误删文件恢复（git checkout HEAD）
- [x] 调研报告归档（分析调研目录）
