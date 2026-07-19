// v4.25 工作流可视化：在无限画布内渲染 ComfyUI 节点图（参考商用 UI 的人机优化）
// - 分层 DAG 布局（自动避让重叠）
// - 平移 / 滚轮缩放 / 悬停高亮节点与连线
// - 分类配色 + 图例 + 关键参数 chip
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { WorkflowGraph, WorkflowNode } from './types';
import { theme } from './theme';

const NODE_W = 196;
const HEADER_H = 28;
const PORT_GAP = 18;
const ROW_GAP = 26;
const COL_GAP = 72;

const CAT_COLOR: Record<string, string> = {
  model: theme.accent.blue,
  sample: theme.accent.orange,
  cond: theme.accent.teal,
  latent: theme.accent.purple,
  vae: theme.accent.rose,
  io: theme.accent.emerald,
  other: theme.text.hint,
};
const CAT_LABEL: Record<string, string> = {
  model: '模型',
  sample: '采样',
  cond: '条件',
  latent: '潜空间',
  vae: 'VAE',
  io: '输入/输出',
  other: '其他',
};

function portCount(n: WorkflowNode) {
  return Math.max(1, n.input_links.length);
}
function nodeHeight(n: WorkflowNode) {
  const h = HEADER_H + portCount(n) * PORT_GAP + 14;
  return h + (Object.keys(n.values).length > 0 ? 26 : 0);
}
function inputY(i: number) {
  return HEADER_H + 10 + i * PORT_GAP;
}

interface Layout {
  x: Map<string, number>;
  y: Map<string, number>;
  h: Map<string, number>;
  W: number;
  H: number;
}

function useLayout(graph: WorkflowGraph, cw: number, ch: number): Layout {
  return useMemo(() => {
    const nodes = graph.nodes;
    const ids = nodes.map((n) => n.id);
    const idset = new Set(ids);
    const incoming = new Map<string, string[]>();
    const outgoing = new Map<string, string[]>();
    ids.forEach((i) => {
      incoming.set(i, []);
      outgoing.set(i, []);
    });
    graph.edges.forEach((e) => {
      if (idset.has(e.from) && idset.has(e.to)) {
        incoming.get(e.to)!.push(e.from);
        outgoing.get(e.from)!.push(e.to);
      }
    });
    // Kahn 拓扑序
    const indeg = new Map(ids.map((i) => [i, incoming.get(i)!.length]));
    const q = ids.filter((i) => indeg.get(i) === 0);
    const topo: string[] = [];
    while (q.length) {
      const n = q.shift()!;
      topo.push(n);
      outgoing.get(n)!.forEach((m) => {
        indeg.set(m, indeg.get(m)! - 1);
        if (indeg.get(m) === 0) q.push(m);
      });
    }
    // 层级
    const level = new Map<string, number>();
    topo.forEach((i) => {
      const preds = incoming.get(i)!;
      level.set(i, preds.length ? Math.max(...preds.map((p) => level.get(p)!)) + 1 : 0);
    });
    const byLevel = new Map<number, string[]>();
    ids.forEach((i) => {
      const lv = level.get(i)!;
      if (!byLevel.has(lv)) byLevel.set(lv, []);
      byLevel.get(lv)!.push(i);
    });
    const x = new Map<string, number>();
    const y = new Map<string, number>();
    const h = new Map<string, number>();
    let maxX = 0;
    let maxY = 0;
    [...byLevel.keys()].sort((a, b) => a - b).forEach((lv) => {
      const members = byLevel.get(lv)!.slice().sort((a, b) => a.localeCompare(b));
      let cy = 0;
      members.forEach((i) => {
        const nh = nodeHeight(graph.nodes.find((n) => n.id === i)!);
        x.set(i, lv * (NODE_W + COL_GAP));
        y.set(i, cy);
        h.set(i, nh);
        cy += nh + ROW_GAP;
      });
      maxX = Math.max(maxX, lv * (NODE_W + COL_GAP) + NODE_W);
      maxY = Math.max(maxY, cy - ROW_GAP + 10);
    });

    return { x, y, h, W: maxX, H: maxY };
  }, [graph, cw, ch]);
}

