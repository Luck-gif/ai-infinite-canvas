// v4.50 分镜规划面板：场景描述→多分镜拆解→逐镜工作流组装
// 浮动面板，支持拖拽
import { useCallback, useRef, useState } from 'react';
import { planStoryboard, listBlueprints } from './api';
import type { StoryboardPlanResponse, StoryboardShotResult, BlueprintItem } from './types';
import { theme } from './theme';
import { useCanvasStore } from './store';
import { toastChannel } from './App';

interface Props {
  onClose: () => void;
}

export function StoryboardPanel({ onClose }: Props) {
  // v4.52: 分镜→画布集成
  const loadStoryboardToCanvas = useCanvasStore((s) => s.loadStoryboardToCanvas);

  // 表单
  const [description, setDescription] = useState('');
  const [numShots, setNumShots] = useState(4);
  const [style, setStyle] = useState('');
  const [characters, setCharacters] = useState('');
  const [blueprint, setBlueprint] = useState('auto');
  const [videoBlueprint, setVideoBlueprint] = useState('');
  const [imageBlueprints, setImageBlueprints] = useState<BlueprintItem[]>([]);
  const [videoBlueprints, setVideoBlueprints] = useState<BlueprintItem[]>([]);

  // 状态
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<StoryboardPlanResponse | null>(null);
  const [expandedShot, setExpandedShot] = useState<string | null>(null);

  // 蓝图加载
  const [bpLoaded, setBpLoaded] = useState(false);

  // 拖拽
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 140, y: 70 });
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

  const loadBps = useCallback(() => {
    if (bpLoaded) return;
    listBlueprints().then((bp) => {
      setImageBlueprints(bp.image || []);
      setVideoBlueprints(bp.video || []);
      setBpLoaded(true);
    }).catch(() => {});
  }, [bpLoaded]);

  const handlePlan = async () => {
    const desc = description.trim();
    if (!desc) return;
    loadBps();
    setBusy(true);
    setResult(null);
    try {
      const chars = characters.trim()
        ? characters.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
        : undefined;
      const res = await planStoryboard({
        description: desc,
        num_shots: numShots || undefined,
        style: style.trim() || undefined,
        characters: chars,
        blueprint: blueprint !== 'auto' ? blueprint : undefined,
        video_blueprint: videoBlueprint || null,
      });
      setResult(res);
      toastChannel.push('success', `分镜规划完成: ${res.total_shots} 个分镜`);
    } catch (e) {
      toastChannel.push('error', '分镜规划失败: ' + ((e as Error)?.message || String(e)));
    } finally {
      setBusy(false);
    }
  };

  const handleViewShot = (shot: StoryboardShotResult) => {
    // 将单个分镜的 workflow_json 转换为可视图
    toastChannel.push('info', `查看分镜 ${shot.shot_index + 1}: ${shot.prompt.slice(0, 40)}…`);
  };

  // 预设模板
  const presets = [
    { label: '短篇故事', desc: '一个年轻冒险家在古老森林中发现神秘遗迹的短篇故事', shots: 4 },
    { label: '产品展示', desc: '一款未来科技产品的多角度展示和功能介绍', shots: 3 },
    { label: '旅行Vlog', desc: '日落时分的城市漫步，从街景到天际线', shots: 5 },
  ];

  const commonBtn: React.CSSProperties = {
    padding: '5px 12px', borderRadius: 6,
    border: `1px solid ${theme.border.subtle}`,
    background: theme.bg.card, color: theme.text.secondary,
    fontSize: 12, cursor: 'pointer',
  };
  const accentBtn: React.CSSProperties = {
    ...commonBtn, background: '#1a2744', borderColor: '#4f8cff', color: theme.accent.blue,
  };
  const inputStyle: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box',
    background: theme.bg.input, color: theme.text.primary,
    border: `1px solid ${theme.border.subtle}`, borderRadius: 6,
    padding: '6px 10px', fontSize: 12,
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11, color: theme.text.label, marginBottom: 3, display: 'block',
  };

  return (
    <div
      ref={panelRef}
      style={{
        position: 'absolute', left: pos.x, top: pos.y, zIndex: 1001,
        width: 520, maxHeight: 640,
        background: theme.bg.surface,
        border: `1px solid ${theme.border.default}`,
        borderRadius: theme.radius.lg,
        boxShadow: '0 12px 40px rgba(0,0,0,0.55)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}
    >
      {/* 标题栏 */}
      <div
        style={{
          padding: '10px 14px', background: theme.bg.header,
          borderBottom: `1px solid ${theme.border.subtle}`,
          cursor: 'move', display: 'flex',
          justifyContent: 'space-between', alignItems: 'center', userSelect: 'none',
        }}
        onMouseDown={(e) => {
          if ((e.target as HTMLElement).tagName === 'BUTTON') return;
          const el = panelRef.current; if (!el) return;
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
          分镜规划 <span style={{ fontSize: 11, color: theme.accent.amber, fontWeight: 400 }}>v4.50</span>
        </span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: theme.text.muted, cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 0 }}>✕</button>
      </div>

      {/* 内容区 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {/* 预设 */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {presets.map((p) => (
            <button
              key={p.label}
              onClick={() => { setDescription(p.desc); setNumShots(p.shots); }}
              style={{ ...commonBtn, padding: '3px 10px', fontSize: 11 }}>
              {p.label} ({p.shots}镜)
            </button>
          ))}
        </div>

        {/* 场景描述 */}
        <div>
          <label style={labelStyle}>场景描述</label>
          <textarea
            placeholder="描述你想要的故事场景…&#10;例如：一只小猫在屋顶冒险，途中遇到小鸟、躲避屋檐、最后在月亮下休息"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5 }}
          />
        </div>

        {/* 参数行 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
          <div>
            <label style={labelStyle}>分镜数</label>
            <input type="number" min={1} max={12} value={numShots}
              onChange={(e) => setNumShots(Number(e.target.value))}
              style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>风格</label>
            <input placeholder="电影级/动漫/写实…" value={style}
              onChange={(e) => setStyle(e.target.value)}
              style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>角色（逗号分隔）</label>
            <input placeholder="少女, 白猫…" value={characters}
              onChange={(e) => setCharacters(e.target.value)}
              style={inputStyle} />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div>
            <label style={labelStyle}>图像蓝图</label>
            <select value={blueprint} onChange={(e) => setBlueprint(e.target.value)}
              onFocus={loadBps}
              style={{ ...inputStyle, cursor: 'pointer' }}>
              <option value="auto">自动选择</option>
              {imageBlueprints.map((bp) => (
                <option key={bp.id} value={bp.id}>{bp.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={labelStyle}>视频蓝图（可选）</label>
            <select value={videoBlueprint} onChange={(e) => setVideoBlueprint(e.target.value)}
              onFocus={loadBps}
              style={{ ...inputStyle, cursor: 'pointer' }}>
              <option value="">不生成视频</option>
              {videoBlueprints.map((bp) => (
                <option key={bp.id} value={bp.id}>{bp.name}</option>
              ))}
            </select>
          </div>
        </div>

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            disabled={busy || !description.trim()}
            onClick={handlePlan}
            style={{
              ...accentBtn, fontSize: 13, padding: '7px 18px',
              opacity: busy || !description.trim() ? 0.5 : 1, fontWeight: 600,
            }}>
            {busy ? '规划中…' : '生成分镜规划'}
          </button>
          {result && (
            <span style={{ fontSize: 12, color: theme.text.label }}>
              {result.total_shots} 个分镜 · {result.consistency_profile ? '已应用一致性策略' : '标准模式'}
            </span>
          )}
        </div>

        {/* 分镜结果列表 */}
        {result && result.shots.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: `1px solid ${theme.border.subtle}`, paddingTop: 10 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: theme.text.primary }}>
                分镜列表 (storyboard_id: {result.storyboard_id})
              </span>
              <button
                onClick={() => {
                  loadStoryboardToCanvas(result.shots);
                  toastChannel.push('success', `${result.shots.length} 个分镜已加载到画布（策划层）`);
                }}
                style={{
                  ...commonBtn,
                  background: '#2a1f10',
                  borderColor: '#f0a030',
                  color: '#f0a030',
                  fontSize: 11,
                  padding: '3px 10px',
                }}
                title="将分镜序列加载到策划层画布，自动布局并连线"
              >📋 加载到画布</button>
            </div>
            {result.shots.map((shot) => (
              <div
                key={shot.shot_id}
                style={{
                  background: theme.bg.card,
                  borderRadius: 8,
                  border: `1px solid ${expandedShot === shot.shot_id ? theme.border.accent : theme.border.subtle}`,
                  overflow: 'hidden',
                }}
              >
                {/* 分镜头部 */}
                <div
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    padding: '8px 10px', cursor: 'pointer',
                  }}
                  onClick={() => setExpandedShot(expandedShot === shot.shot_id ? null : shot.shot_id)}
                >
                  <span style={{
                    width: 24, height: 24, borderRadius: '50%',
                    background: theme.accent.amber,
                    color: '#000', fontSize: 11, fontWeight: 700,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    {shot.shot_index + 1}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: theme.text.primary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {shot.prompt}
                    </div>
                    <div style={{ fontSize: 11, color: theme.text.hint }}>
                      {shot.node_count} 节点
                    </div>
                  </div>
                  <button
                    style={commonBtn}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleViewShot(shot);
                    }}
                  >查看</button>
                </div>

                {/* 展开详情 */}
                {expandedShot === shot.shot_id && (
                  <div style={{ padding: '8px 10px', borderTop: `1px solid ${theme.border.subtle}`, background: theme.bg.input }}>
                    <div style={{ fontSize: 11, color: theme.text.label, marginBottom: 4 }}>
                      完整提示词: {shot.prompt}
                    </div>
                    <pre
                      style={{
                        padding: 8, background: theme.bg.root, borderRadius: 6,
                        color: theme.text.slate, fontSize: 10,
                        maxHeight: 150, overflow: 'auto',
                        fontFamily: '"JetBrains Mono","Fira Code",monospace',
                        lineHeight: 1.4,
                      }}
                    >
                      {JSON.stringify(shot.workflow_json, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {result && result.shots.length === 0 && (
          <div style={{ textAlign: 'center', color: theme.text.hint, fontSize: 12, padding: 16 }}>
            未生成分镜（可能后端处理出错）
          </div>
        )}
      </div>
    </div>
  );
}
