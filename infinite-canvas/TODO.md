# TODO.md — 无限画布 v5.0 任务队列

> 最后更新：2026-07-20
> 驱动方式：PLAN → CODE → TEST → VALIDATE → DOCUMENT → 循环
> 所有人请按优先级从上到下执行。

---

## 🔴 P0 — v4.50 后端增强（48h 内，硬件升级前）

- [ ] **#1 创建 `entity_registry.py`** — 角色/场景/道具/风格结构化注册表（JSON Schema）
- [ ] **#2 新增 `/api/entities/*` CRUD** — 创建/读取/更新/删除实体
- [ ] **#3 创建 `consistency_manager.py`** — StoryDiffusion 17 合 1 封装，按场景路由
- [ ] **#4 创建 `workflow_planner.py`** — LLM 辅助工作流规划（蓝图匹配+DAG构造）
- [ ] **#5 创建 `workflow_assembler.py`** — 蓝图参数填入+一致性策略自动注入+量化匹配
- [ ] **#6 新增 `/api/workflows/generate`** — 自然语言→完整 ComfyUI JSON 端点
- [ ] **#7 创建 `video_blueprints.py`** — WanVideoWrapper + LTXVideo 蓝图封装

## 🟡 P1 — v5.0 前端三层画布（硬件升级后 3-5 天）

- [ ] **#8 ControlPanel.tsx 拆分** — 12 模式面板 → 三层画布各自的上下文工具栏
- [ ] **#9 Canvas.tsx 重构** — 支持项目/故事板/工作流 三种视图模式切换
- [ ] **#10 项目画布** — 角色/场景/道具/风格节点 + 属性面板
- [ ] **#11 故事板画布** — 分镜编排 + 时间轴 + 资产引用 + 批量生成
- [ ] **#12 工作流画布** — 只读→可编辑：拖拽节点/连线/编辑属性/提交执行
- [ ] **#13 types.ts + store.ts + api.ts 扩展** — 新增实体/分镜/工作流编辑类型和状态
- [ ] **#14 创建 `text_production.py`** — 多 Agent 写作管线（大纲→章节→剧本→角色卡→提示词）

## 🟢 P2 — v5.1 发布前增强

- [ ] **#15 LightX2V + SageAttention** 视频加速管线
- [ ] **#16 多角色同框** Regional Pipeline（Regional Sampler + 角色 IPAdapter）
- [ ] **#17 一致性自动审查** — CLIP embedding 跨节点对比
- [ ] **#18 IP 相似度预警** — 角色嵌入库+阈值检测
- [ ] **#19 基础审核** — 节点质量标记 + 批量浏览模式

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
