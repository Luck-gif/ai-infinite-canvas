// v4.41 画布性能优化：视口裁剪 + 图片懒加载 + 撤销历史深度限制
// v4.28 画布多选框选：在 v4.20 拖拽连线基础上，
// 增加「Shift+点击多选 / 拖拽空白框选 / 批量删除」能力。
import { useEffect, useMemo, useRef, useState } from 'react';
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
import { getNodeLayer } from './types';
import { computeEdges, computeLinks } from './graph';
import type { LinkEdge } from './graph';
import { MODE_META } from './types';
import type { CanvasNode, ShotStatus } from './types';
import { theme } from './theme';

/** v4.59 分镜状态中文标签 */
function statusLabel(s: ShotStatus): string {
  const map: Record<ShotStatus, string> = {
    idle: '待生成',
    pending: '排队中',
    generating: '生成中',
    done: '已完成',
    failed: '失败',
  };
  return map[s] || s;
}

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

// ── v4.41 视口裁剪 ──────────────────────────────────────────────
/** 视口外扩展边距（canvas 坐标系），防止平移时节点闪入 */
const VIEWPORT_MARGIN = 600;

/** 计算当前视口内可见的节点 ID 集合；节点数 ≤ 20 时跳过裁剪开销 */
function getVisibleNodeIds(
  nodes: CanvasNode[],
  view: View,
  stageW: number,
  stageH: number,
  margin: number = VIEWPORT_MARGIN,
): Set<string> | null {
  if (nodes.length <= 20) return null; // 少节点全量渲染，避免裁剪开销
  if (stageW <= 0 || stageH <= 0) return null;
  const left  = -view.x / view.scale - margin;
  const top   = -view.y / view.scale - margin;
  const right = (stageW - view.x) / view.scale + margin;
  const bottom = (stageH - view.y) / view.scale + margin;
  return new Set(
    nodes
      .filter((n) => {
        if (n.width == null || n.height == null) return true;
        return !(n.x + n.width < left || n.x > right || n.y + n.height < top || n.y > bottom);
      })
      .map((n) => n.id),
  );
}

interface NodeImageProps {
  node: CanvasNode;
  selected: boolean;
  multiSelected: boolean;
  /** v4.41 懒加载：仅视口内节点才加载位图，减少内存与网络开销 */
  isVisible: boolean;
  linkingFrom: string | null;
  onStartLink: (id: string) => void;
  onDragMove: (id: string, x: number, y: number) => void;
  onDragEnd: (id: string, x: number, y: number) => void;
  onClick: (id: string) => void;
  onShiftClick: (id: string) => void;
  onHover: (node: CanvasNode, e: KonvaEventObject<MouseEvent>) => void;
  onHoverEnd: () => void;
}

