// v4.26 工作流面板：浮于无限画布内，可拖拽/缩放/折叠，展示 ComfyUI 节点图
import { useCallback, useEffect, useRef, useState } from 'react';
import { WorkflowGraph } from './WorkflowGraph';
import type { WorkflowGraph as WG } from './types';
import { theme } from './theme';

const MIN_W = 240;
const MAX_W = 600;
const PANEL_MARGIN = 6;

export function WorkflowPanel({
  graph,
  title,
  live,
  onClose,
}: {
  graph: WG;
  title: string;
  live: boolean;
  onClose: () => void;
}) {
  const [top, setTop] = useState(12);
  const [right, setRight] = useState(12);
  const [panelWidth, setPanelWidth] = useState(380);
  const [collapsed, setCollapsed] = useState(false);
  const [fitKey, setFitKey] = useState(0);
  const [visible, setVisible] = useState(false);

  // 用于全局事件防闭包
  const topRef = useRef(top);
  const rightRef = useRef(right);
  const widthRef = useRef(panelWidth);
  topRef.current = top;
  rightRef.current = right;
  widthRef.current = panelWidth;

  const dragRef = useRef<{
    startX: number; startY: number;
    startTop: number; startRight: number;
  } | null>(null);
  const resizeRef = useRef<{
    startX: number; startWidth: number;
  } | null>(null);

  // 入场动画
  useEffect(() => { requestAnimationFrame(() => setVisible(true)); }, []);

  // Escape 关闭面板
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // 全局鼠标事件：拖拽 + 缩放
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (dragRef.current) {
        const dx = e.clientX - dragRef.current.startX;
        const dy = e.clientY - dragRef.current.startY;
        setTop(Math.max(PANEL_MARGIN, dragRef.current.startTop + dy));
        setRight(Math.max(PANEL_MARGIN, dragRef.current.startRight - dx));
      }
      if (resizeRef.current) {
        const delta = resizeRef.current.startX - e.clientX;
        const nw = Math.max(MIN_W, Math.min(MAX_W, resizeRef.current.startWidth + delta));
        setPanelWidth(nw);
      }
    };
    const onUp = () => {
      if (dragRef.current || resizeRef.current) {
        dragRef.current = null;
        resizeRef.current = null;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, []);

  // 标题栏开始拖拽（排除按钮点击）
  const onHeaderDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return;
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startTop: topRef.current,
      startRight: rightRef.current,
    };
    document.body.style.cursor = 'grabbing';
    document.body.style.userSelect = 'none';
  }, []);

  // 缩放柄按下
  const onResizeDown = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    resizeRef.current = { startX: e.clientX, startWidth: widthRef.current };
    document.body.style.cursor = 'ew-resize';
    document.body.style.userSelect = 'none';
  }, []);

  const displayTitle = title || '生成结果';

  const pulseKeyframes = `@keyframes wf-pulse-p{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.85)}}`;

  return (
    <div
      style={{
        position: 'absolute',
        top,
        right,
        width: collapsed ? 'auto' : panelWidth,
        minWidth: collapsed ? 'auto' : MIN_W,
        maxWidth: collapsed ? 48 : '46%',
        display: 'flex',
        flexDirection: 'column',
        background: theme.bg.overlay,
        border: `1px solid ${theme.border.card}`,
        borderRadius: 12,
        boxShadow: '0 10px 40px rgba(0,0,0,0.55)',
        backdropFilter: 'blur(6px)',
        overflow: 'hidden',
        zIndex: 20,
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateX(0)' : 'translateX(24px)',
        transition: 'opacity 0.22s ease, transform 0.22s ease, width 0.25s ease',
      }}
    >
      <style>{pulseKeyframes}</style>

      {/* 左侧缩放柄 */}
      {!collapsed && (
        <div
          onMouseDown={onResizeDown}
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: 5,
            cursor: 'ew-resize',
            zIndex: 25,
          }}
        />
      )}

      {/* ── 标题栏（可拖拽） ── */}
      <div
        onMouseDown={onHeaderDown}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: collapsed ? '10px 6px' : '10px 12px',
          borderBottom: collapsed ? 'none' : `1px solid ${theme.border.default}`,
          background: theme.bg.headerBar,
          cursor: collapsed ? 'default' : 'grab',
          userSelect: 'none',
          borderRadius: collapsed ? 12 : undefined,
        }}
      >
        {/* 折叠后只显示展开按钮 */}
        {collapsed ? (
          <button
            onClick={() => setCollapsed(false)}
            title="展开工作流面板"
            style={btnIconStyle}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M10 3L6 8l4 5" stroke={theme.text.muted} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        ) : (
          <>
            <span style={{ fontSize: 13, fontWeight: 700, color: theme.text.primary, whiteSpace: 'nowrap' }}>工作流</span>

            {/* 生成中指示灯 + 状态 */}
            <span
              style={{
                fontSize: 11,
                color: live ? theme.accent.yellow : theme.text.dim,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                minWidth: 0,
              }}
            >
              {live && (
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: '#ffd166',
                    boxShadow: '0 0 8px #ffd166',
                    animation: 'wf-pulse-p 1.1s infinite',
                    flexShrink: 0,
                  }}
                />
              )}
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 140 }}>
                {live ? '生成中…' : displayTitle}
              </span>
            </span>

            {/* 右侧按钮组 */}
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 2 }}>
              {/* 适配视图 */}
              <button
                onClick={() => setFitKey((k) => k + 1)}
                title="适配视图"
                style={btnIconStyle}
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M1 6V1h5M15 6V1h-5M1 10v5h5M15 10v5h-5" stroke={theme.text.muted} strokeWidth="1.4" strokeLinecap="round" />
                </svg>
              </button>
              {/* 折叠 */}
              <button
                onClick={() => setCollapsed(true)}
                title="折叠面板"
                style={btnIconStyle}
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M12 3L8 8l4 5" stroke={theme.text.muted} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {/* 关闭 */}
              <button
                onClick={onClose}
                title="关闭 (Esc)"
                style={{ ...btnIconStyle, marginLeft: 2 }}
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M4 4l8 8M12 4l-8 8" stroke={theme.text.muted} strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
            </div>
          </>
        )}
      </div>

      {/* ── 工作流图 ── */}
      {!collapsed && (
        <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          <WorkflowGraph graph={graph} fitKey={fitKey} />
        </div>
      )}
    </div>
  );
}

const btnIconStyle: React.CSSProperties = {
  width: 24,
  height: 24,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  borderRadius: 6,
  border: '1px solid transparent',
  background: 'transparent',
  color: '#9aa6bb',
  cursor: 'pointer',
  outline: 'none',
  transition: 'background 0.15s',
};
