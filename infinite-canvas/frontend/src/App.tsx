// 无限画布 · 主应用（Phase 1 MVP 布局 + 工具栏 + 快捷键 + Toast 通知）
// v4.27: Toast 通知 / 状态自动刷新 / 快捷键提示
import { useCallback, useEffect, useRef, useState } from 'react';
import { Canvas } from './Canvas';
import { ControlPanel } from './ControlPanel';
import { WorkflowPanel } from './WorkflowPanel';
import Timeline from './Timeline';
import { WorkflowLibrary } from './WorkflowLibrary';
import { WorkflowGeneratePanel } from './WorkflowGeneratePanel';
import { StoryboardPanel } from './StoryboardPanel';
import { LayerPanel } from './LayerPanel';
import { NodeEditPanel } from './NodeEditPanel';
import { EntityBrowserPanel } from './EntityBrowserPanel';
import type { WorkflowLibraryData, WorkflowGraph } from './types';
import { useCanvasStore, serializeNodes, deserializeNodes } from './store';
import { exportCanvasZip, getStatus } from './api';
import { theme } from './theme';

interface ToastItem {
  id: number;
  type: 'info' | 'success' | 'error';
  message: string;
}

let toastId = 0;
export const toastChannel = {
  _listener: null as null | ((t: ToastItem) => void),
  push(type: ToastItem['type'], message: string) {
    if (this._listener) this._listener({ id: ++toastId, type, message });
  },
};

