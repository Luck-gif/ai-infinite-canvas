// 无限画布 · API 客户端（封装 §8.1 后端契约；vite 代理 /api → :8000）
import type {
  IntentResponse,
  GenerateResponse,
  PreviewResponse,
  TemplateMeta,
  StoryboardArgs,
  StoryboardResponse,
  ConcatVideosRequest,
  ConcatVideosResponse,
  WorkflowLibraryItem,
  WorkflowLibraryData,
  GptWorkflowRequest,
  GptWorkflowResponse,
  WorkflowGenerateRequest,
  WorkflowGenerateResponse,
  StoryboardPlanRequest,
  StoryboardPlanResponse,
  BlueprintListResponse,
  WorkflowGraph,
  EntityItem,
  EntityListResponse,
  BatchStoryboardRequest,
} from './types';

const BASE = '/api';

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`[${res.status}] ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function parseIntent(userInput: string): Promise<IntentResponse> {
  return postJSON<IntentResponse>(`${BASE}/intent`, { user_input: userInput });
}

export interface GenerateArgs {
  intent?: Record<string, unknown> | null;
  prompt?: string;
  negative?: string;
  checkpoint?: string;
  width?: number;
  height?: number;
  steps?: number;
  cfg?: number;
  seed?: number;
  batch_size?: number;
  input_image?: string | null;
  denoise?: number;
  mask_image?: string | null;
  grow_mask_by?: number;
  outpaint_direction?: string;  // 扩图方向 left/right/up/down/all
  outpaint_pixels?: number;      // 扩图扩展像素（原图像素空间）
  loras?: { name: string; strength: number }[]; // LoRA 应用（控制节点化 §6.22）
  controlnets?: { model: string; type?: string; strength: number; image: string; preprocessor?: string }[]; // ControlNet（§6.23）
  frames?: number;   // 视频帧数（Phase 9）
  fps?: number;      // 视频帧率（Phase 9）
  video_quality?: 'speed' | 'quality';  // 视频质量模式（v5.0 LightX2V）
  face_image?: string | null;  // 角色一致性：人脸参考图（v4.33）
  face_weight?: number;         // 角色一致性：面部权重（v4.33）
  blend_image_b?: string | null;  // 多图融合：图片B（v4.34）
  blend_mode?: string;            // 多图融合：混合模式（v4.34）
  blend_factor?: number;          // 多图融合：混合强度（v4.34）
  style_image?: string | null;   // 风格一致性：风格参考图（v4.35）
  style_weight?: number;         // 风格一致性：风格影响权重（v4.35）
  composition_weight?: number;   // 风格一致性：构图影响权重（v4.35）
  scene_image?: string | null;   // 场景一致性：场景参考图（v4.36）
  scene_weight?: number;         // 场景一致性：场景保持力（v4.36）
  prop_image?: string | null;    // 道具一致性：道具参考图（v4.37）
  prop_weight?: number;          // 道具一致性：道具保持力（v4.37）
  wait?: boolean;
}

export async function generate(args: GenerateArgs): Promise<GenerateResponse> {
  return postJSON<GenerateResponse>(`${BASE}/generate`, { wait: true, ...args });
}

// ── v4.38 分镜编排 ──────────────────────────────────────────
export async function generateStoryboard(args: StoryboardArgs): Promise<StoryboardResponse> {
  return postJSON<StoryboardResponse>(`${BASE}/storyboard`, args);
}

/** 生成前预览工作流节点图（不提交 ComfyUI，前端「工作流」面板实时显示） */
export async function previewWorkflow(args: GenerateArgs): Promise<PreviewResponse> {
  return postJSON<PreviewResponse>(`${BASE}/preview`, { wait: false, ...args });
}

/** 上传图片到 ComfyUI input/（图生图输入），返回存储文件名。 */
export async function uploadImage(filename: string, dataBase64: string): Promise<string> {
  const res = await postJSON<{ name: string }>(`${BASE}/upload`, {
    filename,
    data_base64: dataBase64,
  });
  return res.name;
}

export async function listTemplates(): Promise<TemplateMeta[]> {
  const res = await fetch(`${BASE}/templates`);
  if (!res.ok) throw new Error(`[${res.status}] templates`);
  return res.json() as Promise<TemplateMeta[]>;
}

export async function getStatus(): Promise<{ status: string; comfyui: string }> {
  const res = await fetch(`${BASE}/status`);
  if (!res.ok) throw new Error(`[${res.status}] status`);
  return res.json() as Promise<{ status: string; comfyui: string }>;
}

/** 图片访问：经后端 /api/image/{filename} 代理 ComfyUI /view（同源，无 CORS） */
export function imageUrl(filename: string): string {
  return `${BASE}/image/${encodeURIComponent(filename)}`;
}

/** 共享库已装 LoRA 列表（控制节点化 §6.22） */
export async function listLoras(): Promise<string[]> {
  const res = await fetch(`${BASE}/loras`);
  if (!res.ok) return [];
  const j = (await res.json()) as { loras?: string[] };
  return j.loras ?? [];
}

/** 共享库已装 ControlNet 列表 + 合法 union 类型（控制节点化 §6.23） */
export async function listControlnets(): Promise<{ controlnets: string[]; unionTypes: string[] }> {
  const res = await fetch(`${BASE}/controlnets`);
  if (!res.ok) return { controlnets: [], unionTypes: [] };
  const j = (await res.json()) as { controlnets?: string[]; union_types?: string[] };
  return { controlnets: j.controlnets ?? [], unionTypes: j.union_types ?? [] };
}

/** v4.29 轮询获取生成结果（SSE done 之后调用）。 */
export async function fetchResult(promptId: string): Promise<{ images: string[]; status: string; message?: string }> {
  const res = await fetch(`${BASE}/result/${promptId}`);
  if (!res.ok) throw new Error(`[${res.status}] fetchResult`);
  return res.json() as Promise<{ images: string[]; status: string; message?: string }>;
}

// ── v4.31 用户工作流模板保存/加载/删除 ──────────────────────────
export interface UserTemplateMeta {
  name: string;
  saved_at: number;
  node_count: number;
}

export interface UserTemplateData {
  name: string;
  saved_at: number;
  nodes: unknown[];
  links: unknown[];
}

/** 保存当前画布为模板。 */
export async function saveTemplate(name: string, nodes: unknown[], links: unknown[]): Promise<{ name: string; node_count: number }> {
  return postJSON<{ name: string; node_count: number }>(`${BASE}/templates/save`, { name, nodes, links });
}

/** 列出所有用户模板。 */
export async function listUserTemplates(): Promise<UserTemplateMeta[]> {
  const res = await fetch(`${BASE}/templates/user`);
  if (!res.ok) return [];
  return res.json() as Promise<UserTemplateMeta[]>;
}

/** 加载单个模板完整数据。 */
export async function loadUserTemplate(name: string): Promise<UserTemplateData> {
  const res = await fetch(`${BASE}/templates/user/${encodeURIComponent(name)}`);
  if (!res.ok) throw new Error(`[${res.status}] load template`);
  return res.json() as Promise<UserTemplateData>;
}

/** 删除用户模板。 */
export async function deleteUserTemplate(name: string): Promise<void> {
  const res = await fetch(`${BASE}/templates/user/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`[${res.status}] delete template`);
}

