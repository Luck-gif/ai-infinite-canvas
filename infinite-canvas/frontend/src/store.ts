// 无限画布 · 全局状态（zustand）；含撤销/重做历史栈 + localStorage 持久化 + v4.28 多选框选
import { create } from 'zustand';
import type { CanvasNode, Link, WorkflowGraph, TimelineClip, CanvasLayer, CanvasLayerKind, StoryboardTimelineShot, ShotStatus } from './types';

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
/** 撤销历史栈最大深度（防止大量操作后内存膨胀） */
const MAX_HISTORY = 50;

interface CanvasState {
  nodes: CanvasNode[];
  links: Link[];
  past: Snapshot[];
  future: Snapshot[];
  selectedId: string | null;
  /** v4.28 多选框选：Shift+点击或框选追加的节点 ID 集合 */
  selectedIds: string[];
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
  /** v4.28 Shift+点击切换节点在多选集中 */
  toggleSelectNode: (id: string) => void;
  /** v4.28 框选完成后设置多选集 */
  setSelectedIds: (ids: string[]) => void;
  /** v4.28 清除所有选中（单选 + 多选） */
  clearSelection: () => void;
  /** 获取当前所有选中节点 ID（单选 + 多选合并） */
  getAllSelectedIds: () => string[];
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

  // ── v4.39 视频时间轴 ──────────────────────────────────────────
  /** 时间轴面板是否打开 */
  timelineOpen: boolean;
  /** 时间轴上的视频片段列表 */
  timelineClips: TimelineClip[];
  /** 切换时间轴面板 */
  setTimelineOpen: (open: boolean) => void;
  /** 添加视频片段到时间轴（重复 nodeId 忽略） */
  addToTimeline: (clip: TimelineClip) => void;
  /** 从时间轴移除视频片段 */
  removeFromTimeline: (nodeId: string) => void;
  /** 重新排序时间轴片段 */
  reorderTimeline: (clips: TimelineClip[]) => void;
  /** 清空时间轴 */
  clearTimeline: () => void;

  // ── v4.50 三层画布 ──────────────────────────────────────────
  /** 当前激活的层级 */
  activeLayer: CanvasLayerKind;
  /** 全部层级定义 */
  layers: CanvasLayer[];
  /** 切换激活层级 */
  setActiveLayer: (kind: CanvasLayerKind) => void;
  /** 切换层级可见性 */
  toggleLayerVisibility: (id: string) => void;
  /** 切换层级锁定 */
  toggleLayerLock: (id: string) => void;
  /** v4.52 加载分镜到画布（清空当前后自动布局+连线） */
  loadStoryboardToCanvas: (shots: Array<{ shot_id: string; shot_index: number; prompt: string; node_count: number }>) => void;
  /** v4.52 画布导出 JSON */
  exportCanvas: () => string;

  // ── v4.57 故事板时间轴 ──────────────────────────────────────────
  /** 时间轴面板是否打开 */
  storyboardTimelineOpen: boolean;
  /** 时间轴上的分镜条目列表 */
  storyboardShots: StoryboardTimelineShot[];
  /** 批量生成进行中 */
  storyboardBatchBusy: boolean;
  /** 切换时间轴面板 */
  setStoryboardTimelineOpen: (open: boolean) => void;
  /** 从画布 storyboard 节点同步到时间轴 */
  syncStoryboardFromCanvas: () => void;
  /** 更新单个分镜的生成状态 */
  updateShotStatus: (nodeId: string, status: ShotStatus, image?: string) => void;
  /** 拖拽重排分镜 */
  reorderShots: (fromIndex: number, toIndex: number) => void;
    /** 设置批量生成进行中 */
    setStoryboardBatchBusy: (busy: boolean) => void;
    /** 为分镜绑定实体资产 */
    bindAssetToShot: (nodeId: string, entityId: string) => void;
    /** 为分镜解绑实体资产 */
    unbindAssetFromShot: (nodeId: string, entityId: string) => void;
  }

/** v4.50 三层画布默认配置 */
const DEFAULT_LAYERS: CanvasLayer[] = [
  { id: 'layer-planning', kind: 'planning', name: '策划层', icon: '📋',
    description: '概念图、参考素材、分镜草稿', visible: true, locked: false, order: 0 },
  { id: 'layer-generation', kind: 'generation', name: '生成层', icon: '🎨',
    description: 'AI 生成的图像与视频', visible: true, locked: false, order: 1 },
  { id: 'layer-output', kind: 'output', name: '输出层', icon: '🎬',
    description: '最终合成、导出结果', visible: true, locked: true, order: 2 },
];

