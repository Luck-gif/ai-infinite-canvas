// 无限画布 · 全局状态（zustand）；含撤销/重做历史栈 + localStorage 持久化（Phase 1 验收）
import { create } from 'zustand';
import type { CanvasNode, Link, WorkflowGraph } from './types';

const STORAGE_KEY = 'infinite-canvas.nodes.v1';

/** 序列化：画布节点 + 手动连线 → JSON 字符串 */
export function serializeNodes(nodes: CanvasNode[], links: Link[] = []): string {
  return JSON.stringify({ version: 1, nodes, links });
}

/** 反序列化：JSON 字符串 → 画布节点（容错，非法输入返回 []） */
export function deserializeNodes(raw: string): CanvasNode[] {
  try {
    const obj = JSON.parse(raw);
    const arr = Array.isArray(obj) ? obj : obj?.nodes;
    if (!Array.isArray(arr)) return [];
    return arr.filter(
      (n): n is CanvasNode =>
        !!n && typeof n.id === 'string' && typeof n.filename === 'string',
    );
  } catch {
    return [];
  }
}

/** 反序列化手动关联（容错，缺省/非法返回 []） */
export function deserializeLinks(raw: string): Link[] {
  try {
    const obj = JSON.parse(raw);
    const arr = Array.isArray(obj) ? [] : obj?.links;
    if (!Array.isArray(arr)) return [];
    return arr.filter(
      (l): l is Link =>
        !!l && typeof l.id === 'string' && typeof l.from === 'string' && typeof l.to === 'string',
    );
  } catch {
    return [];
  }
}

function loadInitial(): { nodes: CanvasNode[]; links: Link[] } {
  if (typeof localStorage === 'undefined') return { nodes: [], links: [] };
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return { nodes: [], links: [] };
  return { nodes: deserializeNodes(raw), links: deserializeLinks(raw) };
}

function persist(state: { nodes: CanvasNode[]; links: Link[] }) {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, serializeNodes(state.nodes, state.links));
  } catch {
    /* 配额超限等静默忽略 */
  }
}

/** 历史快照：同时保存 nodes 与 links，保证撤销/重做一致 */
type Snapshot = { nodes: CanvasNode[]; links: Link[] };

interface CanvasState {
  nodes: CanvasNode[];
  links: Link[];
  past: Snapshot[];
  future: Snapshot[];
  selectedId: string | null;
  /** 聚焦请求（ControlPanel → Canvas 平移到某节点），用 nonce 触发重复点击 */
  pendingFocus: { id: string; nonce: number } | null;
  /** 工作流面板：生成前实时工作流（预览）；生成后清空 */
  liveWorkflow: WorkflowGraph | null;
  /** 工作流面板：用户显式「查看工作流」的某个节点图 */
  viewWorkflow: WorkflowGraph | null;
  /** 工作流面板是否展开 */
  wfOpen: boolean;

  addNode: (n: CanvasNode) => void;
  /** 请求画布平移聚焦到指定节点 */
  requestFocus: (id: string) => void;
  /** 拖动中实时更新（不记入历史） */
  dragMove: (id: string, x: number, y: number) => void;
  /** 拖动结束提交一次历史 */
  commitMove: (id: string, x: number, y: number) => void;
  select: (id: string | null) => void;
  removeNode: (id: string) => void;
  undo: () => void;
  redo: () => void;
  clear: () => void;
  /** 用外部节点整体替换（导入/加载存档），记入历史 */
  replaceAll: (nodes: CanvasNode[]) => void;
  /** 建立节点间手动关联（画布拖拽连线），无序去重 */
  addLink: (from: string, to: string) => void;
  /** 移除手动关联 */
  removeLink: (id: string) => void;
  /** 局部更新节点字段（如控制节点的 LoRA 名称/强度） */
  updateNode: (id: string, patch: Partial<CanvasNode>) => void;
  /** 设置生成前实时工作流（预览） */
  setLiveWorkflow: (g: WorkflowGraph | null) => void;
  /** 设置用户显式查看的节点工作流 */
  setViewWorkflow: (g: WorkflowGraph | null) => void;
  /** 切换工作流面板展开 */
  setWfOpen: (open: boolean) => void;
}