// ── v4.39 视频多段拼接 ──────────────────────────────────────────
/** 拼接多个视频文件为单个 mp4 */
export async function concatVideos(args: ConcatVideosRequest): Promise<ConcatVideosResponse> {
  return postJSON<ConcatVideosResponse>(`${BASE}/concat_videos`, args);
}

// ── v4.40 画布导出 ZIP ───────────────────────────────────────────
/** 将画布节点媒体文件打包下载为 ZIP */
export async function exportCanvasZip(filenames: string[]): Promise<{ blob: Blob; added: number; missing: number }> {
  const res = await fetch(`${BASE}/export_canvas`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filenames }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`导出失败 [${res.status}]: ${text}`);
  }
  const blob = await res.blob();
  const added = parseInt(res.headers.get('X-Added-Count') || '0', 10);
  const missing = parseInt(res.headers.get('X-Missing-Count') || '0', 10);
  return { blob, added, missing };
}

// ── v4.42 自定义工作流库 + GPT ────────────────────────────────────
/** 保存自定义 ComfyUI 工作流 JSON */
export async function saveWorkflow(name: string, description: string, workflowJson: Record<string, unknown>): Promise<{ name: string; node_count: number }> {
  return postJSON(`${BASE}/workflows/save`, { name, description, workflow_json: workflowJson });
}

/** 列出所有已保存的自定义工作流 */
export async function listWorkflows(): Promise<WorkflowLibraryItem[]> {
  const res = await fetch(`${BASE}/workflows`);
  if (!res.ok) return [];
  return res.json() as Promise<WorkflowLibraryItem[]>;
}

/** 加载单个自定义工作流完整数据 */
export async function loadWorkflow(name: string): Promise<WorkflowLibraryData> {
  const res = await fetch(`${BASE}/workflows/${encodeURIComponent(name)}`);
  if (!res.ok) throw new Error(`[${res.status}] load workflow`);
  return res.json() as Promise<WorkflowLibraryData>;
}

