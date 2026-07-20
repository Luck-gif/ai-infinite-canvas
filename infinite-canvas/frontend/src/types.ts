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
  negative?: string;        // 负向提示词（v4.22）
  steps?: number;           // 采样步数（v4.54）
  cfg?: number;             // CFG scale（v4.54）
  createdAt?: number;       // 创建时间戳
  description?: string;      // 节点描述（v4.56）
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
  // ── v4.57 故事板分镜字段 ──
  shotIndex?: number;              // 分镜序号
  shotId?: string;                 // 故事板剧集 shot id
  shotDuration?: number;           // 分镜时长（秒）
  shotStatus?: ShotStatus;         // 分镜生成状态
  referenceAssets?: string[];      // 绑定的实体 asset id 列表
}

/** 节点间手动关联（用户在画布拖拽连线建立，区别于 parentId 自动血缘） */
export interface Link {
  id: string;       // 唯一
  from: string;     // 源节点 id
  to: string;       // 目标节点 id
  label?: string;   // 可选关系标注（如「灵感来源」「同一系列」）
}

export type GenMode = 'txt2img' | 'img2img' | 'inpaint' | 'outpaint' | 'txt2vid' | 'img2vid' | 'face_consistency' | 'image_blend' | 'style_consistency' | 'scene_consistency' | 'prop_consistency' | 'storyboard';

/** 节点模式可视化元信息（色标 + 中文名） */
export const MODE_META: Record<GenMode, { label: string; color: string }> = {
  txt2img: { label: '文生图', color: '#4f8cff' },
  img2img: { label: '图生图', color: '#23c4a7' },
  inpaint: { label: '局部重绘', color: '#a06bff' },
  outpaint: { label: '扩图', color: '#f4a23b' },
  txt2vid: { label: '文生视频', color: '#a21caf' },
  img2vid: { label: '图生视频', color: '#db2777' },
  face_consistency: { label: '角色一致', color: '#f97316' },
  image_blend: { label: '图像融合', color: '#14b8a6' },
  style_consistency: { label: '风格一致', color: '#e11d48' },
  scene_consistency: { label: '场景一致', color: '#0891b2' },
  prop_consistency: { label: '道具一致', color: '#7c3aed' },
  storyboard: { label: '分镜编排', color: '#f59e0b' },
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
  faceWeight: number;    // 角色一致性：面部影响权重（v4.33）
  faceImage: string | null;  // 角色一致性：人脸参考图上传名（v4.33）
  blendMode: string;       // 多图融合：混合模式（v4.34）
  blendFactor: number;     // 多图融合：混合强度（v4.34）
  blendImageB: string | null;  // 多图融合：图片B上传名（v4.34）
  styleImage: string | null;   // 风格一致性：风格参考图上传名（v4.35）
  styleWeight: number;         // 风格一致性：风格影响权重（v4.35）
  compositionWeight: number;   // 风格一致性：构图影响权重（v4.35）
  sceneImage: string | null;   // 场景一致性：场景参考图上传名（v4.36）
  sceneWeight: number;         // 场景一致性：场景保持力（v4.36）
  propImage: string | null;    // 道具一致性：道具参考图上传名（v4.37）
  propWeight: number;          // 道具一致性：道具保持力（v4.37）
  storyboardPrompts: string[]; // 分镜编排：分镜提示词列表（v4.38）
  videoQuality: 'speed' | 'quality'; // 视频质量模式（v5.0 LightX2V）
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
  faceWeight: 0.8,
  faceImage: null,
  blendMode: 'normal',
  blendFactor: 0.5,
  blendImageB: null,
  styleImage: null,
  styleWeight: 0.8,
  compositionWeight: 0.3,
  sceneImage: null,
  sceneWeight: 0.7,
  propImage: null,
  propWeight: 0.7,
  storyboardPrompts: [],
  videoQuality: 'speed', // v5.0: 默认速度优先（LightX2V）
};

/** 模板注册表项（§6.7） */
export interface TemplateMeta {
  id: string;
  label?: string;
  desc?: string;
  [k: string]: unknown;
}

// ── v4.38 分镜编排 ─────────────────────────────────────────────
/** 单个分镜帧结果 */
export interface StoryboardFrame {
  index: number;
  prompt: string;
  prompt_id: string;
  image: string | null;
  status: string;
}

/** /api/storyboard 响应 */
export interface StoryboardResponse {
  validated: boolean;
  frames: StoryboardFrame[];
  issues: string[];
  template_id: string;
}

/** /api/storyboard 请求 */
export interface StoryboardArgs {
  prompts: string[];
  checkpoint?: string | null;
  width?: number;
  height?: number;
  steps?: number;
  cfg?: number;
  seed?: number;
}

// ── v4.39 视频时间轴与多段拼接 ──────────────────────────────────
/** 时间轴上的一个视频片段 */
export interface TimelineClip {
  nodeId: string;
  filename: string;
  /** 视频节点帧数 */
  frames: number;
  /** 视频节点帧率 */
  fps: number;
  /** 提示词（用于悬停信息） */
  prompt: string;
}

/** /api/concat_videos 请求 */
export interface ConcatVideosRequest {
  video_names: string[];
  output_name?: string | null;
}