function snapshot(
  set: (fn: (s: CanvasState) => Partial<CanvasState>) => void,
  get: () => CanvasState,
) {
  const { nodes, links } = get();
  set((s) => ({ past: [...s.past, { nodes, links }], future: [] }));
}

export const useCanvasStore = create<CanvasState>((set, get) => {
  const init = loadInitial();
  return {
    nodes: init.nodes,
    links: init.links,
    past: [],
    future: [],
    selectedId: null,
    pendingFocus: null,
    liveWorkflow: null,
    viewWorkflow: null,
    wfOpen: false,

    addNode: (n) => {
      snapshot(set, get);
      set((s) => ({ nodes: [...s.nodes, n], selectedId: n.id }));
      persist(get());
    },

    dragMove: (id, x, y) => {
      set((s) => ({
        nodes: s.nodes.map((nd) => (nd.id === id ? { ...nd, x, y } : nd)),
      }));
    },

    commitMove: (id, x, y) => {
      snapshot(set, get);
      set((s) => ({
        nodes: s.nodes.map((nd) => (nd.id === id ? { ...nd, x, y } : nd)),
      }));
      persist(get());
    },

    select: (id) => set({ selectedId: id }),

    requestFocus: (id) => set({ pendingFocus: { id, nonce: Date.now() } }),

    removeNode: (id) => {
      snapshot(set, get);
      set((s) => ({
        nodes: s.nodes.filter((nd) => nd.id !== id),
        links: s.links.filter((l) => l.from !== id && l.to !== id),
        selectedId: s.selectedId === id ? null : s.selectedId,
      }));
      persist(get());
    },

    addLink: (from, to) => {
      if (!from || !to || from === to) return;
      const s = get();
      const srcNode = s.nodes.find((n) => n.id === from);
      // 控制 / LoRA 节点（kind 均为 'control'）只允许一条出边：拖拽即改目标（重定目标），保证「应用」用到拖到的目标图
      const replaceOutgoing = srcNode?.kind === 'control';
      if (replaceOutgoing) {
        if (!s.nodes.some((n) => n.id === to)) return;
        snapshot(set, get);
        set((st) => ({
          links: [...st.links.filter((l) => l.from !== from), { id: crypto.randomUUID(), from, to }],
        }));
        persist(get());
        return;
      }
      // 无序去重：已存在同向或反向关联则忽略
      if (s.links.some((l) => (l.from === from && l.to === to) || (l.from === to && l.to === from))) return;
      // 两端节点都必须存在
      if (!s.nodes.some((n) => n.id === from) || !s.nodes.some((n) => n.id === to)) return;
      snapshot(set, get);
      set((st) => ({ links: [...st.links, { id: crypto.randomUUID(), from, to }] }));
      persist(get());
    },

    removeLink: (id) => {
      if (!get().links.some((l) => l.id === id)) return;
      snapshot(set, get);
      set((st) => ({ links: st.links.filter((l) => l.id !== id) }));
      persist(get());
    },

    updateNode: (id, patch) => {
      snapshot(set, get);
      set((st) => ({
        nodes: st.nodes.map((nd) => (nd.id === id ? { ...nd, ...patch } : nd)),
      }));
      persist(get());
    },

    undo: () => {
      const { past, nodes, links, future } = get();
      if (past.length === 0) return;
      const prev = past[past.length - 1];
      set({
        nodes: prev.nodes,
        links: prev.links,
        past: past.slice(0, -1),
        future: [{ nodes, links }, ...future],
        selectedId: null,
      });
      persist(get());
    },

    redo: () => {
      const { past, nodes, links, future } = get();
      if (future.length === 0) return;
      const next = future[0];
      set({
        nodes: next.nodes,
        links: next.links,
        past: [...past, { nodes, links }],
        future: future.slice(1),
        selectedId: null,
      });
      persist(get());
    },

    clear: () => {
      snapshot(set, get);
      set({ nodes: [], links: [], selectedId: null });
      persist(get());
    },

    replaceAll: (nodes) => {
      snapshot(set, get);
      set({ nodes, selectedId: null });
      persist(get());
    },

    setLiveWorkflow: (g) => set({ liveWorkflow: g }),
    setViewWorkflow: (g) => set({ viewWorkflow: g }),
    setWfOpen: (open) => set({ wfOpen: open }),
  };
});
