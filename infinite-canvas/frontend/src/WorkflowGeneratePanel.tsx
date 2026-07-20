// v4.50 工作流生成面板：自然语言→蓝图匹配→组装→校验→ComfyUI JSON
// 浮动面板，支持拖拽，可提交到 ComfyUI 或查看工作流图
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  generateWorkflow,
  listBlueprints,
  generate,
} from './api';
import type {
  WorkflowGenerateResponse,
  BlueprintItem,
  WorkflowGraph,
} from './types';
import { theme } from './theme';
import { useCanvasStore } from './store';
import { toastChannel } from './App';

interface Props {
  onClose: () => void;
}

export function WorkflowGeneratePanel({ onClose }: Props) {
  const setWfOpen = useCanvasStore((s) => s.setWfOpen);
  const setLiveWorkflow = useCanvasStore((s) => s.setLiveWorkflow);

  // 蓝图缓存
  const [imageBlueprints, setImageBlueprints] = useState<BlueprintItem[]>([]);
  const [videoBlueprints, setVideoBlueprints] = useState<BlueprintItem[]>([]);

  // 表单
  const [prompt, setPrompt] = useState('');
  const [imageBp, setImageBp] = useState('auto');
  const [videoBp, setVideoBp] = useState('');
  const [consistencyMode, setConsistencyMode] = useState('auto');
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [steps, setSteps] = useState(20);
  const [cfg, setCfg] = useState(7.0);
  const [seed, setSeed] = useState(0);
  const [negative, setNegative] = useState('');
  const [batchSize, setBatchSize] = useState(1);
  const [doSubmit, setDoSubmit] = useState(false);

  // 状态
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WorkflowGenerateResponse | null>(null);
  const [showJson, setShowJson] = useState(false);

  // 拖拽
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 120, y: 60 });
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

  // 加载蓝图
  useEffect(() => {
    listBlueprints()
      .then((bp) => {
        setImageBlueprints(bp.image || []);
        setVideoBlueprints(bp.video || []);
      })
      .catch(() => {});
  }, []);

  const handleGenerate = async () => {
    const p = prompt.trim();
    if (!p) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await generateWorkflow({
        prompt: p,
        image_blueprint: imageBp !== 'auto' ? imageBp : undefined,
        video_blueprint: videoBp || null,
        consistency_mode: consistencyMode !== 'auto' ? consistencyMode : undefined,
        width: width || undefined,
        height: height || undefined,
        steps: steps || undefined,
        cfg: cfg || undefined,
        negative: negative.trim() || undefined,
        submit: doSubmit,
      });
      setResult(res);

      // 如果有工作流图，自动显示
      if (res.workflow_graph) {
        setLiveWorkflow(res.workflow_graph);
        setWfOpen(true);
      }

      const msgParts: string[] = [`${res.node_count} 节点`];
      if (res.consistency_mode && res.consistency_mode !== 'none') {
        msgParts.push(`一致性: ${res.consistency_mode}`);
      }
      if (res.submitted) msgParts.push('已提交');
      else if (res.submit_error) msgParts.push(`提交失败: ${res.submit_error}`);
      toastChannel.push(res.validated ? 'success' : 'info', `生成完成: ${msgParts.join(', ')}`);
    } catch (e) {
      toastChannel.push('error', '生成失败: ' + ((e as Error)?.message || String(e)));
    } finally {
      setBusy(false);
    }
  };

  const handleSubmitToComfyUI = async () => {
    if (!result?.workflow_json) return;
    setBusy(true);
    try {
      // 复用现有 generate 通道提交已组装的工作流
      const genRes = await generate({
        prompt: result.prompt_engineered || prompt,
        negative: negative.trim() || undefined,
        width,
        height,
        steps,
        cfg,
        seed: seed || undefined,
        batch_size: batchSize,
        wait: true,
      });
      if (genRes.images?.length) {
        toastChannel.push('success', `已提交到 ComfyUI，生成 ${genRes.images.length} 张图`);
      }
      if (genRes.workflow) {
        setLiveWorkflow(genRes.workflow);
        setWfOpen(true);
      }
    } catch (e) {
      toastChannel.push('error', '提交失败: ' + ((e as Error)?.message || String(e)));
    } finally {
      setBusy(false);
    }
  };

  // 快捷预设
  const presets = [
    { label: '写实肖像', prompt: '一张写实电影质感的肖像照片，柔和自然光，浅景深' },
    { label: '风景大片', prompt: '壮丽的自然风景，电影级构图，史诗光线，超广角' },
    { label: '科幻场景', prompt: '赛博朋克城市夜景，霓虹灯，雨雾，电影质感，虚化背景' },
    { label: '动漫角色', prompt: '动漫风格角色，精致线条，柔和色彩' },
    { label: '产品摄影', prompt: '高端产品摄影，工作室灯光，干净背景，商业海报风格' },
  ];

  // ── 通用样式 ──
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
  const inputStyle: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box',
    background: theme.bg.input, color: theme.text.primary,
    border: `1px solid ${theme.border.subtle}`, borderRadius: 6,
    padding: '6px 10px', fontSize: 12,
  };
  const selectStyle: React.CSSProperties = {
    ...inputStyle,
    cursor: 'pointer',
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11, color: theme.text.label, marginBottom: 3, display: 'block',
  };

  return (
    <div
      ref={panelRef}
      style={{
        position: 'absolute',
        left: pos.x,
        top: pos.y,
        zIndex: 1001,
        width: 500,
        maxHeight: 620,
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
        <span style={{ fontSize: 14, fontWeight: 600, color: theme.text.primary }}>
          工作流生成 <span style={{ fontSize: 11, color: theme.accent.blue, fontWeight: 400 }}>v4.50</span>
        </span>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: theme.text.muted, cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 0 }}
        >✕</button>
      </div>

      {/* 表单区 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {/* 快捷预设 */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {presets.map((p) => (
            <button
              key={p.label}
              onClick={() => setPrompt(p.prompt)}
              style={{
                ...commonBtn,
                padding: '3px 10px',
                fontSize: 11,
                background: prompt === p.prompt ? '#1a2744' : theme.bg.card,
                borderColor: prompt === p.prompt ? '#4f8cff' : theme.border.subtle,
              }}
            >{p.label}</button>
          ))}
        </div>

        {/* 主输入 */}
        <div>
          <label style={labelStyle}>描述 (NL Prompt)</label>
          <textarea
            placeholder="用自然语言描述你想要的画面或视频…&#10;例如：一个少女在樱花树下，梦幻光影，4K画质，动漫风格"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            style={{
              ...inputStyle,
              resize: 'vertical',
              fontFamily: 'inherit',
              lineHeight: 1.5,
            }}
          />
        </div>

        {/* 蓝图选择区 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div>
            <label style={labelStyle}>图像蓝图</label>
            <select value={imageBp} onChange={(e) => setImageBp(e.target.value)} style={selectStyle}>
              <option value="auto">自动选择</option>
              {imageBlueprints.map((bp) => (
                <option key={bp.id} value={bp.id}>{bp.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={labelStyle}>视频蓝图（可选）</label>
            <select value={videoBp} onChange={(e) => setVideoBp(e.target.value)} style={selectStyle}>
              <option value="">不生成视频</option>
              {videoBlueprints.map((bp) => (
                <option key={bp.id} value={bp.id}>{bp.name}</option>
              ))}
            </select>
          </div>
        </div>

        {/* 一致性 + 参数 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
          <div>
            <label style={labelStyle}>宽</label>
            <input type="number" value={width} onChange={(e) => setWidth(Number(e.target.value))} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>高</label>
            <input type="number" value={height} onChange={(e) => setHeight(Number(e.target.value))} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>步数</label>
            <input type="number" value={steps} onChange={(e) => setSteps(Number(e.target.value))} style={inputStyle} />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
          <div>
            <label style={labelStyle}>CFG</label>
            <input type="number" step="0.5" value={cfg} onChange={(e) => setCfg(Number(e.target.value))} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>种子 (0=随机)</label>
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>批量</label>
            <input type="number" min={1} max={4} value={batchSize} onChange={(e) => setBatchSize(Number(e.target.value))} style={inputStyle} />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div>
            <label style={labelStyle}>一致性策略</label>
            <select value={consistencyMode} onChange={(e) => setConsistencyMode(e.target.value)} style={selectStyle}>
              <option value="auto">auto</option>
              <option value="face_consistency">face_consistency</option>
              <option value="style_consistency">style_consistency</option>
              <option value="scene_consistency">scene_consistency</option>
              <option value="prop_consistency">prop_consistency</option>
              <option value="none">none</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>负向提示词</label>
            <input
              placeholder="ugly, blurry, bad quality…"
              value={negative}
              onChange={(e) => setNegative(e.target.value)}
              style={inputStyle}
            />
          </div>
        </div>

        {/* 操作栏 */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            disabled={busy || !prompt.trim()}
            onClick={handleGenerate}
            style={{
              ...accentBtn,
              fontSize: 13,
              padding: '7px 18px',
              opacity: busy || !prompt.trim() ? 0.5 : 1,
              fontWeight: 600,
            }}
          >
            {busy ? '组装中…' : '生成工作流'}
          </button>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: theme.text.label, cursor: 'pointer', userSelect: 'none' }}>
            <input
              type="checkbox"
              checked={doSubmit}
              onChange={(e) => setDoSubmit(e.target.checked)}
              style={{ accentColor: theme.accent.blue }}
            />
            同时提交到 ComfyUI
          </label>
          <span style={{ flex: 1 }} />
          {result && (
            <button style={commonBtn} onClick={() => setShowJson(!showJson)}>
              {showJson ? '隐藏 JSON' : '查看 JSON'}
            </button>
          )}
        </div>

        {/* 结果信息 */}
        {result && (
          <div
            style={{
              background: theme.bg.card,
              borderRadius: 8,
              border: `1px solid ${result.validated ? theme.border.success : theme.border.warning}`,
              padding: '10px 12px',
              fontSize: 12,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ color: theme.text.primary, fontWeight: 600 }}>
                {result.validated ? '✓ 校验通过' : '⚠ 有警告'}
              </span>
              <span style={{ color: theme.text.hint }}>
                {result.node_count} 节点 · {result.shot_id}
              </span>
            </div>
            <div style={{ color: theme.text.label, marginBottom: 4 }}>
              组装提示词: {result.prompt_engineered?.slice(0, 120)}{(result.prompt_engineered?.length || 0) > 120 ? '…' : ''}
            </div>
            {result.consistency_mode && result.consistency_mode !== 'none' && (
              <div style={{ color: theme.accent.amber }}>
                一致性: {result.consistency_mode}{result.entities_used?.length ? ` · 实体: ${result.entities_used.join(', ')}` : ''}
              </div>
            )}
            {result.submitted && (
              <div style={{ color: theme.accent.green, marginTop: 4 }}>✓ 已提交到 ComfyUI</div>
            )}
            {result.submit_error && (
              <div style={{ color: theme.danger.text, marginTop: 4 }}>✗ {result.submit_error}</div>
            )}
            {result.issues?.length > 0 && (
              <div style={{ marginTop: 6 }}>
                {result.issues.map((issue, i) => (
                  <div key={i} style={{ color: theme.accent.amber, fontSize: 11 }}>• {issue}</div>
                ))}
              </div>
            )}

            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              {result.workflow_graph && (
                <button
                  style={accentBtn}
                  onClick={() => {
                    setLiveWorkflow(result.workflow_graph);
                    setWfOpen(true);
                  }}
                >查看工作流图</button>
              )}
              {!result.submitted && result.workflow_json && (
                <button style={commonBtn} onClick={handleSubmitToComfyUI} disabled={busy}>
                  {busy ? '提交中…' : '提交到 ComfyUI'}
                </button>
              )}
            </div>

            {/* JSON 展示 */}
            {showJson && result.workflow_json && (
              <pre
                style={{
                  marginTop: 8,
                  padding: 10,
                  background: theme.bg.input,
                  borderRadius: 6,
                  color: theme.text.soft,
                  fontSize: 10,
                  maxHeight: 200,
                  overflow: 'auto',
                  fontFamily: '"JetBrains Mono", "Fira Code", monospace',
                  lineHeight: 1.4,
                }}
              >
                {JSON.stringify(result.workflow_json, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
