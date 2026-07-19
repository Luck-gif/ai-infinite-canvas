// v4.20 节点拖拽连线交互：在 v4.19 血缘可视化基础上，
// 增加「节点右侧锚点拖拽 → 建立手动关联」能力，连线持久化、小地图同步。
import { useEffect, useRef, useState } from 'react';
import {
  Stage,
  Layer,
  Group,
  Rect,
  Image as KonvaImage,
  Text,
  Arrow,
  Circle,
  Line,
} from 'react-konva';
import type Konva from 'konva';
import type { KonvaEventObject } from 'konva/lib/Node';
import { useCanvasStore } from './store';
import { imageUrl } from './api';
import { computeEdges, computeLinks } from './graph';
import type { LinkEdge } from './graph';
import { MODE_META } from './types';
import type { CanvasNode } from './types';
import { theme } from './theme';

interface View {
  x: number;
  y: number;
  scale: number;
}
interface HoverInfo {
  node: CanvasNode;
  clientX: number;
  clientY: number;
}

function center(n: CanvasNode) {
  return { cx: n.x + n.width / 2, cy: n.y + n.height / 2 };
}

interface NodeImageProps {
  node: CanvasNode;
  selected: boolean;
  linkingFrom: string | null;
  onStartLink: (id: string) => void;
  onDragMove: (id: string, x: number, y: number) => void;
  onDragEnd: (id: string, x: number, y: number) => void;
  onClick: (id: string) => void;
  onHover: (node: CanvasNode, e: KonvaEventObject<MouseEvent>) => void;
  onHoverEnd: () => void;
}

