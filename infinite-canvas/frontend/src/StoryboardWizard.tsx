// v5.6 故事板引导式工作流 — 4步向导
// 剧本 → 角色/场景 → 分镜 → 批量生成
import { useCallback, useRef, useState } from 'react';
import { extractNarrative, planStoryboard } from './api';
import type { NarrateResponse, NarrateCharacter, NarrateScene, NarrateShot, WizardStep } from './types';
import { theme } from './theme';
import { useCanvasStore } from './store';
import { toastChannel } from './App';

interface Props {
  onClose: () => void;
}

const STEPS: { id: WizardStep; label: string; icon: string }[] = [
  { id: 'script', label: '输入剧本', icon: '📝' },
  { id: 'characters', label: '角色场景', icon: '🎭' },
  { id: 'shots', label: '分镜预览', icon: '🎬' },
  { id: 'generate', label: '开始生成', icon: '✨' },
];

export function StoryboardWizard({ onClose }: Props) {
  // ── 状态 ──
  const [step, setStep] = useState<WizardStep>('script');
  const [storyText, setStoryText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // 叙事提取结果
  const [narrative, setNarrative] = useState<NarrateResponse | null>(null);
  // 可编辑副本
  const [characters, setCharacters] = useState<NarrateCharacter[]>([]);
  const [scenes, setScenes] = useState<NarrateScene[]>([]);
  const [shots, setShots] = useState<NarrateShot[]>([]);

  // 生成参数
  const [numShots, setNumShots] = useState(0);
  const [genParams, setGenParams] = useState({ width: 1024, height: 1024, steps: 20, style: 'anime' });
  const [progress, setProgress] = useState({ current: 0, total: 0 });

  // Store
  const loadStoryboardToCanvas = useCanvasStore((s) => s.loadStoryboardToCanvas);

  // 拖拽位置
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 340, y: 60 });
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

  // ── 步骤1: 解析叙事 ──
  const handleExtract = useCallback(async () => {
    if (!storyText.trim()) {
      setError('请输入故事内容');
      return;
    }
    setError('');
    setBusy(true);
    try {
      const r = await extractNarrative({ story_text: storyText.trim(), num_shots: numShots || 0 });
      setNarrative(r);
      setCharacters(r.characters.map((c) => ({ ...c })));
      setScenes(r.scenes.map((s) => ({ ...s })));
      setShots(r.shots.map((sh) => ({ ...sh })));
      setStep('characters');
      toastChannel.push('success', `已解析「${r.title}」: ${r.characters.length} 角色 · ${r.scenes.length} 场景 · ${r.shots.length} 分镜`);
    } catch (e: any) {
      setError(e?.message || '解析失败');
    } finally {
      setBusy(false);
    }
  }, [storyText, numShots]);

  // ── 更新角色 ──
  const handleCharChange = (idx: number, field: keyof NarrateCharacter, value: string) => {
    setCharacters((prev) => prev.map((c, i) => (i === idx ? { ...c, [field]: value } : c)));
  };

  // ── 更新场景 ──
  const handleSceneChange = (idx: number, field: keyof NarrateScene, value: string) => {
    setScenes((prev) => prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s)));
  };

  // ── 更新分镜 ──
  const handleShotChange = (idx: number, field: keyof NarrateShot, value: string) => {
    setShots((prev) => prev.map((sh, i) => (i === idx ? { ...sh, [field]: value } : sh)));
  };

  // ── 步骤5: 提交 storyboard 生成 ──
  const handleGenerate = useCallback(async () => {
    setBusy(true);
    setStep('generate');
    setProgress({ current: 0, total: shots.length });

    try {
      const res = await planStoryboard({
        description: shots.map((s) => s.prompt).join('\n'),
        num_shots: shots.length,
        style: genParams.style,
        characters: characters.filter((c) => c.name).map((c) => c.name),
      });

      setProgress({ current: res.total_shots, total: res.total_shots });

      if (res.shots.length > 0) {
        loadStoryboardToCanvas(res.shots);
        toastChannel.push('success', `已生成 ${res.total_shots} 个分镜到画布`);
      }
    } catch (e: any) {
      toastChannel.push('error', `生成失败: ${e?.message || '未知错误'}`);
    } finally {
      setBusy(false);
    }
  }, [shots, genParams, characters, loadStoryboardToCanvas]);

  // ── 拖拽 ──
  const handleMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button,input,textarea,select')) return;
    dragRef.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragRef.current) return;
    setPos({ x: e.clientX - dragRef.current.dx, y: e.clientY - dragRef.current.dy });
  };
  const handleMouseUp = () => { dragRef.current = null; };

  // ── 步骤进度条 ──
  const stepIdx = STEPS.findIndex((s) => s.id === step);

  return (
    <div
      ref={panelRef}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{
        position: 'fixed',
        left: pos.x,
        top: pos.y,
        width: 520,
        maxHeight: 'calc(100vh - 120px)',
        background: theme.bg.panel,
        border: `1px solid ${theme.border.default}`,
        borderRadius: 12,
        boxShadow: '0 8px 40px rgba(0,0,0,0.5), 0 0 0 1px rgba(79,140,255,0.08)',
        zIndex: 1001,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        userSelect: 'none',
      }}
    >
      {/* 标题栏 */}
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', borderBottom: `1px solid ${theme.border.default}`,
          background: theme.bg.header, cursor: 'move',
        }}
      >
        <span style={{ color: theme.text.primary, fontWeight: 700, fontSize: 14 }}>
          🎬 故事板向导
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', color: theme.text.muted,
            fontSize: 18, cursor: 'pointer', padding: '0 4px',
          }}
          children="✕"
        />
      </div>

      {/* 步骤指示器 */}
      <div style={{ display: 'flex', padding: '10px 16px', gap: 4, borderBottom: `1px solid ${theme.border.default}`, background: theme.bg.card }}>
        {STEPS.map((s, i) => (
          <div
            key={s.id}
            onClick={() => {
              if (i < stepIdx || (s.id === 'shots' && shots.length > 0)) setStep(s.id);
              if (i === 0) setStep('script');
            }}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px',
              borderRadius: 8, fontSize: 12, fontWeight: i === stepIdx ? 700 : 500,
              color: i === stepIdx ? theme.accent.blue : i < stepIdx ? theme.accent.green : theme.text.muted,
              background: i === stepIdx ? theme.bg.hoverStrong : i < stepIdx ? 'rgba(70,210,122,0.08)' : 'transparent',
              cursor: i <= stepIdx ? 'pointer' : 'default',
              transition: 'all 0.2s',
              border: i === stepIdx ? `1px solid ${theme.accent.blue}40` : '1px solid transparent',
            }}
          >
            <span>{s.icon}</span>
            <span>{s.label}</span>
            {i < stepIdx && <span style={{ marginLeft: 'auto', fontSize: 10 }}>✓</span>}
          </div>
        ))}
      </div>

      {/* 内容区 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16, color: theme.text.primary }}>
        {/* ── 步骤1: 剧本输入 ── */}
        {step === 'script' && (
          <div>
            <label style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, display: 'block', color: theme.text.secondary }}>
              输入你的故事
            </label>
            <textarea
              value={storyText}
              onChange={(e) => { setStoryText(e.target.value); setError(''); }}
              placeholder="在此粘贴故事/剧本/小说片段…&#10;&#10;例如：&#10;少年林风在青云山修炼，一日遇到受伤的白狐少女雪璃。林风救了她，在林间小屋避雨。原来雪璃是妖族公主…"
              rows={8}
              style={{
                width: '100%', padding: 12, borderRadius: 8,
                background: theme.bg.input, color: theme.text.primary,
                border: `1px solid ${error ? theme.danger.border : theme.border.default}`,
                fontSize: 13, lineHeight: 1.6, resize: 'vertical',
                fontFamily: 'inherit',
              }}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10 }}>
              <label style={{ fontSize: 12, color: theme.text.muted }}>期望分镜数:</label>
              <input
                type="number"
                value={numShots || ''}
                onChange={(e) => setNumShots(Math.max(0, Math.min(20, parseInt(e.target.value) || 0)))}
                placeholder="自动"
                min={0} max={20}
                style={{
                  width: 60, padding: '4px 8px', borderRadius: 6,
                  background: theme.bg.input, color: theme.text.primary,
                  border: `1px solid ${theme.border.default}`, fontSize: 13, textAlign: 'center',
                }}
              />
              <span style={{ fontSize: 11, color: theme.text.hint }}>0=AI 自动决定</span>
            </div>
            {error && (
              <div style={{ marginTop: 8, color: theme.accent.red, fontSize: 12 }}>{error}</div>
            )}
            <button
              onClick={handleExtract}
              disabled={busy || !storyText.trim()}
              style={{
                marginTop: 12, width: '100%', padding: '10px 0', borderRadius: 8,
                background: busy ? '#1e3a5a' : 'linear-gradient(135deg, #2563eb, #7c3aed)',
                color: '#fff', border: 'none', fontSize: 14, fontWeight: 600,
                cursor: busy ? 'wait' : 'pointer', transition: 'all 0.2s',
                opacity: busy || !storyText.trim() ? 0.6 : 1,
              }}
            >
              {busy ? '🔮 AI 正在解析叙事…' : '✨ 解析叙事'}
            </button>
          </div>
        )}

        {/* ── 步骤2: 角色与场景确认 ── */}
        {step === 'characters' && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
              <span style={{ fontSize: 15, fontWeight: 700 }}>{narrative?.title || '未命名故事'}</span>
              {narrative?.genre && (
                <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: theme.bg.hoverStrong, color: theme.accent.blue }}>
                  {narrative.genre}
                </span>
              )}
              {narrative?.style_suggestion && (
                <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: 'rgba(167,139,250,0.1)', color: theme.accent.purple }}>
                  {narrative.style_suggestion}
                </span>
              )}
            </div>

            {/* 角色卡片 */}
            <h4 style={{ fontSize: 13, fontWeight: 600, color: theme.accent.blue, marginBottom: 8 }}>
              🧑‍🎨 角色 ({characters.length})
            </h4>
            {characters.length === 0 && (
              <div style={{ color: theme.text.muted, fontSize: 12, padding: 12, textAlign: 'center' }}>
                未检测到角色，请在上一步添加更详细的角色描述
              </div>
            )}
            {characters.map((ch, i) => (
              <div
                key={i}
                style={{
                  marginBottom: 8, padding: 10, borderRadius: 8,
                  background: theme.bg.card, border: `1px solid ${theme.border.default}`,
                }}
              >
                <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                  <input
                    value={ch.name}
                    onChange={(e) => handleCharChange(i, 'name', e.target.value)}
                    placeholder="角色名"
                    style={inlineInputStyle(120)}
                  />
                  <input
                    value={ch.role}
                    onChange={(e) => handleCharChange(i, 'role', e.target.value)}
                    placeholder="定位"
                    style={inlineInputStyle(80)}
                  />
                </div>
                <input
                  value={ch.description}
                  onChange={(e) => handleCharChange(i, 'description', e.target.value)}
                  placeholder="外观描述"
                  style={fullInputStyle}
                />
                <input
                  value={ch.traits}
                  onChange={(e) => handleCharChange(i, 'traits', e.target.value)}
                  placeholder="性格特征"
                  style={{ ...fullInputStyle, marginTop: 4 }}
                />
              </div>
            ))}

            {/* 场景卡片 */}
            <h4 style={{ fontSize: 13, fontWeight: 600, color: theme.accent.teal, margin: '16px 0 8px' }}>
              🌄 场景 ({scenes.length})
            </h4>
            {scenes.map((sc, i) => (
              <div
                key={i}
                style={{
                  marginBottom: 8, padding: 10, borderRadius: 8,
                  background: theme.bg.card, border: `1px solid ${theme.border.default}`,
                }}
              >
                <input
                  value={sc.name}
                  onChange={(e) => handleSceneChange(i, 'name', e.target.value)}
                  placeholder="场景名称"
                  style={inlineInputStyle(180)}
                />
                <select
                  value={sc.mood}
                  onChange={(e) => handleSceneChange(i, 'mood', e.target.value)}
                  style={{ ...inlineInputStyle(100), marginLeft: 8 }}
                >
                  <option value="">氛围</option>
                  {['温馨', '紧张', '浪漫', '神秘', '庄严', '悲伤', '欢快', '恐怖', '史诗'].map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
                <input
                  value={sc.description}
                  onChange={(e) => handleSceneChange(i, 'description', e.target.value)}
                  placeholder="场景描述"
                  style={{ ...fullInputStyle, marginTop: 4 }}
                />
              </div>
            ))}

            {/* 导航按钮 */}
            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button onClick={() => setStep('script')} style={secondaryBtnStyle}>
                ← 返回修改剧本
              </button>
              <button
                onClick={() => setStep('shots')}
                disabled={shots.length === 0}
                style={{ ...primaryBtnStyle, flex: 1, opacity: shots.length === 0 ? 0.5 : 1 }}
              >
                继续 → 分镜预览 ({shots.length})
              </button>
            </div>
          </div>
        )}

        {/* ── 步骤3: 分镜预览与编辑 ── */}
        {step === 'shots' && (
          <div>
            <h4 style={{ fontSize: 13, fontWeight: 600, color: theme.accent.amber, marginBottom: 8 }}>
              🎬 分镜列表 ({shots.length})
            </h4>

            {/* 生成参数 */}
            <div style={{
              display: 'flex', gap: 10, marginBottom: 14, padding: 10,
              borderRadius: 8, background: theme.bg.card, border: `1px solid ${theme.border.default}`,
              flexWrap: 'wrap',
            }}>
              {paramInput('宽', genParams.width, (v) => setGenParams((p) => ({ ...p, width: v })))}
              {paramInput('高', genParams.height, (v) => setGenParams((p) => ({ ...p, height: v })))}
              {paramInput('步数', genParams.steps, (v) => setGenParams((p) => ({ ...p, steps: v })))}
              <select
                value={genParams.style}
                onChange={(e) => setGenParams((p) => ({ ...p, style: e.target.value }))}
                style={selectStyle}
              >
                <option value="anime">动漫风格</option>
                <option value="realistic">写实风格</option>
                <option value="ink_wash">水墨风格</option>
                <option value="manga">漫画风格</option>
              </select>
            </div>

            {/* 分镜列表 */}
            <div style={{ maxHeight: 360, overflowY: 'auto' }}>
              {shots.map((sh, i) => (
                <div
                  key={sh.shot_id}
                  style={{
                    marginBottom: 8, padding: 10, borderRadius: 8,
                    background: theme.bg.card, border: `1px solid ${theme.border.default}`,
                    borderLeft: `3px solid ${theme.accent.amber}`,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: theme.accent.amber, minWidth: 36 }}>
                      # {sh.shot_id}
                    </span>
                    <span style={{ fontSize: 12, color: theme.text.muted }}>
                      {sh.character || '—'} @ {sh.scene || '—'}
                    </span>
                  </div>
                  <input
                    value={sh.description}
                    onChange={(e) => handleShotChange(i, 'description', e.target.value)}
                    placeholder="分镜描述（中文）"
                    style={fullInputStyle}
                  />
                  <textarea
                    value={sh.prompt}
                    onChange={(e) => handleShotChange(i, 'prompt', e.target.value)}
                    placeholder="英文文生图 prompt"
                    rows={2}
                    style={{ ...fullInputStyle, marginTop: 4, resize: 'vertical', fontSize: 11 }}
                  />
                </div>
              ))}
            </div>

            {/* 导航按钮 */}
            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button onClick={() => setStep('characters')} style={secondaryBtnStyle}>
                ← 返回角色场景
              </button>
              <button
                onClick={handleGenerate}
                disabled={busy || shots.length === 0}
                style={{ ...primaryBtnStyle, flex: 1, background: busy ? '#1e3a5a' : 'linear-gradient(135deg, #f59e0b, #ef4444)', opacity: busy ? 0.6 : 1 }}
              >
                {busy ? '⏳ 正在生成…' : `🎬 开始生成 ${shots.length} 个分镜`}
              </button>
            </div>
          </div>
        )}

        {/* ── 步骤4: 生成进度 ── */}
        {step === 'generate' && (
          <div style={{ textAlign: 'center', padding: '30px 0' }}>
            {busy ? (
              <>
                <div style={{ fontSize: 40, marginBottom: 16 }}>🔮</div>
                <div style={{ fontSize: 15, fontWeight: 700, color: theme.text.primary, marginBottom: 8 }}>
                  AI 正在生成分镜…
                </div>
                <div style={{ fontSize: 12, color: theme.text.muted, marginBottom: 16 }}>
                  {progress.total > 0
                    ? `正在生成 ${progress.current} / ${progress.total} 个分镜`
                    : '正在规划与组装工作流…'}
                </div>
                {/* 进度条 */}
                <div style={{
                  width: '100%', height: 4, borderRadius: 2,
                  background: theme.bg.input, overflow: 'hidden',
                }}>
                  <div style={{
                    width: progress.total > 0 ? `${(progress.current / progress.total) * 100}%` : '30%',
                    height: '100%', borderRadius: 2,
                    background: 'linear-gradient(90deg, #f59e0b, #ef4444)',
                    transition: 'width 0.3s ease',
                    animation: 'wizard-progress 2s infinite',
                  }} />
                </div>
                <style>{`@keyframes wizard-progress{0%,100%{opacity:1}50%{opacity:.6}}`}</style>
              </>
            ) : (
              <>
                <div style={{ fontSize: 40, marginBottom: 16 }}>✅</div>
                <div style={{ fontSize: 15, fontWeight: 700, color: theme.accent.green, marginBottom: 8 }}>
                  分镜生成完成！
                </div>
                <div style={{ fontSize: 12, color: theme.text.muted, marginBottom: 20 }}>
                  已添加到画布，可在故事板时间轴中查看
                </div>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
                  <button onClick={() => { setStep('shots'); setNarrative(null); setStoryText(''); }} style={secondaryBtnStyle}>
                    🆕 新建故事
                  </button>
                  <button onClick={onClose} style={primaryBtnStyle}>
                    完成 ✓
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 辅助样式 ──
const inlineInputStyle = (width: number): React.CSSProperties => ({
  width, padding: '4px 8px', borderRadius: 6,
  background: theme.bg.input, color: theme.text.primary,
  border: `1px solid ${theme.border.default}`, fontSize: 12,
});

const fullInputStyle: React.CSSProperties = {
  width: '100%', padding: '6px 8px', borderRadius: 6,
  background: theme.bg.input, color: theme.text.primary,
  border: `1px solid ${theme.border.default}`, fontSize: 12,
  boxSizing: 'border-box',
};

const primaryBtnStyle: React.CSSProperties = {
  padding: '10px 20px', borderRadius: 8,
  background: 'linear-gradient(135deg, #2563eb, #7c3aed)',
  color: '#fff', border: 'none', fontSize: 13, fontWeight: 600,
  cursor: 'pointer', transition: 'all 0.2s',
};

const secondaryBtnStyle: React.CSSProperties = {
  padding: '10px 20px', borderRadius: 8,
  background: theme.bg.input, color: theme.text.secondary,
  border: `1px solid ${theme.border.default}`, fontSize: 13,
  cursor: 'pointer', transition: 'all 0.2s',
};

const selectStyle: React.CSSProperties = {
  padding: '4px 8px', borderRadius: 6,
  background: theme.bg.input, color: theme.text.primary,
  border: `1px solid ${theme.border.default}`, fontSize: 12,
};

function paramInput(label: string, value: number, onChange: (v: number) => void): JSX.Element {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: theme.text.muted }}>
      {label}
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Math.max(64, Math.min(4096, parseInt(e.target.value) || 512)))}
        style={{ width: 70, padding: '4px 6px', borderRadius: 6, background: theme.bg.input, color: theme.text.primary, border: `1px solid ${theme.border.default}`, fontSize: 12, textAlign: 'center' }}
      />
    </label>
  );
}
