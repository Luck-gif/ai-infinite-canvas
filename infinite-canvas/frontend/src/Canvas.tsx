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
import type { CanvasNode, ShotStatus, NodeKind } from './types';
import { defaultPortsForKind } from './types';
import { theme } from './theme';

// ── v5.1 端口可视化 ──────────────────────────────────────────────
/** 端口类型 → 颜色映射 */
const PORT_COLORS: Record<string, string> = {
  image: theme.accent.blue,
  video: theme.accent.rose,
  text: theme.accent.amber,
  audio: theme.accent.purple,
  prompt: theme.accent.teal,
  control: theme.accent.green,
};

// v5.1 端口类型 → 中文标签（预留给未来端口 tooltip）
// const PORT_LABELS: Record<string, string> = { ... };

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
  /** v5.1 端口连线中: 正在拖拽的端口 ID */
  linkingFromPortId: string | null;
  onStartLink: (id: string) => void;
  onStartPortLink: (nodeId: string, portId: string) => void;
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
  linkingFromPortId,
  onStartLink: _onStartLink,
  onStartPortLink,
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
  const isText = node.kind === 'text';
  const isAudio = node.kind === 'audio';
  const ctrlColor = node.controlKind === 'controlnet' ? theme.accent.purple : theme.modeColor.outpaint;

  // v5.1 端口系统：从节点 ports 拆分 input/output
  const nodePorts = node.ports ?? defaultPortsForKind(node.kind as NodeKind);
  const inputPorts = nodePorts.filter((p) => p.direction === 'input');
  const outputPorts = nodePorts.filter((p) => p.direction === 'output');
  const portRadius = 5;
  const getPortPos = (_port: { direction: string }, i: number, total: number, side: 'left' | 'right') => {
    const spacing = node.height / (total + 1);
    return {
      x: side === 'left' ? 0 : node.width,
      y: spacing * (i + 1),
    };
  };

  useEffect(() => {
    if (isControl || isText || isAudio) return; // 控制/文本/音频节点无位图，跳过加载
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
    : isText
    ? { label: node.textData?.role ?? '📝 备注', color: theme.accent.amber }
    : isAudio
    ? { label: '🎵 音频', color: theme.accent.purple }
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
    : isText
    ? (node.textData?.content ?? '').slice(0, 60) + ((node.textData?.content?.length ?? 0) > 60 ? '…' : '')
    : isAudio
    ? 'AI 音频生成'
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
        fill={isControl ? (node.controlKind === 'controlnet' ? theme.bg.controlnet : theme.bg.lora) : isText ? '#1a1f2e' : isAudio ? '#1e1a2e' : theme.bg.nodeCard}
        stroke={selected || multiSelected ? (multiSelected && !selected ? theme.misc.selectMulti : theme.accent.blue) : theme.border.subtle}
        strokeWidth={selected ? 2.5 : multiSelected ? 2 : 1.5}
        shadowColor="#000"
        shadowBlur={8}
        shadowOpacity={0.4}
      />
      {!isControl && !isText && !isAudio && (
        <KonvaImage image={imgRef.current || undefined} width={node.width} height={node.height} cornerRadius={8} />
      )}
      {/* v5.1 文本节点：显示内容预览 */}
      {isText && node.textData && (
        <Group x={12} y={12}>
          <Text
            text={`${node.textData.role === 'prompt' ? '📋' : node.textData.role === 'script' ? '🎬' : node.textData.role === 'description' ? '📖' : '📝'} ${node.textData.role === 'prompt' ? '提示词' : node.textData.role === 'script' ? '脚本' : node.textData.role === 'description' ? '描述' : '备注'}`}
            fontSize={12}
            fill={theme.accent.amber}
            fontStyle="bold"
          />
          <Text
            text={node.textData.content.slice(0, 180)}
            y={22}
            width={node.width - 24}
            fontSize={node.textData.fontSize ?? 13}
            fill={theme.text.secondary}
            fontFamily="'JetBrains Mono', 'Input Mono', monospace"
            lineHeight={1.5}
          />
          {node.textData.content.length > 180 && (
            <Text text="… (双击编辑)" y={node.height - 54} fontSize={10} fill={theme.text.dim} />
          )}
        </Group>
      )}
      {/* v5.1 音频节点：波形占位 + 播放控制 */}
      {isAudio && (
        <Group x={16} y={16}>
          {/* 波形占位线条 */}
          {Array.from({ length: 16 }).map((_, i) => (
            <Line
              key={`wave-${i}`}
              points={[i * 17, 30 + Math.sin(i * 0.7) * 8, i * 17, 30 - Math.sin(i * 0.7) * 8]}
              stroke={theme.accent.purple}
              strokeWidth={3}
              opacity={0.5 + Math.random() * 0.5}
              lineCap="round"
            />
          ))}
          <Text
            text="🔊 音频"
            x={0} y={0}
            fontSize={13}
            fill={theme.accent.purple}
            fontStyle="bold"
          />
          <Text
            text={node.prompt || '未生成音频'}
            x={0} y={20}
            width={node.width - 32}
            fontSize={11}
            fill={theme.text.dim}
            ellipsis
            wrap="none"
          />
        </Group>
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
        <Text
          text={isText ? (node.textData?.content ?? '文本').slice(0, 30) : (node.prompt || node.filename)}
          x={8} y={3} width={node.width - 16} height={14} fontSize={12} fill={theme.text.secondary} ellipsis wrap="none"
        />
        <Text text={sub} x={8} y={16} width={node.width - 16} height={12} fontSize={10} fill={theme.text.dim} ellipsis wrap="none" />
      </Group>
      {/* v5.1 端口系统: 输入端口(左侧) + 输出端口(右侧) */}
      {inputPorts.map((port, i) => {
        const pos = getPortPos(port, i, inputPorts.length, 'left');
        const color = PORT_COLORS[port.type] || '#888';
        const isConnected = port.connectedTo != null && port.connectedTo.length > 0;
        return (
          <Group key={`ip-${port.id}`} x={pos.x} y={pos.y} offsetX={portRadius} offsetY={portRadius}>
            <Circle
              radius={portRadius}
              fill={isConnected ? color : theme.bg.canvas}
              stroke={color}
              strokeWidth={2}
              onMouseDown={(e) => {
                e.cancelBubble = true;
                groupRef.current?.draggable(false);
                onStartPortLink(node.id, port.id);
              }}
              onMouseEnter={(e) => {
                const t = e.target as Konva.Circle;
                t.scale({ x: 1.3, y: 1.3 });
                document.body.style.cursor = 'crosshair';
              }}
              onMouseLeave={(e) => {
                const t = e.target as Konva.Circle;
                t.scale({ x: 1, y: 1 });
                if (!linkingFromPortId) document.body.style.cursor = 'default';
              }}
            />
          </Group>
        );
      })}
      {outputPorts.map((port, i) => {
        const pos = getPortPos(port, i, outputPorts.length, 'right');
        const color = PORT_COLORS[port.type] || '#888';
        const isConnected = port.connectedTo != null && port.connectedTo.length > 0;
        return (
          <Group key={`op-${port.id}`} x={pos.x} y={pos.y} offsetX={-portRadius} offsetY={portRadius}>
            <Circle
              radius={portRadius}
              fill={isConnected ? color : theme.bg.canvas}
              stroke={color}
              strokeWidth={2}
              onMouseDown={(e) => {
                e.cancelBubble = true;
                groupRef.current?.draggable(false);
                onStartPortLink(node.id, port.id);
              }}
              onMouseEnter={(e) => {
                const t = e.target as Konva.Circle;
                t.scale({ x: 1.3, y: 1.3 });
                document.body.style.cursor = 'crosshair';
              }}
              onMouseLeave={(e) => {
                const t = e.target as Konva.Circle;
                t.scale({ x: 1, y: 1 });
                if (!linkingFromPortId) document.body.style.cursor = 'default';
              }}
            />
          </Group>
        );
      })}
    </Group>
  );
}

/** v5.1 右键上下文菜单项 */
function CtxMenuItem({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: '6px 10px',
        borderRadius: 4,
        cursor: 'pointer',
        fontSize: 12,
        color: theme.text.secondary,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
      onMouseEnter={(e) => { (e.target as HTMLElement).style.background = theme.bg.input; }}
      onMouseLeave={(e) => { (e.target as HTMLElement).style.background = 'transparent'; }}
    >
      <span>{icon}</span>
      <span>{label}</span>
    </div>
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
  const removeNode = useCanvasStore((s) => s.removeNode);
  const removePortEdge = useCanvasStore((s) => s.removePortEdge);
  // v4.51: 三层画布模式
  const activeLayer = useCanvasStore((s) => s.activeLayer);
  // v5.1: 端口连线
  const portEdges = useCanvasStore((s) => s.portEdges);
  const addPortEdge = useCanvasStore((s) => s.addPortEdge);

  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 });
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [linkingFrom, setLinkingFrom] = useState<string | null>(null);
  const [linkCursor, setLinkCursor] = useState<{ x: number; y: number } | null>(null);
  // v5.1: 端口连线状态
  const [linkingFromPortId, setLinkingFromPortId] = useState<string | null>(null);
  const [linkingFromNodeId, setLinkingFromNodeId] = useState<string | null>(null);
  // v5.1: 右键菜单
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

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
    // v5.1 右键菜单
    if (e.evt.button === 2) {
      e.evt.preventDefault();
      if (e.target === e.target.getStage()) { setCtxMenu(null); return; }
      const stage = stageRef.current;
      if (!stage) return;
      const pos = stage.getRelativePointerPosition();
      if (!pos) return;
      const hitNode = nodes.find(
        (n) => pos.x >= n.x && pos.x <= n.x + n.width && pos.y >= n.y && pos.y <= n.y + n.height,
      );
      if (hitNode) {
        select(hitNode.id);
        setCtxMenu({ x: e.evt.clientX, y: e.evt.clientY, nodeId: hitNode.id });
      } else {
        setCtxMenu(null);
      }
      return;
    }
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
    if (!linkingFrom && !linkingFromPortId || !stageRef.current) return;
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

    // v5.1 端口连线完成检测
    if (linkingFromPortId && linkingFromNodeId && stageRef.current) {
      const pos = stageRef.current.getRelativePointerPosition();
      if (pos) {
        // 寻找鼠标落在的节点，并找到最近的输入端口
        const hitNode = nodes.find(
          (n) =>
            pos.x >= n.x &&
            pos.x <= n.x + n.width &&
            pos.y >= n.y &&
            pos.y <= n.y + n.height &&
            n.id !== linkingFromNodeId,
        );
        if (hitNode) {
          const hitPorts = (hitNode.ports ?? defaultPortsForKind(hitNode.kind as NodeKind)).filter(
            (p) => p.direction === 'input',
          );
          if (hitPorts.length === 1) {
            addPortEdge({
              id: `pe-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
              fromPortId: linkingFromPortId,
              toPortId: hitPorts[0].id,
              label: '',
            });
          } else if (hitPorts.length > 1) {
            // 多个输入端口：选择离鼠标最近的
            const spacing = hitNode.height / (hitPorts.length + 1);
            let closest = hitPorts[0];
            let minDist = Infinity;
            hitPorts.forEach((p, i) => {
              const py = hitNode.y + spacing * (i + 1);
              const dist = Math.abs(pos.y - py);
              if (dist < minDist) { minDist = dist; closest = p; }
            });
            addPortEdge({
              id: `pe-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
              fromPortId: linkingFromPortId,
              toPortId: closest.id,
              label: '',
            });
          }
        }
      }
      setLinkingFromPortId(null);
      setLinkingFromNodeId(null);
      setLinkCursor(null);
      document.body.style.cursor = 'default';
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

  // v5.1 端口连线起始
  const startPortLink = (nodeId: string, portId: string) => {
    const n = nodes.find((x) => x.id === nodeId);
    if (!n) return;
    setLinkingFromPortId(portId);
    setLinkingFromNodeId(nodeId);
    // 从端口的节点坐标开始（相对于 stage）
    const ports = n.ports ?? defaultPortsForKind(n.kind as NodeKind);
    const port = ports.find(p => p.id === portId);
    if (port) {
      const idx = port.direction === 'input'
        ? ports.filter(p => p.direction === 'input').indexOf(port)
        : ports.filter(p => p.direction === 'output').indexOf(port);
      const total = port.direction === 'input'
        ? ports.filter(p => p.direction === 'input').length
        : ports.filter(p => p.direction === 'output').length;
      const spacing = n.height / (total + 1);
      const portY = n.y + spacing * (idx + 1);
      const portX = port.direction === 'input' ? n.x : n.x + n.width;
      setLinkCursor({ x: portX, y: portY });
    }
  };

  // v5.1 计算端口连线的起止点（用于渲染）
  const portEdgeLines = useMemo(() => {
    const lines: { id: string; x1: number; y1: number; x2: number; y2: number }[] = [];
    for (const pe of portEdges) {
      // 找到 fromPort 和 toPort
      let fromX = 0, fromY = 0, toX = 0, toY = 0;
      for (const n of nodes) {
        const pts = n.ports ?? defaultPortsForKind(n.kind as NodeKind);
        const fp = pts.find(p => p.id === pe.fromPortId);
        const tp = pts.find(p => p.id === pe.toPortId);
        if (fp) {
          const total = pts.filter(p => p.direction === fp.direction).length;
          const idx = pts.filter(p => p.direction === fp.direction).indexOf(fp);
          const spacing = n.height / (total + 1);
          fromY = n.y + spacing * (idx + 1);
          fromX = fp.direction === 'input' ? n.x : n.x + n.width;
        }
        if (tp) {
          const total = pts.filter(p => p.direction === tp.direction).length;
          const idx = pts.filter(p => p.direction === tp.direction).indexOf(tp);
          const spacing = n.height / (total + 1);
          toY = n.y + spacing * (idx + 1);
          toX = tp.direction === 'input' ? n.x : n.x + n.width;
        }
      }
      lines.push({ id: pe.id, x1: fromX, y1: fromY, x2: toX, y2: toY });
    }
    return lines;
  }, [nodes, portEdges]);

  const onHover = (node: CanvasNode, e: KonvaEventObject<MouseEvent>) => {
    setHover({ node, clientX: e.evt.clientX, clientY: e.evt.clientY });
    setHoveredNodeId(node.id);
  };

  // v5.1: 获取 hovered 节点相关的端口连线 ID 集合，用于高亮
  const highlightedPortEdgeIds = useMemo(() => {
    if (!hoveredNodeId) return new Set<string>();
    const ids = new Set<string>();
    const hoveredNode = nodes.find(n => n.id === hoveredNodeId);
    if (!hoveredNode) return ids;
    const nodePorts = hoveredNode.ports ?? defaultPortsForKind(hoveredNode.kind as NodeKind);
    const portIds = new Set(nodePorts.map(p => p.id));
    for (const pe of portEdges) {
      if (portIds.has(pe.fromPortId) || portIds.has(pe.toPortId)) {
        ids.add(pe.id);
      }
    }
    return ids;
  }, [hoveredNodeId, nodes, portEdges]);

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
          {/* v5.1 端口连线渲染 */}
          {portEdgeLines.map((l) => {
            const hl = highlightedPortEdgeIds.has(l.id);
            return (
              <Arrow
                key={'pe-' + l.id}
                points={[l.x1, l.y1, l.x2, l.y2]}
                stroke={hl ? theme.accent.amber : theme.accent.purple}
                strokeWidth={hl ? 3 : 2}
                pointerLength={hl ? 10 : 8}
                pointerWidth={hl ? 8 : 7}
                opacity={hl ? 1 : 0.55}
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
          {linkingFromPortId &&
            linkCursor &&
            (() => {
              const src = nodes.find((n) => n.id === linkingFromNodeId);
              if (!src) return null;
              const ports = src.ports ?? defaultPortsForKind(src.kind as NodeKind);
              const port = ports.find(p => p.id === linkingFromPortId);
              if (!port) return null;
              const directionPorts = ports.filter(p => p.direction === port.direction);
              const idx = directionPorts.indexOf(port);
              const spacing = src.height / (directionPorts.length + 1);
              const px = port.direction === 'input' ? src.x : src.x + src.width;
              const py = src.y + spacing * (idx + 1);
              const color = PORT_COLORS[port.type] || '#888';
              return (
                <Line points={[px, py, linkCursor.x, linkCursor.y]} stroke={color} strokeWidth={2} dash={[5, 5]} opacity={0.9} />
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
              linkingFromPortId={linkingFromPortId}
              onStartLink={startLink}
              onStartPortLink={startPortLink}
              onDragMove={dragMove}
              onDragEnd={commitMove}
              onClick={(id) => select(id)}
              onShiftClick={(id) => toggleSelectNode(id)}
              onHover={onHover}
              onHoverEnd={() => { setHover(null); setHoveredNodeId(null); }}
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

      {/* v5.1 右键上下文菜单 */}
      {ctxMenu && (
        <div
          style={{
            position: 'fixed',
            left: ctxMenu.x,
            top: ctxMenu.y,
            background: theme.bg.hoverCard,
            border: `1px solid ${theme.border.subtle}`,
            borderRadius: 8,
            padding: 4,
            minWidth: 140,
            zIndex: 100,
            boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
          }}
          onMouseLeave={() => setCtxMenu(null)}
          onClick={() => setCtxMenu(null)}
        >
          <CtxMenuItem icon="✂️" label="删除节点" onClick={() => { removeNode(ctxMenu.nodeId); }} />
          <CtxMenuItem
            icon="🔌"
            label="断开所有端口连线"
            onClick={() => {
              const node = nodes.find(n => n.id === ctxMenu.nodeId);
              if (node) {
                const pts = node.ports ?? defaultPortsForKind(node.kind as NodeKind);
                const ptIds = new Set(pts.map(p => p.id));
                portEdges.forEach(pe => {
                  if (ptIds.has(pe.fromPortId) || ptIds.has(pe.toPortId)) {
                    removePortEdge(pe.id);
                  }
                });
              }
            }}
          />
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
