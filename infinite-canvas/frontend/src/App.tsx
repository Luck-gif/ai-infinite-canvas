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
import { ChatPanel } from './ChatPanel';
import StoryboardTimeline from './StoryboardTimeline';
import { StoryboardWizard } from './StoryboardWizard';
import type { WorkflowLibraryData, WorkflowGraph } from './types';
import { useCanvasStore, serializeNodes, deserializeNodes } from './store';
import { exportCanvasZip, exportProject, getStatus } from './api';
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
  const storyboardTimelineOpen = useCanvasStore((s) => s.storyboardTimelineOpen);
  const setStoryboardTimelineOpen = useCanvasStore((s) => s.setStoryboardTimelineOpen);

  const [conn, setConn] = useState<string>('…');
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [wfLibOpen, setWfLibOpen] = useState(false);
  const [wfGenOpen, setWfGenOpen] = useState(false);
  const [storyboardOpen, setStoryboardOpen] = useState(false);
  const [entityBrowserOpen, setEntityBrowserOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [storyboardWizardOpen, setStoryboardWizardOpen] = useState(false);
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

  const exportProjectFull = async (format: 'zip' | 'json') => {
    const state = useCanvasStore.getState();
    try {
      toastChannel.push('info', '正在导出完整项目…');
      const blob = await exportProject({
        nodes: state.nodes,
        links: state.links,
        port_edges: state.portEdges,
        layers: state.layers,
        timeline: [],
        storyboard_shots: state.storyboardShots,
        entity_ids: [],
        include_media: format === 'zip',
        export_format: format,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const ext = format === 'zip' ? 'zip' : 'json';
      a.download = `canvas-project-${Date.now()}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
      toastChannel.push('success', `项目导出成功（${format.toUpperCase()}）`);
    } catch (e) {
      toastChannel.push('error', '项目导出失败：' + ((e as Error)?.message || String(e)));
    } finally {
      setExportMenuOpen(false);
    }
  };

  const importJSON = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,.zip,application/json,application/zip';
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return;
      const fr = new FileReader();
      fr.onload = () => {
        try {
          const text = String(fr.result);
          const parsed = JSON.parse(text);
          if (parsed && parsed.meta && parsed.canvas) {
            const canvas = parsed.canvas as { nodes: unknown[]; links: unknown[]; port_edges?: unknown[] };
            const imported = deserializeNodes(JSON.stringify({
              version: 1,
              nodes: canvas.nodes,
              links: canvas.links,
              portEdges: canvas.port_edges ?? [],
            }));
            replaceAll(imported);
            const entityCount = parsed.entities ? (parsed.entities as unknown[]).length : 0;
            toastChannel.push('success', `项目导入成功：${imported.length} 个节点, ${entityCount} 个实体`);
          } else {
            const imported = deserializeNodes(text);
            replaceAll(imported);
            toastChannel.push('success', `导入成功：${imported.length} 个节点`);
          }
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
        <span style={{ fontSize: 12, color: theme.text.hint, userSelect: 'none' }}>v5.3</span>

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

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* v5.6 故事板向导入口 */}
          <button
            onClick={() => setStoryboardWizardOpen(!storyboardWizardOpen)}
            title="故事板引导式工作流：剧本→角色→分镜→批量生成"
            style={{
              padding: '7px 16px',
              borderRadius: 8,
              border: `1.5px solid ${storyboardWizardOpen ? '#f59e0b' : '#f59e0b60'}`,
              background: storyboardWizardOpen
                ? 'linear-gradient(135deg, #3a2810, #401a0e)'
                : 'linear-gradient(135deg, #2a1a08, #1a0a04)',
              color: storyboardWizardOpen ? '#fbbf24' : '#d97706',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              transition: 'all 0.2s',
              boxShadow: storyboardWizardOpen ? '0 0 12px rgba(245,158,11,0.3)' : undefined,
            }}
          >
            🎬 故事板向导
            {storyboardWizardOpen && (
              <span style={{
                width: 6, height: 6, borderRadius: '50%',
                background: '#fbbf24', display: 'inline-block',
              }} />
            )}
          </button>

          {/* v5.3 Agent 对话入口 */}
          <button
            onClick={() => setChatOpen(!chatOpen)}
            title="Agent 对话：用自然语言描述创作意图"
            style={{
              padding: '7px 16px',
              borderRadius: 8,
              border: `1.5px solid ${chatOpen ? '#5da3ff' : '#7c3aed80'}`,
              background: chatOpen
                ? 'linear-gradient(135deg, #1a2540, #1e1a40)'
                : 'linear-gradient(135deg, #1e1b4b, #1a0e3e)',
              color: chatOpen ? '#5da3ff' : '#a78bfa',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              transition: 'all 0.2s',
              boxShadow: chatOpen ? '0 0 12px rgba(124,58,237,0.3)' : undefined,
            }}
          >
            💬 Agent
            {chatOpen && (
              <span style={{
                width: 6, height: 6, borderRadius: '50%',
                background: '#5da3ff', display: 'inline-block',
                animation: 'agent-dot-pulse 1.2s infinite',
              }} />
            )}
          </button>
          <style>{`@keyframes agent-dot-pulse{0%,100%{opacity:1}50%{opacity:.3}}`}</style>

          {/* 核心创作入口 */}
          <ToolBtn onClick={() => setWfGenOpen(!wfGenOpen)} label="工作流生成" accent title="NL 描述 → 自动组装 ComfyUI 工作流" />
          <ToolBtn onClick={() => setStoryboardOpen(!storyboardOpen)} label="分镜规划" accent title="多分镜规划、资产绑定与批量生成" />

          <div style={{ width: 1, height: 18, background: theme.border.default, margin: '0 4px' }} />

          {/* 资源与视图 */}
          <ToolBtn onClick={() => setEntityBrowserOpen(!entityBrowserOpen)} label="实体库" title="角色 / 场景 / 道具 / 风格 注册表" />
          <ToolBtn onClick={() => setWfOpen(!wfOpen)} label="工作流" title={wfOpen ? '收起工作流面板' : '展开工作流面板'} />
          <ToolBtn onClick={() => setTimelineOpen(!timelineOpen)} label="视频轴" title={timelineOpen ? '收起视频时间轴' : '展开视频时间轴'} />
          <ToolBtn
            onClick={() => {
              const open = !storyboardTimelineOpen;
              setStoryboardTimelineOpen(open);
              if (open) useCanvasStore.getState().syncStoryboardFromCanvas();
            }}
            label="故事板"
            title="故事板时间轴：拖拽排序 + 批量生成"
          />
          <ToolBtn onClick={() => setWfLibOpen(!wfLibOpen)} label="工作流库" title="管理自定义 ComfyUI 工作流 JSON" />

          <div style={{ width: 1, height: 18, background: theme.border.default, margin: '0 4px' }} />

          <div style={{ width: 1, height: 18, background: theme.border.default, margin: '0 4px' }} />

          {/* v5.1 工作流执行 */}
          <ToolBtn
            onClick={async () => {
              const s = useCanvasStore.getState();
              if (s.portEdges.length === 0) {
                toastChannel.push('info', '没有端口连线，请先在画布上连接节点的端口');
                return;
              }
              // 找根节点：没有被任何线指向的节点（拓扑起点）
              const targetIds = new Set(s.portEdges.map(e => e.toPortId));
              const rootNode = s.nodes.find(n =>
                n.ports?.some(p => p.id && !targetIds.has(p.id) && p.type === 'image')
              );
              if (!rootNode) {
                toastChannel.push('warning', '找不到链路起点，请检查端口连线起始节点');
                return;
              }
              try {
                const res = await fetch('/api/workflow/execute-chain', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    root_node_id: rootNode.id,
                    nodes: s.nodes,
                    port_edges: s.portEdges,
                  }),
                });
                const data = await res.json();
                if (data.results) {
                  // 将生成结果写回节点
                  for (const r of data.results) {
                    if (r.status === 'generated' && r.output_file) {
                      s.updateNode(r.node_id, { filename: r.output_file });
                    }
                  }
                  toastChannel.push('success', `工作流执行完成: ${data.results.length} 个节点`);
                } else {
                  toastChannel.push('error', `执行失败: ${data.error || '未知错误'}`);
                }
              } catch (e) {
                toastChannel.push('error', `执行失败: ${(e as Error).message}`);
              }
            }}
            label="▶ 执行"
            title="执行端口连线工作流"
          />

          <div style={{ width: 1, height: 18, background: theme.border.default, margin: '0 4px' }} />

          {/* 编辑操作 */}
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
                  <div style={{
                    padding: '6px 12px', fontSize: 11, color: '#8899aa',
                    borderBottom: `1px solid ${theme.border.subtle}`,
                  }}>项目完整导出 (v5.4)</div>
                  <button
                    onClick={() => { exportProjectFull('json'); setExportMenuOpen(false); }}
                    style={{
                      display: 'block', width: '100%', padding: '10px 16px',
                      background: 'transparent', border: 'none',
                      color: theme.text.primary, cursor: 'pointer',
                      fontSize: 13, textAlign: 'left',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = theme.bg.hover)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    完整项目 JSON
                  </button>
                  <button
                    onClick={() => exportProjectFull('zip')}
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
                    完整项目 ZIP (±媒体)
                  </button>
                  <div style={{
                    padding: '6px 12px', fontSize: 11, color: '#8899aa',
                    borderBottom: `1px solid ${theme.border.subtle}`,
                  }}>画布存档</div>
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
                    画布 JSON 存档
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
          {/* v5.3 审核过滤器 */}
          <select
            value={useCanvasStore((s) => s.qualityFilter) || 'all'}
            onChange={(e) => useCanvasStore.getState().setQualityFilter(e.target.value)}
            style={{
              padding: '4px 8px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.15)',
              background: 'rgba(255,255,255,0.06)', color: '#e2e8f0', fontSize: 12,
              cursor: 'pointer', minWidth: 80,
            }}
            title="v5.3 按审核状态过滤画布节点"
          >
            <option value="all">🟢 全部</option>
            <option value="approved">✅ 已通过</option>
            <option value="rejected">❌ 已驳回</option>
            <option value="needs_regeneration">🔄 需重生成</option>
            <option value="unreviewed">⏳ 待审核</option>
          </select>
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

      {/* v4.57 故事板时间轴 */}
      {storyboardTimelineOpen && <StoryboardTimeline />}

      {/* v5.3 Agent 对话面板 */}
      {chatOpen && <ChatPanel onClose={() => setChatOpen(false)} />}

      {/* v5.6 故事板引导式工作流 */}
      {storyboardWizardOpen && <StoryboardWizard onClose={() => setStoryboardWizardOpen(false)} />}
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