/** 删除自定义工作流 */
export async function deleteWorkflow(name: string): Promise<void> {
  const res = await fetch(`${BASE}/workflows/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`[${res.status}] delete workflow`);
}

/** GPT 辅助：从自然语言描述生成 ComfyUI 工作流 JSON */
export async function gptCreateWorkflow(req: GptWorkflowRequest): Promise<GptWorkflowResponse> {
  return postJSON<GptWorkflowResponse>(`${BASE}/workflows/gpt`, req);
}

/** v4.50 自然语言→组装→校验→完整ComfyUI JSON（新管线） */
export async function generateWorkflow(req: WorkflowGenerateRequest): Promise<WorkflowGenerateResponse> {
  return postJSON<WorkflowGenerateResponse>(`${BASE}/workflows/generate`, req);
}

/** v4.50 故事板规划→多分镜组装 */
export async function planStoryboard(req: StoryboardPlanRequest): Promise<StoryboardPlanResponse> {
  return postJSON<StoryboardPlanResponse>(`${BASE}/storyboard/plan`, req);
}

/** v4.50 蓝图库查询 */
export async function listBlueprints(): Promise<BlueprintListResponse> {
  const res = await fetch(`${BASE}/blueprints`);
  if (!res.ok) throw new Error(`[${res.status}] blueprints`);
  return res.json() as Promise<BlueprintListResponse>;
}

// ── v4.50 Pipeline Orchestrator ────────────────────────────────────

export interface PipelineRunRequest {
  prompt: string;
  image_blueprint?: string | null;
  consistency_mode?: string | null;
  width?: number | null;
  height?: number | null;
  steps?: number | null;
  cfg?: number | null;
  negative?: string | null;
  submit?: boolean;
}

export interface PipelineRunResponse {
  validated: boolean;
  issues: string[];
  node_count: number;
  prompt_engineered: string;
  consistency_mode: string;
  intent: Record<string, unknown>;
  blueprint: string;
  blueprint_id: string;
  submitted: boolean;
  submit_error: string | null;
  workflow_json: Record<string, unknown>;
  workflow_graph: WorkflowGraph | null;
  duration_ms: number;
  pipeline_version: string;
}

/** v4.50 PipelineOrchestrator 完整多Agent管线执行 */
export async function runPipeline(req: PipelineRunRequest): Promise<PipelineRunResponse> {
  return postJSON<PipelineRunResponse>(`${BASE}/pipeline/run`, req);
}

/** v4.50 PipelineOrchestrator 故事板管线执行 */
export async function runPipelineStoryboard(req: StoryboardPlanRequest): Promise<StoryboardPlanResponse> {
  return postJSON<StoryboardPlanResponse>(`${BASE}/pipeline/storyboard`, req);
}

// ── v4.56 Entity Registry ───────────────────────────────────────

/** 列出所有实体（可按 kind 过滤） */
export async function listEntities(kind?: string): Promise<EntityListResponse> {
  const q = kind ? `?kind=${kind}` : '';
  const res = await fetch(`${BASE}/entities${q}`);
  if (!res.ok) throw new Error(`[${res.status}] entities`);
  return res.json() as Promise<EntityListResponse>;
}

/** 创建实体 */
export async function createEntity(body: {
  kind: string; name: string; alias?: string; description?: string;
  prompt_override?: string; tags?: string[];
}): Promise<{ entity: EntityItem }> {
  const res = await fetch(`${BASE}/entities`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`[${res.status}] create entity`);
  return res.json();
}

/** 搜索实体 */
export async function searchEntities(query: string): Promise<EntityListResponse> {
  const res = await fetch(`${BASE}/entities/search?q=${encodeURIComponent(query)}`);
  if (!res.ok) throw new Error(`[${res.status}] search entities`);
  return res.json() as Promise<EntityListResponse>;
}

/** 获取实体 prompt 前缀 */
export async function getEntityPrompt(entityId: string): Promise<{ entity_id: string; prompt: string }> {
  const res = await fetch(`${BASE}/entities/${entityId}/prompt`);
  if (!res.ok) throw new Error(`[${res.status}] entity prompt`);
  return res.json();
}

// ── v4.57 故事板时间轴批量生成 ────────────────────────────────────

/** 批量生成故事板分镜（并行提交到 ComfyUI） */
export async function batchGenerateStoryboard(
  params: BatchStoryboardRequest,
  onProgress?: (done: number, total: number) => void,
): Promise<StoryboardResponse> {
  onProgress?.(0, params.prompts.length);
  const result = await generateStoryboard({
    prompts: params.prompts,
    checkpoint: params.checkpoint ?? undefined,
    width: params.width ?? 1024,
    height: params.height ?? 1024,
    steps: params.steps ?? 20,
    cfg: params.cfg ?? 7.0,
    seed: params.seed ?? 42,
  });
  onProgress?.(result.frames.filter((f) => f.status === 'done').length, params.prompts.length);
  return result;
}

// ═══════════════════════════════════════════════════════════════
// v5.1 Regional Pipeline · 多角色同框
// ═══════════════════════════════════════════════════════════════

export interface RegionalGenerateRequest {
  characters: Array<{
    token: string;
    entity_id: string;
    prompt: string;
    region_ratio: number;
    ipa_weight: number;
  }>;
  base_prompt: string;
  negative?: string;
  layout?: 'horizontal' | 'vertical' | 'grid2x2' | 'custom';
  width?: number;
  height?: number;
  steps?: number;
  cfg?: number;
  seed?: number;
}

export interface RegionalGenerateResponse {
  validated: boolean;
  template_id: string;
  prompt_id: string;
  status: string;
  issues: string[];
  meta: Record<string, unknown>;
  workflow: Record<string, unknown> | null;
}

export async function regionalGenerate(req: RegionalGenerateRequest): Promise<RegionalGenerateResponse> {
  const res = await fetch(`${BASE}/api/regional/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => 'unknown error');
    throw new Error(`regional generate failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<RegionalGenerateResponse>;
}

// ═══════════════════════════════════════════════════════════════
// v5.2 一致性审查 + IP 相似度预警
// ═══════════════════════════════════════════════════════════════

export interface ConsistencyReviewNode {
  node_id: string;
  reference_image: string;
  generated_image: string;
  mode: string;
}

export interface ConsistencyReviewResponse {
  validated: boolean;
  total_nodes: number;
  passed_nodes: number;
  failed_nodes: number;
  pass_rate: number;
  avg_similarity: number;
  grade_distribution: Record<string, number>;
  issues: string[];
  reports: Array<{
    node_id: string;
    mode: string;
    similarity_score: number;
    grade: string;
    passed: boolean;
    issues: string[];
  }>;
}

export async function reviewConsistency(
  nodes: ConsistencyReviewNode[],
  threshold?: number,
): Promise<ConsistencyReviewResponse> {
  const res = await fetch(`${BASE}/api/review/consistency`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nodes, threshold: threshold ?? 0.75 }),
  });
  if (!res.ok) throw new Error(`consistency review failed: ${res.status}`);
  return res.json() as Promise<ConsistencyReviewResponse>;
}

export interface IPCheckResponse {
  validated: boolean;
  entity_id: string;
  entity_name: string;
  similarity: number;
  passed: boolean;
  warning: string;
  action: string;
}

export async function ipCheck(entityId: string, generatedImage: string, entityName?: string): Promise<IPCheckResponse> {
  const res = await fetch(`${BASE}/api/guard/ip-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entity_id: entityId, generated_image: generatedImage, entity_name: entityName ?? '' }),
  });
  if (!res.ok) throw new Error(`ip check failed: ${res.status}`);
  return res.json() as Promise<IPCheckResponse>;
}

