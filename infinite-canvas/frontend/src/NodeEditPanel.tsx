// v4.54 NodeEditPanel — 画布节点属性编辑面板（右侧滑入）
// 点击画布节点 → 弹出浮动面板 → 编辑参数 → 重新生成 → 更新节点
import { useState, useEffect } from 'react';
import { useCanvasStore } from './store';
import { generate, previewWorkflow, runPipeline, type PipelineRunResponse } from './api';
import { toastChannel } from './App';
import type { WorkflowGraph } from './types';
import { theme } from './theme';

const PANEL_W = 340;

// ── 通用样式 ──────────────────────────────────────────────────────
const S = {
  panel: {
    position: 'absolute',
    right: 0, top: 44, bottom: 0,
    width: PANEL_W,
    background: theme.bg.surface,
    borderLeft: `1px solid ${theme.border.card}`,
    zIndex: 100,
    overflowY: 'auto',
    padding: 14,
    display: 'flex', flexDirection: 'column', gap: 10,
    boxShadow: '-4px 0 20px rgba(0,0,0,0.3)',
    fontFamily: 'ui-sans-serif, system-ui, sans-serif',
  } as React.CSSProperties,
  h2: { fontSize: 13, fontWeight: 700, color: theme.text.primary, margin: 0 } as React.CSSProperties,
  label: { fontSize: 11, fontWeight: 600, color: theme.text.soft, textTransform: 'uppercase', letterSpacing: 0.5 } as React.CSSProperties,
  field: {
    width: '100%',
    padding: '6px 8px',
    borderRadius: 5,
    border: `1px solid ${theme.border.card}`,
    background: theme.bg.card,
    color: theme.text.primary,
    fontSize: 12,
    outline: 'none',
    resize: 'vertical' as const,
    boxSizing: 'border-box' as const,
  },
  btn: {
    padding: '7px 14px',
    borderRadius: 6,
    border: 'none',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'opacity 0.15s',
  },
};

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <span style={S.label}>{label}</span>
      {children}
    </div>
  );
}

function SliderField({ label, value, min, max, step, onChange }: {
  label: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 11, color: theme.text.hint }}>{label}</span>
        <span style={{ fontSize: 11, fontWeight: 600, color: theme.accent.blue }}>{value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: theme.accent.blue }} />
    </div>
  );
}

// ── 主组件 ────────────────────────────────────────────────────────