export function WorkflowGraph({ graph, fitKey }: { graph: WorkflowGraph; fitKey?: number }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 360, h: 520 });
  const [scale, setScale] = useState(0.9);
  const [tx, setTx] = useState(16);
  const [ty, setTy] = useState(16);
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const pan = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);
  const fitted = useRef(false);

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const layout = useLayout(graph, size.w, size.h);

  // 每次切换工作流或外部触发 fitKey 变化时自动适应一次
  useEffect(() => {
    fitted.current = false;
  }, [graph, fitKey]);
  useEffect(() => {
    if (fitted.current || !graph.nodes.length) return;
    const pad = 24;
    const fit = Math.min(1, (size.w - pad * 2) / Math.max(layout.W, 1), (size.h - pad * 2) / Math.max(layout.H, 1));
    setScale(fit);
    setTx(pad);
    setTy(pad);
    fitted.current = true;
  }, [layout, size, graph]);

  const nodeById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);

  const outputPoint = (id: string) => {
    return { x: (layout.x.get(id) ?? 0) + NODE_W, y: (layout.y.get(id) ?? 0) + HEADER_H + 10 };
  };
  const inputPoint = (id: string, slotName: string) => {
    const n = nodeById.get(id)!;
    const idx = Math.max(0, n.input_links.findIndex((p) => p.name === slotName));
    return { x: layout.x.get(id) ?? 0, y: (layout.y.get(id) ?? 0) + inputY(idx) };
  };

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const rect = wrapRef.current!.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const factor = 1.1;
    const dir = e.deltaY > 0 ? -1 : 1;
    const next = Math.max(0.25, Math.min(2.5, scale * (dir > 0 ? factor : 1 / factor)));
    // 以光标为锚点缩放
    const nx = cx - ((cx - tx) * next) / scale;
    const ny = cy - ((cy - ty) * next) / scale;
    setScale(next);
    setTx(nx);
    setTy(ny);
  };

  const onDown = (e: React.MouseEvent) => {
    pan.current = { x: e.clientX, y: e.clientY, tx, ty };
  };
  const onMove = (e: React.MouseEvent) => {
    if (!pan.current) return;
    setTx(pan.current.tx + (e.clientX - pan.current.x));
    setTy(pan.current.ty + (e.clientY - pan.current.y));
  };
  const onUp = () => {
    pan.current = null;
  };

  const edgeActive = (from: string, to: string) =>
    !hovered || hovered === from || hovered === to;

  if (!graph.nodes.length) {
    return <div style={{ padding: 24, color: theme.text.dim, fontSize: 13 }}>无工作流节点</div>;
  }

  return (
    <div
      ref={wrapRef}
      onWheel={onWheel}
      onMouseDown={onDown}
      onMouseMove={onMove}
      onMouseUp={onUp}
      onMouseLeave={onUp}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        background:
          `radial-gradient(circle at 30% 20%, ${theme.bg.wfGrad} 0%, ${theme.bg.header} 70%)`,
        cursor: pan.current ? 'grabbing' : 'grab',
        userSelect: 'none',
      }}
    >
      <svg width={size.w} height={size.h} style={{ display: 'block' }}>
        <defs>
          <marker id="wf-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill={theme.text.dim} />
          </marker>
          <marker id="wf-arrow-a" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill={theme.accent.blue} />
          </marker>
        </defs>
        <g transform={`translate(${tx},${ty}) scale(${scale})`}>
          {/* 连线 */}
          {graph.edges.map((e, i) => {
            const s = outputPoint(e.from);
            const t = inputPoint(e.to, e.to_slot);
            const dx = Math.max(40, Math.abs(t.x - s.x) * 0.5);
            const active = edgeActive(e.from, e.to);
            const d = `M ${s.x} ${s.y} C ${s.x + dx} ${s.y}, ${t.x - dx} ${t.y}, ${t.x} ${t.y}`;
            return (
              <path
                key={'e' + i}
                d={d}
                fill="none"
                stroke={active ? theme.accent.blue : theme.misc.edgeDim}
                strokeWidth={active ? 2 : 1.4}
                opacity={active ? 0.95 : 0.4}
                markerEnd={active ? 'url(#wf-arrow-a)' : 'url(#wf-arrow)'}
              />
            );
          })}
          {/* 节点 */}
          {graph.nodes.map((n) => {
            const x = layout.x.get(n.id) ?? 0;
            const y = layout.y.get(n.id) ?? 0;
            const h = layout.h.get(n.id) ?? nodeHeight(n);
            const color = CAT_COLOR[n.category] ?? CAT_COLOR.other;
            const isOn = !hovered || hovered === n.id;
            const vals = Object.entries(n.values).slice(0, 3);
            return (
              <g
                key={n.id}
                transform={`translate(${x},${y})`}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => setPinned(pinned === n.id ? null : n.id)}
                style={{ cursor: 'pointer' }}
              >
                <rect
                  width={NODE_W}
                  height={h}
                  rx={9}
                  fill={theme.bg.node}
                  stroke={isOn ? color : theme.border.subtle}
                  strokeWidth={isOn ? 1.6 : 1}
                  opacity={isOn ? 1 : 0.5}
                />
                {/* 头部 */}
                <rect width={NODE_W} height={HEADER_H} rx={9} fill={color} opacity={0.92} />
                <rect y={HEADER_H - 10} width={NODE_W} height={10} fill={color} opacity={0.92} />
                <text x={10} y={19} fontSize={12.5} fontWeight={700} fill="#fff">
                  {n.title}
                </text>
                <text x={NODE_W - 8} y={18} fontSize={9.5} fill="rgba(255,255,255,0.8)" textAnchor="end">
                  {n.type}
                </text>
                {/* 输入端口 + 标签 */}
                {n.input_links.map((p, idx) => (
                  <g key={p.name + idx}>
                    <circle cx={0} cy={inputY(idx)} r={4.5} fill={theme.bg.canvas} stroke={color} strokeWidth={1.6} />
                    <text x={10} y={inputY(idx) + 4} fontSize={10.5} fill={theme.text.port}>
                      {p.name}
                    </text>
                  </g>
                ))}
                {/* 输出端口 */}
                {n.num_outputs > 0 && (
                  <circle cx={NODE_W} cy={HEADER_H + 10} r={4.5} fill={color} stroke={theme.bg.canvas} strokeWidth={1.4} />
                )}
                {/* 关键参数 chip */}
                {vals.length > 0 && (
                  <g transform={`translate(8, ${HEADER_H + portCount(n) * PORT_GAP + 6})`}>
                    {vals.map(([k, v], vi) => (
                      <g key={k} transform={`translate(0, ${vi * 14})`}>
                        <text x={0} y={10} fontSize={9.5} fill={theme.text.dim}>
                          {k}: <tspan fill={theme.text.tertiary}>{v}</tspan>
                        </text>
                      </g>
                    ))}
                  </g>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* 节点详情弹窗（固定） */}
      {pinned && nodeById.has(pinned) && (() => {
        const n = nodeById.get(pinned)!;
        const color = CAT_COLOR[n.category] ?? CAT_COLOR.other;
        const allVals = Object.entries(n.values);
        return (
          <div
            onClick={() => setPinned(null)}
            style={{
              position: 'absolute',
              left: 16,
              top: 16,
              maxWidth: 260,
              background: theme.bg.popup,
              border: `1px solid ${color}80`,
              borderRadius: 10,
              padding: '12px 14px',
              color: theme.text.secondary,
              fontSize: 12,
              zIndex: 10,
              boxShadow: '0 6px 24px rgba(0,0,0,0.5)',
              backdropFilter: 'blur(4px)',
              cursor: 'pointer',
              pointerEvents: 'auto',
              userSelect: 'text',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: color, flexShrink: 0 }} />
              <span style={{ fontWeight: 700, fontSize: 13, color: theme.text.primary }}>{n.title}</span>
              <span style={{ marginLeft: 'auto', fontSize: 10, color: theme.text.dim }}>{n.type}</span>
            </div>
            <div style={{ marginBottom: 6 }}>
              <span style={{ color: theme.text.hint }}>分类：</span>
              <span style={{ color: theme.text.muted }}>{CAT_LABEL[n.category] || n.category}</span>
            </div>
            <div style={{ marginBottom: 6 }}>
              <span style={{ color: theme.text.hint }}>输入槽：</span>
              <span style={{ color: theme.text.muted }}>{n.input_links.map((p) => p.name).join(', ') || '—'}</span>
            </div>
            {allVals.length > 0 && (
              <div>
                <div style={{ color: theme.text.hint, marginBottom: 4 }}>参数：</div>
                {allVals.map(([k, v]) => (
                  <div key={k} style={{ paddingLeft: 8, marginBottom: 2 }}>
                    <span style={{ color: theme.text.dim }}>{k}: </span>
                    <span style={{ color: theme.text.tertiary, fontFamily: 'monospace', fontSize: 11 }}>{v}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })()}

      {/* 图例 + 统计 */}
      <div
        style={{
          position: 'absolute',
          left: 10,
          bottom: 10,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 6,
          maxWidth: '70%',
          pointerEvents: 'none',
        }}
      >
        {Object.entries(CAT_LABEL).map(([k, label]) => (
          <span
            key={k}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 10.5,
              color: theme.text.muted,
              background: theme.bg.legend,
              padding: '2px 6px',
              borderRadius: 6,
            }}
          >
            <span style={{ width: 8, height: 8, borderRadius: 2, background: CAT_COLOR[k] }} />
            {label}
          </span>
        ))}
      </div>
      <div
        style={{
          position: 'absolute',
          right: 10,
          bottom: 10,
          fontSize: 10.5,
          color: theme.text.dim,
          background: theme.bg.legend,
          padding: '2px 8px',
          borderRadius: 6,
          pointerEvents: 'none',
        }}
      >
        {graph.nodes.length} 节点 · {graph.edges.length} 连线
      </div>
    </div>
  );
}