/** /api/concat_videos 响应 */
export interface ConcatVideosResponse {
  validated: boolean;
  filename: string | null;
  issues: string[];
}

/** 时间轴拼接参数（GenParams 扩展） */
export interface ConcatArgs {
  video_names: string[];
  output_name?: string | null;
}

// ── v4.42 自定义工作流库 + GPT 辅助创建 ──────────────────────────
/** 已保存的工作流库项元数据 */
export interface WorkflowLibraryItem {
  name: string;
  description: string;
  node_count: number;
  saved_at: number;
}

/** 工作流库项完整数据（含 raw ComfyUI JSON + 可视化图） */
export interface WorkflowLibraryData {
  name: string;
  description: string;
  saved_at: number;
  workflow_json: Record<string, unknown>;
  workflow_graph?: WorkflowGraph;
}

/** GPT 辅助创建工作流的请求/响应 */
export interface GptWorkflowRequest {
  description: string;
}

export interface GptWorkflowResponse {
  template_id: string;
  node_count: number;
  intent: Intent;
  workflow_json: Record<string, unknown>;
  workflow_graph: WorkflowGraph;
}

// ── v4.50 工作流生成 + 故事板规划 + 蓝图库 ─────────────────────────
/** /api/workflows/generate 请求 */
export interface WorkflowGenerateRequest {
  prompt: string;
  blueprint?: string;
  image_blueprint?: string;
  video_blueprint?: string | null;
  consistency_mode?: string;
  width?: number;
  height?: number;
  steps?: number;
  cfg?: number;
  negative?: string;
  submit?: boolean;
}

/** /api/workflows/generate 响应 */
export interface WorkflowGenerateResponse {
  validated: boolean;
  issues: string[];
  node_count: number;
  shot_id: string;
  prompt_engineered: string;
  consistency_mode: string;
  entities_used: string[];
  intent: Intent;
  workflow_json: Record<string, unknown>;
  workflow_graph: WorkflowGraph;
  prompt_id?: string;
  submitted?: boolean;
  submit_error?: string;
}

/** /api/storyboard/plan 请求 */
export interface StoryboardPlanRequest {
  description: string;
  num_shots?: number;
  style?: string;
  characters?: string[];
  blueprint?: string;
  video_blueprint?: string | null;
}

/** 单个分镜的工作流结果 */
export interface StoryboardShotResult {
  shot_id: string;
  shot_index: number;
  prompt: string;
  node_count: number;
  workflow_json: Record<string, unknown>;
}

/** /api/storyboard/plan 响应 */
export interface StoryboardPlanResponse {
  validated: boolean;
  storyboard_id: string;
  total_shots: number;
  consistency_profile: Record<string, unknown>;
  shots: StoryboardShotResult[];
}

/** /api/blueprints 响应 */
export interface BlueprintItem {
  id: string;
  name: string;
  category: string;
}

export interface BlueprintListResponse {
  image: BlueprintItem[];
  video: BlueprintItem[];
}

// ── v4.56 实体注册表 ─────────────────────────────────────────────

export type EntityKind = 'character' | 'scene' | 'prop' | 'style';

export interface EntityItem {
  entity_id: string;
  kind: EntityKind;
  name: string;
  alias: string;
  description: string;
  prompt_override: string;
  tags: string[];
  anchor?: Record<string, unknown>;
  created_at?: string;
}

export interface EntityListResponse {
  entities: EntityItem[];
}

// ── v4.50 三层画布 ──────────────────────────────────────────────

/** 画布层级：策划 / 生成 / 输出 */
export type CanvasLayerKind = 'planning' | 'generation' | 'output';

/** 画布层级对象 */
export interface CanvasLayer {
  id: string;
  kind: CanvasLayerKind;
  name: string;
  icon: string;
  description: string;
  visible: boolean;
  locked: boolean;
  order: number;
}

// ── v4.57 故事板时间轴 ─────────────────────────────────────────────

/** 分镜生成状态 */
export type ShotStatus = 'idle' | 'pending' | 'generating' | 'done' | 'failed';

/** 故事板时间轴上的单个分镜条目 */
export interface StoryboardTimelineShot {
  nodeId: string;
  shotId: string;
  shotIndex: number;
  prompt: string;
  status: ShotStatus;
  generatedImage?: string;
  duration?: number;
  referenceAssets: string[];
}

/** 批量故事板生成请求 */
export interface BatchStoryboardRequest {
  prompts: string[];
  checkpoint?: string | null;
  width?: number;
  height?: number;
  steps?: number;
  cfg?: number;
  seed?: number;
}

// ── v4.55 模式→层级映射工具 ─────────────────────────────────────

/** 根据节点 mode 推导所属画布层级 */
export function getNodeLayer(mode?: GenMode): CanvasLayerKind {
  switch (mode) {
    case 'storyboard':
      return 'planning';
    case 'txt2vid':
    case 'img2vid':
      return 'output';
    default:
      return 'generation';
  }
}

/** 层级→默认推荐模式 */
export function getDefaultMode(layer: CanvasLayerKind): GenMode {
  switch (layer) {
    case 'planning': return 'storyboard';
    case 'output': return 'txt2vid';
    case 'generation':
    default:
      return 'txt2img';
  }
}