export async function ipRegister(entityId: string, referenceImage: string): Promise<{ validated: boolean; entity_id: string; registered: boolean; message: string }> {
  const res = await fetch(`${BASE}/api/guard/ip-register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entity_id: entityId, reference_image: referenceImage }),
  });
  if (!res.ok) throw new Error(`ip register failed: ${res.status}`);
  return res.json() as Promise<{ validated: boolean; entity_id: string; registered: boolean; message: string }>;
}

export async function ipLibraryStatus(): Promise<{ total_entities: number; embedding_dim: number; entity_ids: string[]; index_file: string }> {
  const res = await fetch(`${BASE}/api/guard/ip-library`);
  if (!res.ok) throw new Error(`ip library status failed: ${res.status}`);
  return res.json() as Promise<{ total_entities: number; embedding_dim: number; entity_ids: string[]; index_file: string }>;
}

// ═══════════════════════════════════════════════════════════════
// v5.3 基础审核 · 节点质量标记
// ═══════════════════════════════════════════════════════════════

export async function markNodeQuality(nodeId: string, status: string, note?: string): Promise<{ validated: boolean; node_id: string; status: string }> {
  const res = await fetch(`${BASE}/api/review/quality`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_id: nodeId, status, note }),
  });
  if (!res.ok) throw new Error(`quality mark failed: ${res.status}`);
  return res.json() as Promise<{ validated: boolean; node_id: string; status: string }>;
}

export async function batchMarkQuality(nodeIds: string[], status: string, note?: string): Promise<{ validated: boolean; count: number }> {
  const res = await fetch(`${BASE}/api/review/batch-quality`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_ids: nodeIds, status, note }),
  });
  if (!res.ok) throw new Error(`batch quality mark failed: ${res.status}`);
  return res.json() as Promise<{ validated: boolean; count: number }>;
}
