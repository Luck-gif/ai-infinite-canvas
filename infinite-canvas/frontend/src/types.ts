// 无限画布 · 前端类型定义（对齐 agent 后端契约 §8.1 / §6.0）

/** §8.1.4 结构化意图 */
export interface Intent {
  action: string;
  subject: string;
  style: string;
  elements: string[];
  params: {
    model?: string;
    width?: number;
    height?: number;
    steps?: number;
    cfg?: number;
    prompt?: string;
    negative_prompt?: string;
    [k: string]: unknown;
  };
}

/** /api/intent 响应 */
export interface IntentResponse extends Intent {}

/** /api/generate 响应 */
export interface GenerateResponse {
  template_id: string;
  validated: boolean;
  prompt_id: string;
  status: string;
  images: string[];
  issues: string[];
  meta: Record<string, unknown>;
  workflow?: WorkflowGraph | null; // 前端无限画布内节点图（comfy_client.workflow_to_graph）
}

/** 工作流节点图（前端无限画布内可视化，后端 workflow_to_graph 生成） */
export interface WorkflowPort {
  name: string;     // 输入槽名（如 model / positive）
  from: string;     // 源节点 id
  from_slot: number; // 源输出槽号
}
export interface WorkflowNode {
  id: string;
  type: string;      // ComfyUI class_type
  title: string;     // 中文可读标题
  category: string;  // model/sample/cond/latent/vae/io/other
  pos: { x: number; y: number };
  input_links: WorkflowPort[];
  values: Record<string, string>; // 关键字面参数（seed/steps…）
  num_outputs: number;
}
export interface WorkflowEdge {
  from: string;
  from_slot: number;
  to: string;
  to_slot: string;
}
export interface WorkflowGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  layout: string;
}

/** /api/preview 响应（生成前预览，不提交） */
export interface PreviewResponse {
  validated: boolean;
  issues: string[];
  workflow: WorkflowGraph | null;
  template_id: string;
}

/** 画布上的图片节点（一张生成结果） */
export interface CanvasNode {
  id: string;
  filename: string;   // ComfyUI 输出文件名
  prompt: string;     // 触发该图的 prompt
  templateId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  mode?: GenMode;          // 生成方式（节点可视化色标）
  parentId?: string | null; // 派生来源（图生图/局部重绘的源节点）→ 血缘连线
  seed?: number;            // 随机种子（溯源）
  negative?: string;        // 负向提示词
  createdAt?: number;       // 创建时间戳
  // ── 控制节点（§6.22：LoRA / ControlNet 节点化）──
  kind?: 'image' | 'control' | 'video';   // 节点种类：图片节点 | 控制节点 | 视频节点
  controlKind?: 'lora' | 'controlnet'; // 控制节点子类型
  frames?: number;           // 视频节点帧数（v4.32）
  fps?: number;              // 视频节点帧率（v4.32）
  loraName?: string;             // LoRA 文件名（含 .safetensors）
  loraStrength?: number;         // LoRA 强度（model & clip 共用）
  controlType?: string;          // ControlNet 类型（v4.23）
  controlStrength?: number;      // ControlNet 强度（v4.23）
  controlModel?: string;         // ControlNet 模型文件名（含 .safetensors，v4.23）
  controlImage?: string;         // ControlNet 控制图文件名（v4.23，缺省=目标图）
  workflowGraph?: WorkflowGraph | null; // 该节点由哪个工作流生成（可「查看工作流」）
}

/** 节点间手动关联（用户在画布拖拽连线建立，区别于 parentId 自动血缘） */
export interface Link {
  id: string;       // 唯一
  from: string;     // 源节点 id
  to: string;       // 目标节点 id
  label?: string;   // 可选关系标注（如「灵感来源」「同一系列」）
}

export type GenMode = 'txt2img' | 'img2img' | 'inpaint' | 'outpaint' | 'txt2vid' | 'img2vid';

/** 节点模式可视化元信息（色标 + 中文名） */
export const MODE_META: Record<GenMode, { label: string; color: string }> = {
  txt2img: { label: '文生图', color: '#4f8cff' },
  img2img: { label: '图生图', color: '#23c4a7' },
  inpaint: { label: '局部重绘', color: '#a06bff' },
  outpaint: { label: '扩图', color: '#f4a23b' },
  txt2vid: { label: '文生视频', color: '#a21caf' },
  img2vid: { label: '图生视频', color: '#db2777' },
};

/** 生成参数（前端参数面板 → /api/generate） */
export interface GenParams {
  mode: GenMode;
  model: '' | 'qwen2' | 'sdxl';   // '' = 自动
  width: number;
  height: number;
  steps: number;
  cfg: number;
  batchSize: number;
  seed: number;       // 0 = 随机
  negative: string;
  denoise: number;    // 图生图重绘幅度
  growMaskBy: number; // 局部重绘蒙版外扩像素
  outpaintDir: 'left' | 'right' | 'up' | 'down' | 'all'; // 扩图方向
  outpaintPixels: number; // 扩图扩展像素（原图像素空间）
  frames?: number;   // 视频帧数（Phase 9）
  fps?: number;      // 视频帧率（Phase 9）
}

export const DEFAULT_GEN_PARAMS: GenParams = {
  mode: 'txt2img',
  model: '',
  width: 1024,
  height: 1024,
  steps: 20,
  cfg: 7.0,
  batchSize: 1,
  seed: 0,
  negative: '',
  denoise: 0.6,
  growMaskBy: 6,
  outpaintDir: 'right',
  outpaintPixels: 256,
  frames: 33,
  fps: 16,
};

/** 模板注册表项（§6.7） */
export interface TemplateMeta {
  id: string;
  label?: string;
  desc?: string;
  [k: string]: unknown;
}