export function NodeEditPanel() {
  const nodes = useCanvasStore((s) => s.nodes);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const updateNode = useCanvasStore((s) => s.updateNode);
  const removeNode = useCanvasStore((s) => s.removeNode);
  const clearSelection = useCanvasStore((s) => s.clearSelection);
  const setWfOpen = useCanvasStore((s) => s.setWfOpen);
  const setLiveWorkflow = useCanvasStore((s) => s.setLiveWorkflow);
  const markNodeQuality = useCanvasStore((s) => s.markNodeQuality);  // v5.3

  const node = nodes.find((n) => n.id === selectedId);
  const [prompt, setPrompt] = useState('');
  const [negative, setNegative] = useState('');
  const [seed, setSeed] = useState(-1);
  const [steps, setSteps_] = useState(20);
  const [cfg, setCfg_] = useState(7);
  const [w, setW] = useState(1024);
  const [h, setH] = useState(1024);
  const [busy, setBusy] = useState(false);
  const [previewJson, setPreviewJson] = useState<string | null>(null);

  useEffect(() => {
    if (node) {
      setPrompt(node.prompt || '');
      setNegative(node.negative || '');
      setSeed(node.seed ?? -1);
      setSteps_(node.steps ?? 20);
      setCfg_(node.cfg ?? 7);
      setW(node.width || 1024);
      setH(node.height || 1024);
    }
    setPreviewJson(null);
  }, [selectedId, node?.id]);

  if (!node) return null;

  const onRegenerate = async () => {
    setBusy(true);
    try {
      const resp = await generate({
        prompt,
        negative: negative || undefined,
        width: w,
        height: h,
        steps,
        cfg,
        seed: seed >= 0 ? seed : undefined,
      });
      const url = resp.images?.[0] || '';
      updateNode(node.id, {
        prompt,
        negative,
        seed: seed >= 0 ? seed : undefined,
        width: w, height: h,
        steps, cfg,
        filename: url,
        createdAt: Date.now(),
      });
      toastChannel.push('success', '节点已重新生成');
    } catch (e: unknown) {
      toastChannel.push('error', `生成失败: ${(e as Error)?.message || String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const onPipelineRegenerate = async () => {
    setBusy(true);
    try {
      const resp: PipelineRunResponse = await runPipeline({
        prompt,
        negative: negative || undefined,
        width: w, height: h,
        steps, cfg,
        submit: true,
      });
      if (resp.submitted) {
        toastChannel.push('success', `管线提交成功 (${resp.blueprint})`);
      } else {
        toastChannel.push('info', `验证通过但未提交: ${resp.issues.join('; ') || '无问题'}`);
      }
    } catch (e: unknown) {
      toastChannel.push('error', `管线执行失败: ${(e as Error)?.message || String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const onPreview = async () => {
    try {
      const resp = await previewWorkflow({
        prompt,
        negative: negative || undefined,
        width: w, height: h,
        steps, cfg,
      });
      setPreviewJson(JSON.stringify(resp.workflow, null, 2));
      setLiveWorkflow(resp.workflow as unknown as WorkflowGraph);
      setWfOpen(true);
    } catch (e: unknown) {
      toastChannel.push('error', `预览失败: ${(e as Error)?.message || String(e)}`);
    }
  };

  const onDelete = () => {
    removeNode(node.id);
    toastChannel.push('info', '节点已删除');
  };

  const onFullscreen = () => {
    if (node.filename) {
      window.open(`/api/output/${node.filename}`, '_blank');
    }
  };

  return (
    <div style={S.panel}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={S.h2}>🎯 节点属性</h2>
        <button onClick={clearSelection}
          style={{ ...S.btn, background: 'transparent', color: theme.text.hint, fontSize: 18, padding: '0 4px', lineHeight: 1 }}>
          ✕
        </button>
      </div>

      <div style={{ fontSize: 11, color: theme.text.hint }}>
        ID: <code style={{ color: theme.accent.blue }}>{node.id}</code>
        {node.mode ? ` · ${node.mode}` : ''}
        {node.kind ? ` · ${node.kind}` : ''}
        {node.filename ? ` · 已生成` : ' · 未生成'}
      </div>

      {/* 提示词 */}
      <Section label="正向提示词">
        <textarea rows={3} style={S.field} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </Section>

      <Section label="负向提示词">
        <input style={S.field} value={negative} onChange={(e) => setNegative(e.target.value)} placeholder="(可选)" />
      </Section>

      {/* 尺寸 */}
      <div style={{ display: 'flex', gap: 8 }}>
        <div style={{ flex: 1 }}>
          <Section label="宽度">
            <input type="number" style={S.field} value={w} onChange={(e) => setW(Number(e.target.value))} />
          </Section>
        </div>
        <div style={{ flex: 1 }}>
          <Section label="高度">
            <input type="number" style={S.field} value={h} onChange={(e) => setH(Number(e.target.value))} />
          </Section>
        </div>
      </div>

      {/* 种子 */}
      <Section label="种子 (Seed)">
        <input type="number" style={S.field} value={seed} onChange={(e) => setSeed(Number(e.target.value))}
          placeholder="-1 = 随机" />
      </Section>

      {/* 步数 & CFG */}
      <SliderField label="采样步数" value={steps} min={4} max={50} step={1} onChange={setSteps_} />
      <SliderField label="CFG Scale" value={cfg} min={1} max={20} step={0.5} onChange={setCfg_} />

      {/* 操作按钮 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
        <button disabled={busy} onClick={onRegenerate}
          style={{ ...S.btn, background: theme.accent.blue, color: '#fff', opacity: busy ? 0.5 : 1 }}>
          {busy ? '生成中…' : '♻ 重新生成 (直接ComfyUI)'}
        </button>

        <button disabled={busy} onClick={onPipelineRegenerate}
          style={{ ...S.btn, background: '#2a1f10', border: '1px solid #f0a030', color: '#f0a030', opacity: busy ? 0.5 : 1 }}>
          {busy ? '提交中…' : '⚡ 管线重新生成 (PipelineOrchestrator)'}
        </button>

        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={onPreview}
            style={{ ...S.btn, flex: 1, background: theme.bg.card, border: `1px solid ${theme.border.card}`, color: theme.text.soft }}>
            🔍 预览工作流
          </button>
          <button onClick={onFullscreen}
            disabled={!node.filename}
            style={{ ...S.btn, flex: 1, background: theme.bg.card, border: `1px solid ${theme.border.card}`, color: theme.text.soft, opacity: node.filename ? 1 : 0.4 }}>
            🖼 查看全图
          </button>
          <button onClick={onDelete}
            style={{ ...S.btn, flex: 1, background: '#2a1010', border: '1px solid #cc3333', color: '#ff6666' }}>
            🗑 删除
          </button>
        </div>
      </div>

      {/* 工作流预览 */}
      {previewJson && (
        <details>
          <summary style={{ fontSize: 11, color: theme.accent.blue, cursor: 'pointer' }}>工作流 JSON (已加载到面板)</summary>
          <pre style={{ fontSize: 10, color: theme.text.soft, background: theme.bg.card, padding: 8, borderRadius: 4, maxHeight: 200, overflow: 'auto' }}>
            {previewJson.slice(0, 2000)}
          </pre>
        </details>
      )}

      {/* v5.3 审核标记 */}
      <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
        <span style={{ fontSize: 11, color: theme.text.hint, lineHeight: '24px' }}>审核:</span>
        {[
          { s: 'approved', l: '✅ 通过' },
          { s: 'rejected', l: '❌ 驳回' },
          { s: 'needs_regeneration', l: '🔄 重生成' },
        ].map(({ s, l }) => (
          <button key={s} onClick={() => { if (node) markNodeQuality(node.id, s); }}
            style={{
              flex: 1, padding: '3px 0', borderRadius: 4, border: 'none',
              cursor: 'pointer', fontSize: 11,
              background: node?.qualityStatus === s ? 'rgba(56,189,248,0.2)' : 'rgba(255,255,255,0.05)',
              color: node?.qualityStatus === s ? theme.accent.blue : theme.text.hint,
            }}>{l}</button>
        ))}
        <span style={{ fontSize: 10, color: theme.text.tiny, lineHeight: '24px', minWidth: 50 }}>
          {node?.qualityStatus ? `[${node.qualityStatus}]` : '[未标记]'}
        </span>
      </div>

      {/* 底部提示 */}
      <div style={{ fontSize: 10, color: theme.text.tiny, marginTop: 4 }}>
        修改参数后点击「重新生成」即可原地更新节点。
        点击「预览工作流」可查看 ComfyUI 工作流图。
      </div>
    </div>
  );
}