function snapshot(
  set: (fn: (s: CanvasState) => Partial<CanvasState>) => void,
  get: () => CanvasState,
) {
  const { nodes, links } = get();
  set((s) => ({
    past: s.past.length >= MAX_HISTORY
      ? [...s.past.slice(-(MAX_HISTORY - 1)), { nodes, links }]
      : [...s.past, { nodes, links }],
    future: [],
  }));
}

export const useCanvasStore = create<CanvasState>((set, get) => {
  const init = loadInitial();
  return {
    nodes: init.nodes,
    links: init.links,
    past: [],
    future: [],
    selectedId: null,
    selectedIds: [],
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

    select: (id) => set({ selectedId: id, selectedIds: [] }),

    toggleSelectNode: (id) => {
      const s = get();
      // 如果已有单选且与 toggle 目标不同，保留单选节点一同进入多选
      const base = s.selectedIds.length > 0 ? s.selectedIds
        : s.selectedId && s.selectedId !== id ? [s.selectedId] : [];
      const idx = base.indexOf(id);
      const next = idx >= 0 ? base.filter((x) => x !== id) : [...base, id];
      set({ selectedId: next.length === 1 ? next[0] : null, selectedIds: next.length >= 2 ? next : [] });
    },

    setSelectedIds: (ids) => {
      set({ selectedId: ids.length === 1 ? ids[0] : null, selectedIds: ids.length >= 2 ? ids : [] });
    },

    clearSelection: () => set({ selectedId: null, selectedIds: [] }),

    getAllSelectedIds: () => {
      const s = get();
      if (s.selectedIds.length > 0) return s.selectedIds;
      if (s.selectedId) return [s.selectedId];
      return [];
    },

    requestFocus: (id) => set({ pendingFocus: { id, nonce: Date.now() } }),

    removeNode: (id) => {
      snapshot(set, get);
      set((s) => ({
        nodes: s.nodes.filter((nd) => nd.id !== id),
        links: s.links.filter((l) => l.from !== id && l.to !== id),
        selectedId: s.selectedId === id ? null : s.selectedId,
        selectedIds: s.selectedIds.filter((sid) => sid !== id),
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

    // ── v4.39 视频时间轴 ────────────────────────────────────────
    timelineOpen: false,
    timelineClips: [],

    setTimelineOpen: (open) => set({ timelineOpen: open }),

    addToTimeline: (clip) => {
      const existing = get().timelineClips.some((c) => c.nodeId === clip.nodeId);
      if (existing) return;
      set((s) => ({ timelineClips: [...s.timelineClips, clip] }));
    },

    removeFromTimeline: (nodeId) => {
      set((s) => ({
        timelineClips: s.timelineClips.filter((c) => c.nodeId !== nodeId),
      }));
    },

    reorderTimeline: (clips) => set({ timelineClips: clips }),

    clearTimeline: () => set({ timelineClips: [] }),

    // ── v4.50 三层画布 ──────────────────────────────────────
    activeLayer: 'generation',
    layers: DEFAULT_LAYERS,

    setActiveLayer: (kind) => set({ activeLayer: kind }),

    toggleLayerVisibility: (id) => {
      set((s) => ({
        layers: s.layers.map((l) =>
          l.id === id ? { ...l, visible: !l.visible } : l,
        ),
      }));
    },

    toggleLayerLock: (id) => {
      set((s) => ({
        layers: s.layers.map((l) =>
          l.id === id ? { ...l, locked: !l.locked } : l,
        ),
      }));
    },

    // ── v4.52 分镜→画布 ──────────────────────────────────────────
    loadStoryboardToCanvas: (shots) => {
      const COLS = 3;
      const GAP_X = 360;
      const GAP_Y = 300;
      const START_X = 100;
      const START_Y = 80;

      const newNodes: CanvasNode[] = shots.map((shot, i) => ({
        id: `sb-${shot.shot_id}`,
        filename: '',
        prompt: shot.prompt,
        templateId: 'storyboard',
        x: START_X + (i % COLS) * GAP_X,
        y: START_Y + Math.floor(i / COLS) * GAP_Y,
        width: 320,
        height: 240,
        kind: 'image',
        mode: 'storyboard',
        seed: undefined,
        createdAt: Date.now(),
      }));

      // 清除当前节点后加载 + 建立顺序连线
      const links: { from: string; to: string }[] = [];
      for (let i = 0; i < newNodes.length - 1; i++) {
        links.push({ from: newNodes[i].id, to: newNodes[i + 1].id });
      }

      snapshot(set, get);

      set((s) => {
        const newLinks = [...s.links];
        links.forEach((l) => {
          const key = `${l.from}->${l.to}`;
          if (!newLinks.some((ex) => ex.id === key)) {
            newLinks.push({ id: key, from: l.from, to: l.to });
          }
        });
        return { nodes: newNodes, links: newLinks, selectedId: null, activeLayer: 'planning' as const };
      });

      persist(get());
    },

    exportCanvas: () => {
      const s = get();
      return JSON.stringify({
        nodes: s.nodes,
        links: s.links,
        layers: s.layers,
        activeLayer: s.activeLayer,
        version: '4.57',
        exportedAt: new Date().toISOString(),
      }, null, 2);
    },

    // ── v4.57 故事板时间轴 ────────────────────────────────────────
    storyboardTimelineOpen: false,
    storyboardShots: [],
    storyboardBatchBusy: false,

    setStoryboardTimelineOpen: (open) => set({ storyboardTimelineOpen: open }),

    syncStoryboardFromCanvas: () => {
      const { nodes } = get();
      const storyboardNodes = nodes
        .filter((n) => n.mode === 'storyboard')
        .sort((a, b) => (a.shotIndex ?? Infinity) - (b.shotIndex ?? Infinity));

      const shots: StoryboardTimelineShot[] = storyboardNodes.map((n, i) => ({
        nodeId: n.id,
        shotId: n.shotId ?? n.id,
        shotIndex: n.shotIndex ?? i + 1,
        prompt: n.prompt ?? '',
        status: n.shotStatus ?? 'idle',
        generatedImage: n.filename || undefined,
        duration: n.shotDuration,
        referenceAssets: n.referenceAssets ?? [],
      }));

      set({ storyboardShots: shots });
    },

    updateShotStatus: (nodeId, status, image) => {
      set((s) => ({
        storyboardShots: s.storyboardShots.map((sh) =>
          sh.nodeId === nodeId
            ? { ...sh, status, ...(image !== undefined ? { generatedImage: image } : {}) }
            : sh,
        ),
      }));
      // Also update the canvas node shotStatus
      const cur = get();
      const node = cur.nodes.find((n) => n.id === nodeId);
      if (node) {
        const patch: Partial<CanvasNode> = { shotStatus: status };
        if (image !== undefined) patch.filename = image;
        set((s) => ({
          nodes: s.nodes.map((nd) => (nd.id === nodeId ? { ...nd, ...patch } : nd)),
        }));
        persist(get());
      }
    },

    reorderShots: (fromIndex, toIndex) => {
      set((s) => {
        const shots = [...s.storyboardShots];
        const [moved] = shots.splice(fromIndex, 1);
        shots.splice(toIndex, 0, moved);
        return { storyboardShots: shots.map((sh, i) => ({ ...sh, shotIndex: i + 1 })) };
      });
    },

    setStoryboardBatchBusy: (busy) => set({ storyboardBatchBusy: busy }),

    bindAssetToShot: (nodeId, entityId) => {
      set((s) => {
        // Update storyboard shot
        const shots = s.storyboardShots.map((sh) => {
          if (sh.nodeId !== nodeId) return sh;
          const assets = sh.referenceAssets.includes(entityId)
            ? sh.referenceAssets
            : [...sh.referenceAssets, entityId];
          return { ...sh, referenceAssets: assets };
        });
        // Update canvas node
        const nodes = s.nodes.map((nd) => {
          if (nd.id !== nodeId) return nd;
          const assets = nd.referenceAssets ?? [];
          return {
            ...nd,
            referenceAssets: assets.includes(entityId) ? assets : [...assets, entityId],
          };
        });
        return { storyboardShots: shots, nodes };
      });
      persist(get());
    },

    unbindAssetFromShot: (nodeId, entityId) => {
      set((s) => {
        const shots = s.storyboardShots.map((sh) => {
          if (sh.nodeId !== nodeId) return sh;
          return { ...sh, referenceAssets: sh.referenceAssets.filter((a) => a !== entityId) };
        });
        const nodes = s.nodes.map((nd) => {
          if (nd.id !== nodeId) return nd;
          return {
            ...nd,
            referenceAssets: (nd.referenceAssets ?? []).filter((a) => a !== entityId),
          };
        });
        return { storyboardShots: shots, nodes };
      });
      persist(get());
    },
  };
});