function NodeImage({
  node,
  selected,
  linkingFrom,
  onStartLink,
  onDragMove,
  onDragEnd,
  onClick,
  onHover,
  onHoverEnd,
}: NodeImageProps) {
  const imgRef = useRef<HTMLImageElement | HTMLCanvasElement | null>(null);
  const groupRef = useRef<Konva.Group>(null);

  const isControl = node.kind === 'control';
  const isVideo = node.kind === 'video' || /\.(mp4|webm|mov|m4v)$/i.test(node.filename || '');
  const ctrlColor = node.controlKind === 'controlnet' ? theme.accent.purple : theme.modeColor.outpaint;

  useEffect(() => {
    if (isControl) return; // 控制节点无位图，跳过加载
    const w = node.width, h = node.height;
    let alive = true;
    const url = imageUrl(node.filename);
    if (isVideo) {
      // 视频节点：抽首帧到 canvas 作 Konva 静态预览；点击播放见选中面板 <video>
      const v = document.createElement('video');
      v.src = url;
      v.crossOrigin = 'anonymous';
      v.muted = true;
      v.preload = 'metadata';
      v.playsInline = true;
      v.onloadeddata = () => {
        if (!alive) return;
        const c = document.createElement('canvas');
        c.width = w; c.height = h;
        const ctx = c.getContext('2d');
        if (ctx) { try { ctx.drawImage(v, 0, 0, w, h); } catch { /* 跨域污染：跳过 */ } }
        imgRef.current = c;
        groupRef.current?.getLayer()?.batchDraw();
      };
      return () => { alive = false; v.onloadeddata = null; v.removeAttribute('src'); v.load(); };
    }
    const img = new window.Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      if (alive) {
        imgRef.current = img;
        groupRef.current?.getLayer()?.batchDraw();
      }
    };
    img.src = url;
    return () => {
      alive = false;
    };
  }, [node.filename, isVideo]);

  const badge = isControl
    ? { label: node.controlKind === 'controlnet' ? 'ControlNet' : 'LoRA', color: ctrlColor }
    : node.mode ? MODE_META[node.mode] : null;
  const sub = isControl
    ? [
        node.controlKind === 'controlnet'
          ? `模型 ${(node.controlModel || '未选').replace(/\.safetensors$/i, '')}`
          : `LoRA ${(node.loraName || '未选').replace(/\.safetensors$/i, '')}`,
        node.controlKind === 'controlnet'
          ? `类型 ${node.controlType || '—'}`
          : null,
        `强度 ${
          node.controlKind === 'controlnet'
            ? (node.controlStrength ?? 1.0)
            : (node.loraStrength ?? 1.0)
        }`,
      ].filter(Boolean).join(' · ')
    : [
        node.mode ? MODE_META[node.mode].label : '原创',
        node.seed != null ? `seed ${node.seed}` : null,
        node.templateId ? `模板 ${node.templateId}` : null,
      ]
        .filter(Boolean)
        .join(' · ');

  return (
    <Group
      ref={groupRef}
      x={node.x}
      y={node.y}
      draggable={!linkingFrom}
      onDragMove={(e) => onDragMove(node.id, e.target.x(), e.target.y())}
      onDragEnd={(e) => onDragEnd(node.id, e.target.x(), e.target.y())}
      onMouseEnter={(e) => onHover(node, e)}
      onMouseLeave={onHoverEnd}
      onClick={(e) => {
        e.cancelBubble = true;
        onClick(node.id);
      }}
    >
      <Rect
        width={node.width}
        height={node.height}
        cornerRadius={8}
        fill={isControl ? (node.controlKind === 'controlnet' ? theme.bg.controlnet : theme.bg.lora) : theme.bg.nodeCard}
        stroke={selected ? theme.accent.blue : theme.border.subtle}
        strokeWidth={selected ? 2.5 : 1.5}
        shadowColor="#000"
        shadowBlur={8}
        shadowOpacity={0.4}
      />
      {!isControl && (
        <KonvaImage image={imgRef.current || undefined} width={node.width} height={node.height} cornerRadius={8} />
      )}
      {/* 视频节点：居中播放角标，提示可点击播放 */}
      {isVideo && (
        <Group x={node.width / 2 - 14} y={node.height / 2 - 14}>
          <Circle radius={15} fill="rgba(0,0,0,0.5)" />
          <Text text="▶" fontSize={16} fill="#fff" x={5} y={3} />
        </Group>
      )}
      {/* 模式徽章 */}
      {badge && (
        <Group x={8} y={8}>
          <Rect width={64} height={20} cornerRadius={10} fill={badge.color} opacity={0.92} />
          <Text text={badge.label} x={0} y={3} width={64} align="center" fontSize={11} fill="#fff" />
        </Group>
      )}
      {/* 标题条 */}
      <Group x={0} y={node.height - 30}>
        <Rect width={node.width} height={30} cornerRadius={[0, 0, 8, 8]} fill={theme.bg.canvas} opacity={0.82} />
        <Text text={node.prompt || node.filename} x={8} y={3} width={node.width - 16} height={14} fontSize={12} fill={theme.text.secondary} ellipsis wrap="none" />
        <Text text={sub} x={8} y={16} width={node.width - 16} height={12} fontSize={10} fill={theme.text.dim} ellipsis wrap="none" />
      </Group>
      {/* 连线锚点（右侧中点，拖拽可建立手动关联） */}
      <Group x={node.width} y={node.height / 2}>
        <Circle
          radius={7}
          fill="#ffd166"
          stroke={theme.bg.canvas}
          strokeWidth={2}
          onMouseDown={(e) => {
            e.cancelBubble = true;
            groupRef.current?.draggable(false);
            onStartLink(node.id);
          }}
          onMouseEnter={(e) => {
            const t = e.target as Konva.Circle;
            t.scale({ x: 1.35, y: 1.35 });
            document.body.style.cursor = 'crosshair';
          }}
          onMouseLeave={(e) => {
            const t = e.target as Konva.Circle;
            t.scale({ x: 1, y: 1 });
            if (!linkingFrom) document.body.style.cursor = 'default';
          }}
        />
      </Group>
    </Group>
  );
}