export function App() {
  const undo = useCanvasStore((s) => s.undo);
  const redo = useCanvasStore((s) => s.redo);
  const clear = useCanvasStore((s) => s.clear);
  const replaceAll = useCanvasStore((s) => s.replaceAll);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const nodes = useCanvasStore((s) => s.nodes);
  const liveWorkflow = useCanvasStore((s) => s.liveWorkflow);
  const viewWorkflow = useCanvasStore((s) => s.viewWorkflow);
  const wfOpen = useCanvasStore((s) => s.wfOpen);
  const setWfOpen = useCanvasStore((s) => s.setWfOpen);
  const timelineOpen = useCanvasStore((s) => s.timelineOpen);
  const setTimelineOpen = useCanvasStore((s) => s.setTimelineOpen);

  const [conn, setConn] = useState<string>('…');
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [wfLibOpen, setWfLibOpen] = useState(false);
  const [wfGenOpen, setWfGenOpen] = useState(false);
  const [storyboardOpen, setStoryboardOpen] = useState(false);
  const [entityBrowserOpen, setEntityBrowserOpen] = useState(false);
  const statusTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── v4.42 工作流库回调 ──────────────────────────────────────────
  const handleLoadWorkflow = useCallback((data: WorkflowLibraryData) => {
    // 加载工作流 → 存入 viewWorkflow → 触发面板显示
    if (data.workflow_graph?.nodes?.length) {
      useCanvasStore.getState().setViewWorkflow(data.workflow_graph);
      setWfOpen(true);
    } else {
      toastChannel.push('info', `已加载工作流「${data.name}」（无可视化图）`);
    }
  }, [setWfOpen]);
  const handleGptGraph = useCallback((graph: WorkflowGraph) => {
    if (graph.nodes?.length && graph.edges?.length) {
      useCanvasStore.getState().setViewWorkflow(graph);
      setWfOpen(true);
    }
  }, [setWfOpen]);

  // Toast 通知订阅
  useEffect(() => {
    toastChannel._listener = (t) => {
      setToasts((prev) => [...prev, t]);
      setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== t.id)), 4000);
    };
    return () => { toastChannel._listener = null; };
  }, []);

  // 状态自动刷新
  const refreshStatus = useCallback(async () => {
    try {
      const s = await getStatus();
      setConn(s.comfyui);
    } catch {
      setConn('offline');
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    statusTimer.current = setInterval(refreshStatus, 30000);
    return () => { if (statusTimer.current) clearInterval(statusTimer.current); };
  }, [refreshStatus]);

  const exportJSON = () => {
    try {
      const data = serializeNodes(useCanvasStore.getState().nodes, useCanvasStore.getState().links);
      const blob = new Blob([data], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `infinite-canvas-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toastChannel.push('success', `导出成功：${useCanvasStore.getState().nodes.length} 个节点`);
    } catch (e) {
      toastChannel.push('error', '导出失败：' + ((e as Error)?.message || String(e)));
    }
  };

  const exportZIP = async () => {
    const curNodes = useCanvasStore.getState().nodes;
    const filenames = curNodes
      .filter((n) => n.filename)
      .map((n) => n.filename);
    if (filenames.length === 0) {
      toastChannel.push('info', '画布中没有可导出的媒体文件');
      setExportMenuOpen(false);
      return;
    }
    try {
      toastChannel.push('info', `正在打包 ${filenames.length} 个文件…`);
      const { blob, added, missing } = await exportCanvasZip(filenames);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `canvas-media-${Date.now()}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      let msg = `打包完成：${added} 个文件`;
      if (missing > 0) msg += `，${missing} 个缺失`;
      toastChannel.push('success', msg);
    } catch (e) {
      toastChannel.push('error', '导出失败：' + ((e as Error)?.message || String(e)));
    } finally {
      setExportMenuOpen(false);
    }
  };

  const importJSON = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json';
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return;
      const fr = new FileReader();
      fr.onload = () => {
        try {
          const imported = deserializeNodes(String(fr.result));
          replaceAll(imported);
          toastChannel.push('success', `导入成功：${imported.length} 个节点`);
        } catch (e) {
          toastChannel.push('error', '导入失败：文件格式无效');
        }
      };
      fr.readAsText(file);
    };
    input.click();
  };

  const handleClear = () => {
    clear();
    toastChannel.push('info', '画布已清空（可 Ctrl+Z 撤销）');
  };

  // 生成前预览工作流到达时自动展开面板
  useEffect(() => {
    if (liveWorkflow) setWfOpen(true);
  }, [liveWorkflow, setWfOpen]);

  const selectedNode = selectedId ? nodes.find((n) => n.id === selectedId) ?? null : null;
  const displayGraph = viewWorkflow ?? liveWorkflow ?? selectedNode?.workflowGraph ?? null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'TEXTAREA' || tag === 'INPUT') return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if (e.key === 'Delete') {
        // v4.28 支持多选批量删除
        const allSelected = useCanvasStore.getState().getAllSelectedIds();
        if (allSelected.length > 0) {
          e.preventDefault();
          allSelected.forEach((id) => useCanvasStore.getState().removeNode(id));
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [undo, redo]);

  const connColor = conn === 'connected' ? theme.accent.green : conn === 'disconnected' ? theme.accent.amber : theme.text.label;
  const connLabel = conn === 'connected' ? '已连接' : conn === 'disconnected' ? '未连接' : conn === 'offline' ? '离线' : '检测中…';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: theme.bg.root, color: theme.text.primary }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: '10px 18px',
          borderBottom: `1px solid ${theme.border.default}`,
          background: theme.bg.header,
        }}
      >
        <span style={{ fontSize: 16, fontWeight: 700, userSelect: 'none' }}>无限画布</span>
        <span style={{ fontSize: 12, color: theme.text.hint, userSelect: 'none' }}>v4.50</span>

        {/* 状态指示器 */}
        <span
          title={`ComfyUI 状态：${connLabel}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 12,
            color: theme.text.label,
            background: theme.bg.card,
            padding: '3px 10px',
            borderRadius: 10,
            border: `1px solid ${connColor}40`,
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: connColor,
              display: 'inline-block',
              boxShadow: conn === 'connected' ? `0 0 6px ${connColor}` : undefined,
              animation: conn === 'connected' ? 'app-status-pulse 2s infinite' : undefined,
            }}
          />
          <span>ComfyUI {connLabel}</span>
          <style>{`@keyframes app-status-pulse{0%,100%{opacity:1}50%{opacity:.5}}`}</style>
        </span>

        {/* 节点计数 */}
        <span style={{ fontSize: 12, color: theme.text.dim, userSelect: 'none' }}>
          {nodes.length} 个节点
        </span>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <ToolBtn onClick={() => setWfOpen(!wfOpen)} label="工作流" title={wfOpen ? '收起工作流面板' : '展开工作流面板'} />
          <ToolBtn onClick={() => setTimelineOpen(!timelineOpen)} label="时间轴" title={timelineOpen ? '收起时间轴' : '展开视频时间轴'} />
          <ToolBtn onClick={() => setWfGenOpen(!wfGenOpen)} label="工作流生成" accent title="v4.50 NL→工作流自动组装" />
          <ToolBtn onClick={() => setStoryboardOpen(!storyboardOpen)} label="分镜规划" accent title="v4.50 多分镜规划与批量组装" />
          <ToolBtn onClick={() => setEntityBrowserOpen(!entityBrowserOpen)} label="实体库" accent title="v4.56 角色/场景/道具/风格实体注册表" />
          <ToolBtn onClick={() => setWfLibOpen(!wfLibOpen)} label="工作流库" title="管理自定义 ComfyUI 工作流 JSON / GPT 创建" />
          <ToolBtn onClick={undo} label="撤销" title="Ctrl+Z" />
          <ToolBtn onClick={redo} label="重做" title="Ctrl+Shift+Z" />
          {/* v4.40 导出下拉：JSON 归档 / ZIP 媒体包 */}
          <div style={{ position: 'relative' }}>
            <ToolBtn
              onClick={() => setExportMenuOpen(!exportMenuOpen)}
              label="导出"
              title="导出画布（JSON 存档 / ZIP 媒体包）"
            />
            {exportMenuOpen && (
              <>
                {/* 遮罩层：点击菜单外关闭 */}
                <div
                  style={{
                    position: 'fixed', inset: 0, zIndex: 9998,
                  }}
                  onClick={() => setExportMenuOpen(false)}
                />
                <div
                  style={{
                    position: 'absolute',
                    top: '100%',
                    right: 0,
                    zIndex: 9999,
                    marginTop: 6,
                    background: theme.bg.surface,
                    borderRadius: theme.radius.md,
                    border: `1px solid ${theme.border.default}`,
                    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                    overflow: 'hidden',
                    minWidth: 160,
                  }}
                >
                  <button
                    onClick={() => { exportJSON(); setExportMenuOpen(false); }}
                    style={{
                      display: 'block', width: '100%', padding: '10px 16px',
                      background: 'transparent', border: 'none',
                      color: theme.text.primary, cursor: 'pointer',
                      fontSize: 13, textAlign: 'left',
                      borderBottom: `1px solid ${theme.border.subtle}`,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = theme.bg.hover)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    导出 JSON 存档
                  </button>
                  <button
                    onClick={exportZIP}
                    style={{
                      display: 'block', width: '100%', padding: '10px 16px',
                      background: 'transparent', border: 'none',
                      color: theme.text.primary, cursor: 'pointer',
                      fontSize: 13, textAlign: 'left',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = theme.bg.hover)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    打包下载 ZIP
                  </button>
                </div>
              </>
            )}
          </div>
          <ToolBtn onClick={importJSON} label="导入" title="导入存档 JSON" />
          <ToolBtn onClick={handleClear} label="清空" danger title="清空画布（可撤销）" />
        </div>
      </header>

      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <ControlPanel />
        <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
          <Canvas />
          {wfOpen && displayGraph && (
            <WorkflowPanel
              graph={displayGraph}
              title={selectedNode?.prompt ? selectedNode.prompt.slice(0, 16) : '生成结果'}
              live={!!liveWorkflow}
              onClose={() => setWfOpen(false)}
            />
          )}
        </div>
      </div>

      {/* Toast 通知层 */}
      <ToastLayer toasts={toasts} />

      {/* v4.39 视频时间轴面板 */}
      {timelineOpen && <Timeline />}

      {/* v4.42 自定义工作流库 + GPT */}
      {wfLibOpen && (
        <WorkflowLibrary
          onClose={() => setWfLibOpen(false)}
          onLoadWorkflow={handleLoadWorkflow}
          onGptGraph={handleGptGraph}
        />
      )}

      {/* v4.50 工作流生成面板 */}
      {wfGenOpen && (
        <WorkflowGeneratePanel
          onClose={() => setWfGenOpen(false)}
        />
      )}

      {/* v4.50 分镜规划面板 */}
      {storyboardOpen && (
        <StoryboardPanel
          onClose={() => setStoryboardOpen(false)}
        />
      )}

      {/* v4.56 实体浏览器面板 */}
      {entityBrowserOpen && (
        <EntityBrowserPanel
          onClose={() => setEntityBrowserOpen(false)}
        />
      )}

      {/* v4.50 三层画布面板 */}
      <LayerPanel />

      {/* v4.54 节点属性编辑面板 */}
      {selectedId && <NodeEditPanel />}
    </div>
  );
}

function ToolBtn({ onClick, label, danger, accent, title }: { onClick: () => void; label: string; danger?: boolean; accent?: boolean; title?: string }) {
  const accentBg = accent ? '#162040' : danger ? theme.danger.bg : theme.bg.card;
  const accentBorder = accent ? '#4f8cff' : theme.border.card;
  const accentColor = accent ? theme.accent.blue : danger ? theme.danger.text : theme.text.tertiary;
  return (
    <button
      onClick={onClick}
      title={title || label}
      style={{
        padding: '6px 12px',
        borderRadius: 6,
        border: `1px solid ${accentBorder}`,
        background: accentBg,
        color: accentColor,
        fontSize: 12,
        cursor: 'pointer',
        whiteSpace: 'nowrap',
        transition: 'border-color 0.15s, background 0.15s',
      }}
      onMouseEnter={(e) => {
        (e.target as HTMLButtonElement).style.borderColor = danger ? '#cc4444' : accent ? '#6db3ff' : '#4f8cff';
      }}
      onMouseLeave={(e) => {
        (e.target as HTMLButtonElement).style.borderColor = accentBorder;
      }}
    >
      {label}
    </button>
  );
}

function ToastLayer({ toasts }: { toasts: ToastItem[] }) {
  if (toasts.length === 0) return null;
  const color = (t: ToastItem['type']) => {
    switch (t) {
      case 'success': return { bg: theme.success.bg, border: theme.border.success, text: theme.accent.green };
      case 'error': return { bg: theme.danger.bg, border: theme.danger.border, text: theme.danger.text };
      default: return { bg: theme.info.bg, border: theme.info.border, text: theme.accent.pastel };
    }
  };
  return (
    <div
      style={{
        position: 'fixed',
        bottom: 68,
        right: 16,
        display: 'flex',
        flexDirection: 'column-reverse',
        gap: 8,
        zIndex: 100,
        pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => {
        const c = color(t.type);
        return (
          <div
            key={t.id}
            style={{
              padding: '10px 16px',
              background: c.bg,
              border: `1px solid ${c.border}`,
              color: c.text,
              borderRadius: 8,
              fontSize: 13,
              maxWidth: 360,
              wordBreak: 'break-all',
              boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
              backdropFilter: 'blur(4px)',
              animation: 'toast-in 0.25s ease',
              pointerEvents: 'auto',
            }}
          >
            {t.message}
          </div>
        );
      })}
      <style>{`@keyframes toast-in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}`}</style>
    </div>
  );
}
