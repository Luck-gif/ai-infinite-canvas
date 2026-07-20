// v4.42 自定义 ComfyUI 工作流库 + GPT 辅助创建
// 浮动面板：浏览/保存/加载/删除 ComfyUI 工作流 JSON，以及 GPT 自然语言辅助生成
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  listWorkflows,
  loadWorkflow,
  saveWorkflow,
  deleteWorkflow,
  gptCreateWorkflow,
} from './api';
import type { WorkflowLibraryItem, WorkflowLibraryData, WorkflowGraph } from './types';
import { theme } from './theme';
import { useCanvasStore } from './store';

interface Props {
  onClose: () => void;
  /** 回调：加载工作流 → 外部可将其设为当前预览图 */
  onLoadWorkflow: (data: WorkflowLibraryData) => void;
  /** 回调：GPT 生成的工作流图 */
  onGptGraph: (graph: WorkflowGraph) => void;
}

export function WorkflowLibrary({ onClose, onLoadWorkflow, onGptGraph }: Props) {
  const setWfOpen = useCanvasStore((s) => s.setWfOpen);

  const [items, setItems] = useState<WorkflowLibraryItem[]>([]);
  const [saveOpen, setSaveOpen] = useState(false);
  const [gptOpen, setGptOpen] = useState(false);

  // 保存表单
  const [wfName, setWfName] = useState('');
  const [wfDesc, setWfDesc] = useState('');
  const [wfJson, setWfJson] = useState('');

  // GPT 表单
  const [gptDesc, setGptDesc] = useState('');
  const [gptBusy, setGptBusy] = useState(false);
  const [gptResult, setGptResult] = useState<WorkflowLibraryData | null>(null);

  const refresh = useCallback(() => {
    listWorkflows().then(setItems).catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handleSave = async () => {
    const name = wfName.trim();
    if (!name) return;
    let wf: Record<string, unknown>;
    try {
      wf = JSON.parse(wfJson);
    } catch {
      alert('工作流 JSON 格式错误，请检查语法');
      return;
    }
    try {
      const r = await saveWorkflow(name, wfDesc.trim(), wf);
      alert(`已保存工作流「${r.name}」（${r.node_count} 节点）`);
      setSaveOpen(false);
      setWfName('');
      setWfDesc('');
      setWfJson('');
      refresh();
    } catch (e) {
      alert('保存失败: ' + ((e as Error)?.message || String(e)));
    }
  };

  const handleLoad = async (name: string) => {
    try {
      const data = await loadWorkflow(name);
      onLoadWorkflow(data);
      setWfOpen(true);
      onClose();
    } catch (e) {
      alert('加载失败: ' + ((e as Error)?.message || String(e)));
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`确认删除工作流「${name}」？`)) return;
    try {
      await deleteWorkflow(name);
      refresh();
    } catch (e) {
      alert('删除失败: ' + ((e as Error)?.message || String(e)));
    }
  };

  const handleGpt = async () => {
    const desc = gptDesc.trim();
    if (!desc) return;
    setGptBusy(true);
    setGptResult(null);
    try {
      const r = await gptCreateWorkflow({ description: desc });
      // 构造伪 WorkflowLibraryData 用于预览
      const data: WorkflowLibraryData = {
        name: `GPT-${Date.now().toString(36)}`,
        description: desc,
        saved_at: Date.now() / 1000,
        workflow_json: r.workflow_json,
      };
      setGptResult(data);
      if (r.workflow_graph) {
        onGptGraph(r.workflow_graph);
        setWfOpen(true);
      }
    } catch (e) {
      alert('GPT 生成失败: ' + ((e as Error)?.message || String(e)));
    } finally {
      setGptBusy(false);
    }
  };

  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 100, y: 80 });
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

  const commonBtn: React.CSSProperties = {
    padding: '5px 12px',
    borderRadius: 6,
    border: `1px solid ${theme.border.subtle}`,
    background: theme.bg.card,
    color: theme.text.secondary,
    fontSize: 12,
    cursor: 'pointer',
  };

  const accentBtn: React.CSSProperties = {
    ...commonBtn,
    background: '#1a2744',
    borderColor: '#4f8cff',
    color: theme.accent.blue,
  };

  const dangerBtn: React.CSSProperties = {
    ...commonBtn,
    background: theme.danger.bg,
    borderColor: theme.danger.border,
    color: theme.danger.text,
  };

  return (
    <div
      ref={panelRef}
      style={{
        position: 'absolute',
        left: pos.x,
        top: pos.y,
        zIndex: 1000,
        width: 420,
        maxHeight: 520,
        background: theme.bg.surface,
        border: `1px solid ${theme.border.default}`,
        borderRadius: theme.radius.lg,
        boxShadow: '0 12px 40px rgba(0,0,0,0.55)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* 标题栏（可拖拽） */}
      <div
        style={{
          padding: '10px 14px',
          background: theme.bg.header,
          borderBottom: `1px solid ${theme.border.subtle}`,
          cursor: 'move',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          userSelect: 'none',
        }}
        onMouseDown={(e) => {
          if ((e.target as HTMLElement).tagName === 'BUTTON') return;
          const el = panelRef.current;
          if (!el) return;
          dragRef.current = { dx: e.clientX - el.offsetLeft, dy: e.clientY - el.offsetTop };
          const onMove = (ev: MouseEvent) => {
            if (!dragRef.current) return;
            setPos({ x: ev.clientX - dragRef.current.dx, y: ev.clientY - dragRef.current.dy });
          };
          const onUp = () => {
            dragRef.current = null;
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
          };
          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 600, color: theme.text.primary }}>工作流库</span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none',
            color: theme.text.muted, cursor: 'pointer',
            fontSize: 18, lineHeight: 1, padding: 0,
          }}
        >
          ✕
        </button>
      </div>

      {/* 操作栏 */}
      <div style={{ padding: '10px 14px', borderBottom: `1px solid ${theme.border.subtle}`, display: 'flex', gap: 8 }}>
        <button style={accentBtn} onClick={() => setGptOpen(true)}>
          GPT 创建
        </button>
        <button style={accentBtn} onClick={() => setSaveOpen(true)}>
          保存工作流
        </button>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: theme.text.hint, alignSelf: 'center' }}>
          {items.length} 个
        </span>
      </div>

      {/* GPT 面板 */}
      {gptOpen && (
        <div style={{ padding: '10px 14px', borderBottom: `1px solid ${theme.border.subtle}` }}>
          <textarea
            placeholder="用自然语言描述你想要的工作流，AI 将为你生成……&#10;例：文生图 2560×1440 宽屏，写实电影质感，20步 Eula 采样器"
            value={gptDesc}
            onChange={(e) => setGptDesc(e.target.value)}
            rows={3}
            style={{
              width: '100%',
              background: theme.bg.input,
              color: theme.text.primary,
              border: `1px solid ${theme.border.subtle}`,
              borderRadius: 6,
              padding: 8,
              fontSize: 12,
              resize: 'vertical',
              boxSizing: 'border-box',
            }}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
            <button
              disabled={gptBusy || !gptDesc.trim()}
              onClick={handleGpt}
              style={{
                ...accentBtn,
                opacity: gptBusy ? 0.5 : 1,
              }}
            >
              {gptBusy ? '生成中…' : '生成工作流'}
            </button>
            <button style={commonBtn} onClick={() => setGptOpen(false)}>取消</button>
            {gptResult && (
              <button
                style={commonBtn}
                onClick={async () => {
                  const n = prompt('保存名称', gptResult.name)?.trim();
                  if (!n) return;
                  try {
                    await saveWorkflow(n, gptResult.description, gptResult.workflow_json);
                    alert(`已保存「${n}」`);
                    setGptOpen(false);
                    refresh();
                  } catch (e) { alert('保存失败: ' + ((e as Error)?.message || String(e))); }
                }}
              >
                保存此工作流
              </button>
            )}
          </div>
        </div>
      )}

      {/* 保存表单 */}
      {saveOpen && (
        <div style={{ padding: '10px 14px', borderBottom: `1px solid ${theme.border.subtle}` }}>
          <input
            placeholder="工作流名称"
            value={wfName}
            onChange={(e) => setWfName(e.target.value)}
            style={{
              width: '100%', boxSizing: 'border-box',
              background: theme.bg.input, color: theme.text.primary,
              border: `1px solid ${theme.border.subtle}`, borderRadius: 6,
              padding: '6px 10px', fontSize: 12, marginBottom: 6,
            }}
          />
          <input
            placeholder="描述（可选）"
            value={wfDesc}
            onChange={(e) => setWfDesc(e.target.value)}
            style={{
              width: '100%', boxSizing: 'border-box',
              background: theme.bg.input, color: theme.text.primary,
              border: `1px solid ${theme.border.subtle}`, borderRadius: 6,
              padding: '6px 10px', fontSize: 12, marginBottom: 6,
            }}
          />
          <textarea
            placeholder='粘贴 ComfyUI workflow JSON…'
            value={wfJson}
            onChange={(e) => setWfJson(e.target.value)}
            rows={6}
            style={{
              width: '100%', boxSizing: 'border-box',
              background: theme.bg.input, color: theme.text.primary,
              border: `1px solid ${theme.border.subtle}`, borderRadius: 6,
              padding: 8, fontSize: 11, resize: 'vertical',
              fontFamily: 'monospace',
            }}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button style={accentBtn} onClick={handleSave}>保存</button>
            <button style={commonBtn} onClick={() => setSaveOpen(false)}>取消</button>
          </div>
        </div>
      )}

      {/* 工作流列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 14px' }}>
        {items.length === 0 && (
          <div style={{ textAlign: 'center', color: theme.text.hint, fontSize: 12, padding: '24px 0' }}>
            暂无已保存的自定义工作流。<br />
            使用「GPT 创建」或「保存工作流」添加。
          </div>
        )}
        {items.map((it) => (
          <div
            key={it.name}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 0',
              borderBottom: `1px solid ${theme.border.subtle}2e`,
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, color: theme.text.primary, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {it.name}
              </div>
              <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 2 }}>
                {it.description ? it.description.slice(0, 60) : '无描述'} · {it.node_count} 节点 · {new Date(it.saved_at * 1000).toLocaleString('zh-CN')}
              </div>
            </div>
            <button style={commonBtn} onClick={() => handleLoad(it.name)}>加载</button>
            <button style={dangerBtn} onClick={() => handleDelete(it.name)}>删除</button>
          </div>
        ))}
      </div>
    </div>
  );
}
