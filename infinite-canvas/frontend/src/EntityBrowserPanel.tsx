// v4.56 EntityBrowserPanel — 实体注册表浏览 + 加载到策划层画布
// 浏览角色/场景/道具/风格实体，点击即可在策划层画布创建实体节点
import { useEffect, useState } from 'react';
import { listEntities, getEntityPrompt } from './api';
import type { EntityItem, EntityKind } from './types';
import { useCanvasStore } from './store';
import { toastChannel } from './App';
import { theme } from './theme';

interface Props {
  onClose: () => void;
}

const KIND_META: Record<EntityKind, { label: string; icon: string; color: string }> = {
  character: { label: '角色', icon: '👤', color: '#ff7eb6' },
  scene: { label: '场景', icon: '🏞', color: '#7ec8ff' },
  prop: { label: '道具', icon: '🗝', color: '#ffd97e' },
  style: { label: '风格', icon: '🎨', color: '#b87eff' },
};

const S = {
  panel: {
    position: 'absolute', right: 346, top: 44, bottom: 0, width: 300,
    background: theme.bg.surface, borderLeft: `1px solid ${theme.border.card}`,
    zIndex: 99, display: 'flex', flexDirection: 'column',
    boxShadow: '-2px 0 16px rgba(0,0,0,0.2)', fontFamily: 'ui-sans-serif, system-ui, sans-serif',
  } as React.CSSProperties,
  header: {
    padding: '10px 14px', borderBottom: `1px solid ${theme.border.subtle}`,
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  } as React.CSSProperties,
  body: {
    flex: 1, overflowY: 'auto', padding: '6px 8px',
  } as React.CSSProperties,
  btn: {
    padding: '4px 10px', borderRadius: 5, border: 'none',
    fontSize: 11, fontWeight: 600, cursor: 'pointer',
  },
  field: {
    width: '100%', padding: '4px 8px', borderRadius: 5,
    border: `1px solid ${theme.border.card}`, background: theme.bg.card,
    color: theme.text.primary, fontSize: 11, outline: 'none',
    boxSizing: 'border-box' as const,
  },
};

export function EntityBrowserPanel({ onClose }: Props) {
  const [entities, setEntities] = useState<EntityItem[]>([]);
  const [tab, setTab] = useState<EntityKind>('character');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const addNode = useCanvasStore((s) => s.addNode);
  const setActiveLayer = useCanvasStore((s) => s.setActiveLayer);

  useEffect(() => {
    setLoading(true);
    listEntities(tab)
      .then((r) => setEntities(r.entities))
      .catch(() => toastChannel.push('error', '无法加载实体'))
      .finally(() => setLoading(false));
  }, [tab]);

  const loadToCanvas = async (ent: EntityItem) => {
    // 切换到策划层
    setActiveLayer('planning');

    // 获取实体 prompt 前缀
    let extraPrompt = '';
    try {
      const r = await getEntityPrompt(ent.entity_id);
      extraPrompt = r.prompt;
    } catch { /* 忽略 */ }

    addNode({
      id: `entity-${ent.entity_id}`,
      filename: '',
      prompt: extraPrompt || ent.description,
      templateId: 'entity',
      x: 100 + Math.random() * 400,
      y: 100 + Math.random() * 300,
      width: 260,
      height: 160,
      kind: 'image',
      mode: 'storyboard',
      description: `${ent.kind}: ${ent.name}`,
      negative: ent.prompt_override || undefined,
      seed: undefined,
      createdAt: Date.now(),
    });
    toastChannel.push('success', `"${ent.name}" 已加载到策划层画布`);
  };

  const filtered = query
    ? entities.filter((e) =>
        e.name.includes(query) || e.alias.includes(query) || e.description.includes(query) || e.tags.some((t) => t.includes(query)),
      )
    : entities;

  return (
    <div style={S.panel}>
      <div style={S.header}>
        <span style={{ fontSize: 13, fontWeight: 700, color: theme.text.primary }}>📦 实体库</span>
        <button onClick={onClose} style={{ ...S.btn, background: 'transparent', color: theme.text.hint, fontSize: 16 }}>
          ✕
        </button>
      </div>

      {/* 类别标签 */}
      <div style={{ display: 'flex', padding: '6px 8px', gap: 4 }}>
        {(Object.keys(KIND_META) as EntityKind[]).map((k) => (
          <button key={k} onClick={() => setTab(k)}
            style={{
              ...S.btn,
              flex: 1,
              background: tab === k ? `${KIND_META[k].color}22` : 'transparent',
              border: `1px solid ${tab === k ? KIND_META[k].color : theme.border.subtle}`,
              color: tab === k ? KIND_META[k].color : theme.text.hint,
            }}>
            {KIND_META[k].icon} {KIND_META[k].label}
          </button>
        ))}
      </div>

      {/* 搜索 */}
      <div style={{ padding: '0 8px 6px' }}>
        <input style={S.field} placeholder="搜索实体…" value={query}
          onChange={(e) => setQuery(e.target.value)} />
      </div>

      {/* 列表 */}
      <div style={S.body}>
        {loading ? (
          <div style={{ textAlign: 'center', color: theme.text.hint, fontSize: 12, padding: 20 }}>加载中…</div>
        ) : filtered.length === 0 ? (
          <div style={{ textAlign: 'center', color: theme.text.tiny, fontSize: 12, padding: 20 }}>
            {query ? '无匹配结果' : '暂无实体，请先创建'}
          </div>
        ) : (
          filtered.map((ent) => {
            const m = KIND_META[ent.kind];
            return (
              <div key={ent.entity_id}
                style={{
                  padding: '8px 10px', marginBottom: 4, borderRadius: 6,
                  background: theme.bg.card, border: `1px solid ${theme.border.subtle}`,
                  cursor: 'pointer',
                }}
                onClick={() => loadToCanvas(ent)}
                title="点击加载到画布"
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: m.color }}>
                    {m.icon} {ent.name}
                  </span>
                  {ent.alias && (
                    <span style={{ fontSize: 10, color: theme.text.tiny }}>{ent.alias}</span>
                  )}
                </div>
                {ent.description && (
                  <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 3, lineHeight: 1.4 }}>
                    {ent.description.slice(0, 80)}
                  </div>
                )}
                {ent.tags.length > 0 && (
                  <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                    {ent.tags.slice(0, 4).map((t) => (
                      <span key={t} style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: `${m.color}18`, color: m.color }}>
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* 底部提示 */}
      <div style={{ padding: '6px 14px', borderTop: `1px solid ${theme.border.subtle}`, fontSize: 10, color: theme.text.tiny }}>
        点击实体即可将其添加到策划层画布
      </div>
    </div>
  );
}