function NodeImage({
  node,
  selected,
  multiSelected,
  isVisible,
  linkingFrom,
  onStartLink,
  onDragMove,
  onDragEnd,
  onClick,
  onShiftClick,
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
    if (!isVisible) return; // v4.41 懒加载：视口外不加载
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
  }, [node.filename, isVideo, isVisible]);

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
        node.controlImage ? '📎参考图' : null,
      ].filter(Boolean).join(' · ')
    : isVideo
    ? [
        node.mode ? MODE_META[node.mode].label : '视频',
        node.frames != null || node.fps != null ? `${node.frames ?? '?'}f/${node.fps ?? '?'}fps` : null,
        node.seed != null ? `seed ${node.seed}` : null,
        `${node.width}×${node.height}`,
      ].filter(Boolean).join(' · ')
    : node.mode === 'storyboard'
    ? [
        `🎬 分镜 #${node.shotIndex ?? '?'}`,
        node.shotStatus ? statusLabel(node.shotStatus) : null,
        node.shotDuration ? `${node.shotDuration}s` : null,
        node.referenceAssets?.length ? `🔗${node.referenceAssets.length}` : null,
        node.createdAt ? new Date(node.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : null,
      ].filter(Boolean).join(' · ')
    : [
        node.mode ? MODE_META[node.mode].label : '原创',
        node.seed != null ? `seed ${node.seed}` : null,
        `${node.width}×${node.height}`,
        node.templateId ? `模板 ${node.templateId}` : null,
        node.createdAt ? new Date(node.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : null,
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
        if (e.evt.shiftKey) {
          onShiftClick(node.id);
        } else {
          onClick(node.id);
        }
      }}
    >
      <Rect
        width={node.width}
        height={node.height}
        cornerRadius={8}
        fill={isControl ? (node.controlKind === 'controlnet' ? theme.bg.controlnet : theme.bg.lora) : theme.bg.nodeCard}
        stroke={selected || multiSelected ? (multiSelected && !selected ? theme.misc.selectMulti : theme.accent.blue) : theme.border.subtle}
        strokeWidth={selected ? 2.5 : multiSelected ? 2 : 1.5}
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
  const selectedIds = useCanvasStore((s) => s.selectedIds);
  const pendingFocus = useCanvasStore((s) => s.pendingFocus);
  const dragMove = useCanvasStore((s) => s.dragMove);
  const commitMove = useCanvasStore((s) => s.commitMove);
  const select = useCanvasStore((s) => s.select);
  const toggleSelectNode = useCanvasStore((s) => s.toggleSelectNode);
  const setSelectedIds = useCanvasStore((s) => s.setSelectedIds);
  const clearSelection = useCanvasStore((s) => s.clearSelection);
  const addLink = useCanvasStore((s) => s.addLink);
  // v4.51: 三层画布模式
  const activeLayer = useCanvasStore((s) => s.activeLayer);

  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 });
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [linkingFrom, setLinkingFrom] = useState<string | null>(null);
  const [linkCursor, setLinkCursor] = useState<{ x: number; y: number } | null>(null);

  // v4.28 框选状态
  const [boxSelect, setBoxSelect] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);

  const stageRef = useRef<Konva.Stage>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const edges = computeEdges(nodes);
  const linkEdges = computeLinks(nodes, links);

  // v4.55: 按活跃层级过滤显示节点
  const displayNodes = useMemo(
    () => nodes.filter((n) => getNodeLayer(n.mode) === activeLayer),
    [nodes, activeLayer],
  );

  // ── v4.41 视口裁剪：计算当前可见节点 ID 集 ────────────────────
  const visibleNodeIds = useMemo(
    () => getVisibleNodeIds(nodes, view, size.w, size.h),
    [nodes, view.x, view.y, view.scale, size.w, size.h],
  );

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
      // v4.28 在空白区域按下 → 开始框选
      if (e.evt.button === 0) {
        // 检查是否按住了中键/右键（用于平移，不触发框选）
        const stage = stageRef.current;
        if (stage) {
          const pos = stage.getRelativePointerPosition();
          if (pos) {
            setBoxSelect({ x1: pos.x, y1: pos.y, x2: pos.x, y2: pos.y });
          }
        }
      }
      select(null);
      setHover(null);
    }
  };

  const onStageMouseMove = () => {
    // v4.28 框选拖动中：更新 rect
    if (boxSelect && stageRef.current) {
      const pos = stageRef.current.getRelativePointerPosition();
      if (pos) {
        setBoxSelect((prev) => prev ? { ...prev, x2: pos.x, y2: pos.y } : null);
      }
      return;
    }
    if (!linkingFrom || !stageRef.current) return;
    const pos = stageRef.current.getRelativePointerPosition();
    if (pos) setLinkCursor({ x: pos.x, y: pos.y });
  };

  const onStageMouseUp = () => {
    // v4.28 完成框选
    if (boxSelect) {
      const { x1, y1, x2, y2 } = boxSelect;
      const rx = Math.min(x1, x2);
      const ry = Math.min(y1, y2);
      const rw = Math.abs(x2 - x1);
      const rh = Math.abs(y2 - y1);
      // 只有拖动超过 4px 才视为框选
      if (rw > 4 || rh > 4) {
        const hitIds = nodes
          .filter(
            (n) =>
              n.x + n.width >= rx &&
              n.x <= rx + rw &&
              n.y + n.height >= ry &&
              n.y <= ry + rh,
          )
          .map((n) => n.id);
        if (hitIds.length > 0) {
          setSelectedIds(hitIds);
        } else {
          clearSelection();
        }
      }
      setBoxSelect(null);
      return;
    }

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
          {displayNodes.map((n) => {
            // v4.41 视口裁剪：跳过不可见节点（节点数 > 20 时生效）
            if (visibleNodeIds && !visibleNodeIds.has(n.id)) return null;
            const isMultiSelected = selectedIds.includes(n.id) && selectedIds.length >= 2;
            return (
            <NodeImage
              key={n.id}
              node={n}
              selected={n.id === selectedId}
              multiSelected={isMultiSelected}
              isVisible={visibleNodeIds ? visibleNodeIds.has(n.id) : true}
              linkingFrom={linkingFrom}
              onStartLink={startLink}
              onDragMove={dragMove}
              onDragEnd={commitMove}
              onClick={(id) => select(id)}
              onShiftClick={(id) => toggleSelectNode(id)}
              onHover={onHover}
              onHoverEnd={() => setHover(null)}
            />
          )})}
        </Layer>
        {/* v4.28 框选矩形叠加层 */}
        {boxSelect && (
          <Layer listening={false}>
            <Rect
              x={Math.min(boxSelect.x1, boxSelect.x2)}
              y={Math.min(boxSelect.y1, boxSelect.y2)}
              width={Math.abs(boxSelect.x2 - boxSelect.x1)}
              height={Math.abs(boxSelect.y2 - boxSelect.y1)}
              fill="rgba(79,140,255,0.08)"
              stroke="rgba(79,140,255,0.5)"
              strokeWidth={1}
              dash={[4, 3]}
            />
          </Layer>
        )}
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
        滚轮缩放 · 拖动节点移动 · Shift+点击多选 · 拖拽空白框选 · 点节点右侧锚点建立连线
      </div>

      {/* v4.55: 层级上下文统计栏 */}
      {(() => {
        const colors = { planning: '#f0a030', generation: '#4f8cff', output: '#44cc66' };
        const names = { planning: '策划层', generation: '生成层', output: '输出层' };
        const c = colors[activeLayer] || colors.generation;
        const shown = displayNodes.length;
        const total = nodes.length;
        return (
          <div
            style={{
              position: 'absolute', right: 14, top: 14,
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '4px 12px', borderRadius: 20,
              background: `${c}18`,
              border: `1px solid ${c}40`,
              backdropFilter: 'blur(4px)',
              pointerEvents: 'none', userSelect: 'none',
              zIndex: 40,
            }}
          >
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: c }} />
            <span style={{ fontSize: 11, color: theme.text.hint, fontWeight: 500 }}>
              {names[activeLayer] || names.generation}
            </span>
            <span style={{ fontSize: 10, color: theme.text.tiny }}>
              {shown}/{total} 节点
            </span>
          </div>
        );
      })()}

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

      {/* 空画布引导 */}
      {nodes.length === 0 && (
        <div
          style={{
            position: 'absolute', left: '50%', top: '45%', transform: 'translate(-50%, -50%)',
            textAlign: 'center', pointerEvents: 'none', userSelect: 'none', zIndex: 30,
            maxWidth: 420,
          }}
        >
          <div style={{
            width: 72, height: 72, borderRadius: '50%',
            background: 'linear-gradient(135deg, rgba(79,140,255,0.15), rgba(139,92,246,0.15))',
            border: '1px solid rgba(79,140,255,0.25)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 16px', fontSize: 32,
          }}>
            🎨
          </div>
          <div style={{ fontSize: 18, fontWeight: 600, color: theme.text.primary, marginBottom: 8 }}>
            画布为空
          </div>
          <div style={{ fontSize: 13, color: theme.text.secondary, lineHeight: 1.7 }}>
            在左侧输入描述并点击「生成」，或点击上方「工作流生成」「分镜规划」快速开始。<br />
            生成结果会自动出现在画布上，支持拖拽、连线与批量管理。
          </div>
        </div>
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