export function Canvas() {
  const nodes = useCanvasStore((s) => s.nodes);
  const links = useCanvasStore((s) => s.links);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const pendingFocus = useCanvasStore((s) => s.pendingFocus);
  const dragMove = useCanvasStore((s) => s.dragMove);
  const commitMove = useCanvasStore((s) => s.commitMove);
  const select = useCanvasStore((s) => s.select);
  const addLink = useCanvasStore((s) => s.addLink);

  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 });
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [linkingFrom, setLinkingFrom] = useState<string | null>(null);
  const [linkCursor, setLinkCursor] = useState<{ x: number; y: number } | null>(null);

  const stageRef = useRef<Konva.Stage>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const edges = computeEdges(nodes);
  const linkEdges = computeLinks(nodes, links);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // 聚焦请求：平移使目标节点居中
  useEffect(() => {
    if (!pendingFocus || !stageRef.current || !wrapRef.current) return;
    const n = nodes.find((nd) => nd.id === pendingFocus.id);
    if (!n) return;
    const wrap = wrapRef.current.getBoundingClientRect();
    const next = {
      scale: 1,
      x: wrap.width / 2 - (n.x + n.width / 2),
      y: wrap.height / 2 - (n.y + n.height / 2),
    };
    setView(next);
    stageRef.current.position({ x: next.x, y: next.y });
    stageRef.current.scale({ x: 1, y: 1 });
  }, [pendingFocus, nodes]);

  const onWheel = (e: KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault();
    const stage = stageRef.current!;
    const oldScale = stage.scaleX();
    const pointer = stage.getPointerPosition();
    if (!pointer) return;
    const mousePointTo = {
      x: (pointer.x - stage.x()) / oldScale,
      y: (pointer.y - stage.y()) / oldScale,
    };
    const direction = e.evt.deltaY > 0 ? -1 : 1;
    const factor = 1.08;
    const newScale = direction > 0 ? oldScale * factor : oldScale / factor;
    const clamped = Math.max(0.15, Math.min(4, newScale));
    const newPos = {
      x: pointer.x - mousePointTo.x * clamped,
      y: pointer.y - mousePointTo.y * clamped,
    };
    setView({ x: newPos.x, y: newPos.y, scale: clamped });
  };

  const onStageMouseDown = (e: KonvaEventObject<MouseEvent>) => {
    if (e.target === e.target.getStage()) {
      select(null);
      setHover(null);
    }
  };

  const onStageMouseMove = () => {
    if (!linkingFrom || !stageRef.current) return;
    const pos = stageRef.current.getRelativePointerPosition();
    if (pos) setLinkCursor({ x: pos.x, y: pos.y });
  };

  const onStageMouseUp = () => {
    if (!linkingFrom || !stageRef.current) return;
    const pos = stageRef.current.getRelativePointerPosition();
    let targetId: string | null = null;
    if (pos) {
      const hit = nodes.find(
        (n) =>
          pos.x >= n.x &&
          pos.x <= n.x + n.width &&
          pos.y >= n.y &&
          pos.y <= n.y + n.height &&
          n.id !== linkingFrom,
      );
      if (hit) targetId = hit.id;
    }
    if (targetId) addLink(linkingFrom, targetId);
    setLinkingFrom(null);
    setLinkCursor(null);
    document.body.style.cursor = 'default';
  };

  const startLink = (id: string) => {
    const n = nodes.find((x) => x.id === id);
    if (!n) return;
    const c = center(n);
    setLinkingFrom(id);
    setLinkCursor({ x: c.cx, y: c.cy });
  };

  const onHover = (node: CanvasNode, e: KonvaEventObject<MouseEvent>) => {
    setHover({ node, clientX: e.evt.clientX, clientY: e.evt.clientY });
  };

  const linkCountOf = (id: string) =>
    links.filter((l) => l.from === id || l.to === id).length;

  return (
    <div
      ref={wrapRef}
      style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden', background: theme.bg.canvas }}
    >
      {size.w > 0 && size.h > 0 && (
        <Stage
          ref={stageRef}
          width={size.w}
          height={size.h}
        x={view.x}
        y={view.y}
        scaleX={view.scale}
        scaleY={view.scale}
        onWheel={onWheel}
        onMouseDown={onStageMouseDown}
        onMouseMove={onStageMouseMove}
        onMouseUp={onStageMouseUp}
      >
        {/* 连线层（血缘 + 手动关联 + 临时线，不监听交互） */}
        <Layer listening={false}>
          {edges.map((e) => {
            const a = center(e.from);
            const b = center(e.to);
            const hl = e.from.id === selectedId || e.to.id === selectedId;
            return (
              <Arrow
                key={e.id}
                points={[a.cx, a.cy, b.cx, b.cy]}
                stroke={hl ? theme.accent.blue : theme.misc.edgeDim}
                strokeWidth={hl ? 2.5 : 1.5}
                pointerLength={8}
                pointerWidth={7}
                opacity={hl ? 1 : 0.6}
              />
            );
          })}
          {linkEdges.map((e) => {
            const a = center(e.from);
            const b = center(e.to);
            const hl = e.from.id === selectedId || e.to.id === selectedId;
            return (
              <Arrow
                key={'lnk-' + e.id}
                points={[a.cx, a.cy, b.cx, b.cy]}
                stroke={hl ? '#ffd166' : theme.accent.gold}
                strokeWidth={hl ? 2.5 : 1.5}
                dash={[6, 5]}
                pointerLength={8}
                pointerWidth={7}
                opacity={hl ? 1 : 0.7}
              />
            );
          })}
          {linkingFrom &&
            linkCursor &&
            (() => {
              const src = nodes.find((n) => n.id === linkingFrom);
              if (!src) return null;
              const c = center(src);
              return (
                <Line points={[c.cx, c.cy, linkCursor.x, linkCursor.y]} stroke={theme.accent.yellow} strokeWidth={2} dash={[5, 5]} opacity={0.9} />
              );
            })()}
        </Layer>
        {/* 节点层 */}
        <Layer>
          {nodes.map((n) => (
            <NodeImage
              key={n.id}
              node={n}
              selected={n.id === selectedId}
              linkingFrom={linkingFrom}
              onStartLink={startLink}
              onDragMove={dragMove}
              onDragEnd={commitMove}
              onClick={(id) => select(id)}
              onHover={onHover}
              onHoverEnd={() => setHover(null)}
            />
          ))}
        </Layer>
        </Stage>
      )}

      {/* 悬浮详情 */}
      {hover && !linkingFrom && (
        <div
          style={{
            position: 'fixed',
            left: hover.clientX + 14,
            top: hover.clientY + 14,
            maxWidth: 280,
            background: theme.bg.hoverCard,
            border: `1px solid ${theme.border.subtle}`,
            borderRadius: 8,
            padding: '10px 12px',
            color: theme.text.secondary,
            fontSize: 12,
            pointerEvents: 'none',
            zIndex: 50,
            boxShadow: '0 6px 18px rgba(0,0,0,0.5)',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>{hover.node.prompt || hover.node.filename}</div>
          <div style={{ color: theme.text.dim }}>模板：{hover.node.templateId || '—'}</div>
          <div style={{ color: theme.text.dim }}>
            模式：{hover.node.mode ? MODE_META[hover.node.mode].label : '原创'} · 种子：{hover.node.seed ?? '—'}
          </div>
          {hover.node.negative && <div style={{ color: theme.text.dim }}>负向：{hover.node.negative}</div>}
          <div style={{ color: theme.text.dim }}>
            {hover.node.parentId ? '派生自另一节点' : '原创节点'} · 手动关联 {linkCountOf(hover.node.id)}
          </div>
          {hover.node.createdAt && <div style={{ color: theme.text.dim }}>{new Date(hover.node.createdAt).toLocaleString()}</div>}
        </div>
      )}

      {/* 操作提示 */}
      <div
        style={{
          position: 'absolute',
          left: 12,
          bottom: 12,
          color: theme.text.tiny,
          fontSize: 11,
          userSelect: 'none',
        }}
      >
        滚轮缩放 · 拖动节点移动 · 点节点右侧黄色锚点拖出连线建立关联
      </div>

      {nodes.length > 0 && (
        <Minimap
          nodes={nodes}
          edges={edges}
          linkEdges={linkEdges}
          selectedId={selectedId}
          view={view}
          width={160}
          height={110}
          size={size}
          onNavigate={(newView) => {
            setView(newView);
            stageRef.current?.position({ x: newView.x, y: newView.y });
            stageRef.current?.scale({ x: newView.scale, y: newView.scale });
          }}
        />
      )}
    </div>
  );
}

function Minimap({
  nodes,
  edges,
  linkEdges,
  selectedId,
  view,
  width,
  height,
  size,
  onNavigate,
}: {
  nodes: CanvasNode[];
  edges: { id: string; from: CanvasNode; to: CanvasNode }[];
  linkEdges: LinkEdge[];
  selectedId: string | null;
  view: View;
  width: number;
  height: number;
  size: { w: number; h: number };
  onNavigate: (v: View) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  const allX = nodes.map((n) => n.x);
  const allY = nodes.map((n) => n.y);
  const minX = Math.min(...allX, -view.x / view.scale, 0);
  const minY = Math.min(...allY, -view.y / view.scale, 0);
  const maxX = Math.max(...allX.map((x) => x + 200), (-view.x + size.w) / view.scale, 200);
  const maxY = Math.max(...allY.map((y) => y + 200), (-view.y + size.h) / view.scale, 200);
  const mmW = maxX - minX || 1;
  const mmH = maxY - minY || 1;
  const s = Math.min(width / mmW, height / mmH);
  const toX = (x: number) => (x - minX) * s;
  const toY = (y: number) => (y - minY) * s;
  const fromX = (px: number) => px / s + minX;
  const fromY = (py: number) => py / s + minY;

  const handlePointerDown = (e: React.MouseEvent | React.PointerEvent) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    // 点中转为中心画布坐标 → 设为新视口中心
    const cx = fromX(mx);
    const cy = fromY(my);
    onNavigate({
      x: size.w / 2 - cx * view.scale,
      y: size.h / 2 - cy * view.scale,
      scale: view.scale,
    });
    setDragging(true);
  };

  const handlePointerMove = (e: React.MouseEvent | React.PointerEvent) => {
    if (!dragging) return;
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const cx = fromX(mx);
    const cy = fromY(my);
    onNavigate({
      x: size.w / 2 - cx * view.scale,
      y: size.h / 2 - cy * view.scale,
      scale: view.scale,
    });
  };

  const handlePointerUp = () => setDragging(false);

  return (
    <div
      ref={wrapRef}
      onMouseDown={handlePointerDown}
      onMouseMove={handlePointerMove}
      onMouseUp={handlePointerUp}
      onMouseLeave={handlePointerUp}
      style={{
        position: 'absolute',
        right: 12,
        bottom: 12,
        width,
        height,
        background: theme.bg.minimap,
        border: `1px solid ${dragging ? theme.accent.blue : theme.border.subtle}`,
        borderRadius: 8,
        overflow: 'hidden',
        cursor: dragging ? 'grabbing' : 'pointer',
        transition: 'border-color 0.15s',
      }}
      title="拖拽或点击小地图定位"
    >
      <svg width={width} height={height}>
        {edges.map((e) => {
          const a = center(e.from);
          const b = center(e.to);
          const hl = e.from.id === selectedId || e.to.id === selectedId;
          return (
            <line
              key={e.id}
              x1={toX(a.cx)}
              y1={toY(a.cy)}
              x2={toX(b.cx)}
              y2={toY(b.cy)}
              stroke={hl ? theme.accent.blue : theme.misc.edgeDim}
              strokeWidth={hl ? 2 : 1}
              opacity={hl ? 1 : 0.6}
            />
          );
        })}
        {linkEdges.map((e) => {
          const a = center(e.from);
          const b = center(e.to);
          const hl = e.from.id === selectedId || e.to.id === selectedId;
          return (
            <line
              key={'lnk-' + e.id}
              x1={toX(a.cx)}
              y1={toY(a.cy)}
              x2={toX(b.cx)}
              y2={toY(b.cy)}
              stroke={hl ? '#ffd166' : theme.accent.gold}
              strokeWidth={hl ? 2 : 1}
              strokeDasharray="4 3"
              opacity={hl ? 1 : 0.7}
            />
          );
        })}
        {nodes.map((n) => {
          const cx = toX(n.x + n.width / 2);
          const cy = toY(n.y + n.height / 2);
          const c = n.mode ? MODE_META[n.mode].color : theme.text.dim;
          return (
            <circle
              key={'m' + n.id}
              cx={cx}
              cy={cy}
              r={3.5}
              fill={c}
              stroke={n.id === selectedId ? '#fff' : 'transparent'}
              strokeWidth={1.5}
              style={{ cursor: 'pointer' }}
            />
          );
        })}
        {/* 视口框 */}
        <rect
          x={toX(-view.x / view.scale)}
          y={toY(-view.y / view.scale)}
          width={(size.w / view.scale) * s}
          height={(size.h / view.scale) * s}
          fill="rgba(79,140,255,0.06)"
          stroke={theme.accent.blue}
          strokeWidth={dragging ? 2 : 1}
          opacity={dragging ? 1 : 0.75}
          rx={2}
          style={{ pointerEvents: 'none' }}
        />
      </svg>
    </div>
  );
}
