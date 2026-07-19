// 无限画布 · API 客户端（封装 §8.1 后端契约；vite 代理 /api → :8000）
import type {
  IntentResponse,
  GenerateResponse,
  PreviewResponse,
  TemplateMeta,
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
  wait?: boolean;
}

export async function generate(args: GenerateArgs): Promise<GenerateResponse> {
  return postJSON<GenerateResponse>(`${BASE}/generate`, { wait: true, ...args });
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
