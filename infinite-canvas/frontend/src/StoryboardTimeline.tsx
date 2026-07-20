// 无限画布 v4.58 · 故事板时间轴（增强版：资产绑定 + 图片预览 + 画布联动）
import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useCanvasStore } from './store';
import { batchGenerateStoryboard, listEntities, imageUrl } from './api';
import { theme } from './theme';
import type { ShotStatus, EntityItem, EntityKind } from './types';

const STATUS_COLORS: Record<ShotStatus, string> = {
  idle: theme.text.muted,
  pending: theme.accent.yellow,
  generating: theme.accent.blue,
  done: theme.accent.green,
  failed: theme.accent.red,
};

const STATUS_LABELS: Record<ShotStatus, string> = {
  idle: '待生成',
  pending: '排队中',
  generating: '生成中…',
  done: '已完成',
  failed: '失败',
};

const KIND_META: Record<EntityKind, { label: string; icon: string; color: string }> = {
  character: { label: '角色', icon: '👤', color: '#ff7eb6' },
  scene: { label: '场景', icon: '🏞', color: '#7ec8ff' },
  prop: { label: '道具', icon: '🗝', color: '#ffd97e' },
  style: { label: '风格', icon: '🎨', color: '#b87eff' },
};

export default function StoryboardTimeline() {
  const {
    storyboardShots,
    storyboardBatchBusy,
    setStoryboardTimelineOpen,
    syncStoryboardFromCanvas,
    updateShotStatus,
    reorderShots,
    setStoryboardBatchBusy,
    bindAssetToShot,
    unbindAssetFromShot,
  } = useCanvasStore();

  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [assetPickerShot, setAssetPickerShot] = useState<string | null>(null); // nodeId of shot with open picker
  const [entities, setEntities] = useState<EntityItem[]>([]);
  const [entityQuery, setEntityQuery] = useState('');
  const [entityTab, setEntityTab] = useState<EntityKind>('character');
  const scrollRef = useRef<HTMLDivElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);

  // Load entities when picker opens
  useEffect(() => {
    if (assetPickerShot) {
      listEntities(entityTab)
        .then((r) => setEntities(r.entities))
        .catch(() => setErrorMsg('无法加载实体列表'));
    }
  }, [assetPickerShot, entityTab]);

  // Close picker on outside click
  useEffect(() => {
    if (!assetPickerShot) return;
    const handler = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setAssetPickerShot(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [assetPickerShot]);

  const handleSync = useCallback(() => {
    syncStoryboardFromCanvas();
    setErrorMsg(null);
  }, [syncStoryboardFromCanvas]);

  const handleBatchGenerate = useCallback(async () => {
    const shots = useCanvasStore.getState().storyboardShots;
    if (shots.length === 0) {
      setErrorMsg('请先同步画布分镜节点');
      return;
    }

    const idleShots = shots.filter((s) => s.status === 'idle' || s.status === 'failed');
    if (idleShots.length === 0) {
      // Try regenerating all
      const allShots = shots;
      if (allShots.every((s) => s.status === 'done')) {
        setErrorMsg('所有分镜已完成。已重新生成全部。');
        allShots.forEach((s) => updateShotStatus(s.nodeId, 'pending'));
        allShots.forEach((s) => updateShotStatus(s.nodeId, 'generating'));
        // fall through to batch generate
        try {
          const prompts = allShots.map((s) => s.prompt);
          const result = await batchGenerateStoryboard(
            { prompts, width: 1024, height: 1024, steps: 20, cfg: 7.0, seed: Date.now() % 65536 },
          );
          result.frames.forEach((frame, i) => {
            const shot = allShots[i];
            if (shot) {
              if (frame.status === 'done' && frame.image) {
                updateShotStatus(shot.nodeId, 'done', frame.image);
              } else {
                updateShotStatus(shot.nodeId, 'failed');
              }
            }
          });
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : '批量生成失败';
          setErrorMsg(msg);
          allShots.forEach((s) => updateShotStatus(s.nodeId, 'failed'));
        } finally {
          setStoryboardBatchBusy(false);
          syncStoryboardFromCanvas();
        }
        return;
      }
      setErrorMsg('所有分镜已生成或正在生成中');
      return;
    }

    setStoryboardBatchBusy(true);
    setErrorMsg(null);

    idleShots.forEach((s) => updateShotStatus(s.nodeId, 'pending'));
    idleShots.forEach((s) => updateShotStatus(s.nodeId, 'generating'));

    try {
      const prompts = idleShots.map((s) => s.prompt);

      const result = await batchGenerateStoryboard(
        { prompts, width: 1024, height: 1024, steps: 20, cfg: 7.0, seed: 42 + idleShots[0].shotIndex },
      );

      result.frames.forEach((frame, i) => {
        const shot = idleShots[i];
        if (shot) {
          if (frame.status === 'done' && frame.image) {
            updateShotStatus(shot.nodeId, 'done', frame.image);
          } else if (frame.status === 'failed') {
            updateShotStatus(shot.nodeId, 'failed');
          }
        }
      });

      // Any remaining pending/generating → failed
      const updated = useCanvasStore.getState().storyboardShots;
      updated.forEach((s) => {
        if (s.status === 'pending' || s.status === 'generating') {
          updateShotStatus(s.nodeId, 'failed');
        }
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '批量生成失败';
      setErrorMsg(msg);
      useCanvasStore.getState().storyboardShots.forEach((s) => {
        if (s.status === 'pending' || s.status === 'generating') {
          updateShotStatus(s.nodeId, 'failed');
        }
      });
    } finally {
      setStoryboardBatchBusy(false);
      syncStoryboardFromCanvas();
    }
  }, [setStoryboardBatchBusy, updateShotStatus, syncStoryboardFromCanvas]);

  // Drag handlers
  const handleDragStart = useCallback((index: number) => setDragIndex(index), []);
  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault();
    setOverIndex(index);
  }, []);
  const handleDragLeave = useCallback(() => setOverIndex(null), []);
  const handleDrop = useCallback(
    (e: React.DragEvent, toIndex: number) => {
      e.preventDefault();
      if (dragIndex !== null && dragIndex !== toIndex) reorderShots(dragIndex, toIndex);
      setDragIndex(null);
      setOverIndex(null);
    },
    [dragIndex, reorderShots],
  );
  const handleDragEnd = useCallback(() => {
    setDragIndex(null);
    setOverIndex(null);
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (scrollRef.current) scrollRef.current.scrollLeft += e.deltaY;
  }, []);

  // Entity picker filter
  const entityFiltered = entityQuery
    ? entities.filter((e) => e.name.includes(entityQuery) || e.alias.includes(entityQuery) || e.tags.some((t) => t.includes(entityQuery)))
    : entities;

  const doneCount = storyboardShots.filter((s) => s.status === 'done').length;
  const totalCount = storyboardShots.length;
  const hasShots = totalCount > 0;

  return (
    <div style={timelineContainer}>
      {/* Header bar */}
      <div style={headerBar}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ color: theme.text.primary, fontWeight: 600, fontSize: 13 }}>
            🎬 故事板时间轴
          </span>
          {hasShots && (
            <span style={hintBadge}>
              {doneCount}/{totalCount} 已完成
            </span>
          )}
          {storyboardBatchBusy && (
            <span style={pendingBadge}>
              ⏳ 批量生成中...
            </span>
          )}
          {errorMsg && (
            <span style={errorBadge}>{errorMsg}</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handleSync} title="从画布同步 storyboard 节点" style={btnStyle()}>
            🔄 同步画布
          </button>
          <button
            disabled={!hasShots || storyboardBatchBusy}
            onClick={handleBatchGenerate}
            title="批量生成所有待处理分镜"
            style={btnStyle('accent', !hasShots || storyboardBatchBusy)}
          >
            ⚡ 批量生成
          </button>
          <button onClick={() => setStoryboardTimelineOpen(false)} title="关闭时间轴" style={btnStyle()}>
            ✕
          </button>
        </div>
      </div>

      {/* Scrollable shot row */}
      <div ref={scrollRef} onWheel={handleWheel} style={shotRow}>
        {!hasShots && (
          <div style={emptyHint}>
            <p style={{ margin: '0 0 8px' }}>暂无分镜数据</p>
            <p style={{ margin: 0, fontSize: 11, color: theme.text.hint }}>
              请在 <strong>分镜规划</strong> 面板中规划分镜并「加载到画布」，然后点击「🔄 同步画布」
            </p>
          </div>
        )}

        {storyboardShots.map((shot, i) => {
          const isDragging = dragIndex === i;
          const isOver = overIndex === i;
          const statusColor = STATUS_COLORS[shot.status];

          return (
            <div
              key={shot.nodeId}
              draggable
              onDragStart={() => handleDragStart(i)}
              onDragOver={(e) => handleDragOver(e, i)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, i)}
              onDragEnd={handleDragEnd}
              style={shotCard(isDragging, isOver)}
            >
              {/* Shot index + status badge */}
              <div style={cardHeader}>
                <div style={{ ...statusDot, background: statusColor }}>
                  {shot.shotIndex}
                </div>
                <span style={{ fontSize: 10, fontWeight: 600, color: statusColor }}>
                  {STATUS_LABELS[shot.status]}
                </span>
              </div>

              {/* Thumbnail + Prompt */}
              <div style={{ display: 'flex', gap: 6, flex: 1, minHeight: 0 }}>
                {/* Thumbnail */}
                <div style={thumbBox}>
                  {shot.generatedImage ? (
                    <img
                      src={imageUrl(shot.generatedImage)}
                      alt={`shot ${shot.shotIndex}`}
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  ) : (
                    <span style={{ fontSize: 18, opacity: 0.3 }}>
                      {shot.status === 'generating' ? '⏳' : shot.status === 'done' ? '✅' : '🖼'}
                    </span>
                  )}
                </div>

                {/* Prompt preview */}
                <div style={promptBox}>
                  {shot.prompt || '(无提示词)'}
                </div>
              </div>

              {/* Bottom actions row */}
              <div style={cardFooter}>
                <span style={{ fontSize: 10, color: theme.text.muted }}>
                  {shot.duration ? `${shot.duration}s` : '--'}
                </span>

                {/* Asset bind button */}
                <button
                  title="绑定实体资产到分镜"
                  style={miniBtn}
                  onClick={(e) => {
                    e.stopPropagation();
                    setAssetPickerShot(assetPickerShot === shot.nodeId ? null : shot.nodeId);
                  }}
                >
                  🔗 {shot.referenceAssets.length > 0 ? shot.referenceAssets.length : '+'}
                </button>

                {/* Asset chips */}
                {shot.referenceAssets.length > 0 && (
                  <span style={{ fontSize: 9, color: theme.text.tiny, maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {shot.referenceAssets.join(', ')}
                  </span>
                )}
              </div>

              {/* Entity picker popover */}
              {assetPickerShot === shot.nodeId && (
                <div
                  ref={pickerRef}
                  style={pickerStyle}
                  onClick={(e) => e.stopPropagation()}
                >
                  {/* Tab row */}
                  <div style={{ display: 'flex', gap: 2, marginBottom: 4 }}>
                    {(Object.keys(KIND_META) as EntityKind[]).map((k) => (
                      <button
                        key={k}
                        onClick={() => setEntityTab(k)}
                        style={{
                          ...miniTab,
                          background: entityTab === k ? `${KIND_META[k].color}22` : 'transparent',
                          color: entityTab === k ? KIND_META[k].color : theme.text.hint,
                        }}
                      >
                        {k.slice(0, 2)}
                      </button>
                    ))}
                  </div>
                  {/* Search */}
                  <input
                    style={fieldStyle}
                    placeholder="搜索实体…"
                    value={entityQuery}
                    onChange={(e) => setEntityQuery(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                  />
                  {/* Entity list */}
                  <div style={{ maxHeight: 120, overflowY: 'auto', marginTop: 4 }}>
                    {entityFiltered.length === 0 ? (
                      <div style={{ fontSize: 10, color: theme.text.tiny, padding: 6, textAlign: 'center' }}>
                        无匹配实体
                      </div>
                    ) : (
                      entityFiltered.slice(0, 12).map((ent) => {
                        const bound = shot.referenceAssets.includes(ent.entity_id);
                        return (
                          <div
                            key={ent.entity_id}
                            style={entityRow(bound)}
                            onClick={() => {
                              if (bound) {
                                unbindAssetFromShot(shot.nodeId, ent.entity_id);
                              } else {
                                bindAssetToShot(shot.nodeId, ent.entity_id);
                              }
                            }}
                          >
                            <span style={{ fontSize: 11 }}>{KIND_META[ent.kind].icon} {ent.name}</span>
                            <span style={{ fontSize: 9, color: bound ? theme.accent.blue : theme.text.muted }}>
                              {bound ? '已绑定' : '点击绑定'}
                            </span>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              )}

              {/* Arrow between shots */}
              {i < storyboardShots.length - 1 && (
                <div style={arrowStyle}>→</div>
              )}
            </div>
          );
        })}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}

// ─── Styles ────────────────────────────────────────────────────────

const timelineContainer: React.CSSProperties = {
  position: 'fixed', bottom: 0, left: 0, right: 0, height: 220,
  background: theme.bg.panel, borderTop: `1px solid ${theme.border.default}`,
  zIndex: 100, display: 'flex', flexDirection: 'column',
};

const headerBar: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  padding: '6px 16px', borderBottom: `1px solid ${theme.border.subtle}`,
  background: theme.bg.header, flexShrink: 0,
};

const shotRow: React.CSSProperties = {
  flex: 1, overflowX: 'auto', overflowY: 'hidden',
  display: 'flex', alignItems: 'flex-start', gap: 10,
  padding: '10px 16px', scrollBehavior: 'smooth',
};

const emptyHint: React.CSSProperties = {
  width: '100%', textAlign: 'center', color: theme.text.muted,
  fontSize: 13, padding: '40px 0',
};

const hintBadge: React.CSSProperties = {
  fontSize: 11, color: theme.text.muted, background: theme.bg.input,
  borderRadius: 4, padding: '1px 8px',
};

const pendingBadge: React.CSSProperties = {
  fontSize: 11, color: theme.accent.blue, background: theme.bg.hover,
  borderRadius: 4, padding: '1px 8px',
};

const errorBadge: React.CSSProperties = {
  fontSize: 11, color: theme.accent.red, background: theme.danger?.bg ?? '#3c1e1e',
  borderRadius: 4, padding: '1px 8px',
};

function btnStyle(variant?: 'accent', disabled = false): React.CSSProperties {
  return {
    padding: '4px 12px', borderRadius: 6,
    border: `1px solid ${variant === 'accent' ? theme.accent.blue : theme.border.subtle}`,
    background: variant === 'accent' ? theme.accent.blue : theme.bg.input,
    color: variant === 'accent' ? '#fff' : theme.text.primary,
    cursor: disabled ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 500,
    opacity: disabled ? 0.4 : 1, transition: 'background 0.15s',
  };
}

function shotCard(dragging: boolean, over: boolean): React.CSSProperties {
  return {
    flexShrink: 0, width: 220, height: 155,
    background: theme.bg.card,
    border: `1.5px solid ${over ? theme.border.accent : dragging ? theme.border.dashed : theme.border.card}`,
    borderRadius: theme.radius.md, padding: '8px 10px',
    display: 'flex', flexDirection: 'column', gap: 5,
    cursor: 'grab', opacity: dragging ? 0.5 : 1,
    transition: 'border-color 0.2s, opacity 0.2s', position: 'relative', overflow: 'visible',
  };
}

const cardHeader: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
};

const statusDot: React.CSSProperties = {
  width: 22, height: 22, borderRadius: '50%',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  fontSize: 10, fontWeight: 700, color: theme.bg.root, flexShrink: 0,
};

const thumbBox: React.CSSProperties = {
  width: 52, height: 52, borderRadius: 6,
  background: theme.bg.input, flexShrink: 0,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  overflow: 'hidden',
};

const promptBox: React.CSSProperties = {
  fontSize: 10, color: theme.text.primary, lineHeight: 1.4,
  overflow: 'hidden', display: '-webkit-box',
  WebkitLineClamp: 3, WebkitBoxOrient: 'vertical' as any, flex: 1,
};

const cardFooter: React.CSSProperties = {
  display: 'flex', justifyContent: 'flex-start', alignItems: 'center', gap: 6,
  fontSize: 10, color: theme.text.muted, flexShrink: 0,
};

const miniBtn: React.CSSProperties = {
  padding: '1px 6px', borderRadius: 3, border: `1px solid ${theme.border.subtle}`,
  background: 'transparent', color: theme.text.secondary, fontSize: 10,
  cursor: 'pointer',
};

const pickerStyle: React.CSSProperties = {
  position: 'absolute', bottom: '100%', left: 8,
  width: 200, background: theme.bg.surface,
  border: `1px solid ${theme.border.default}`, borderRadius: 8,
  padding: 6, zIndex: 200, boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
  marginBottom: 4,
};

const miniTab: React.CSSProperties = {
  flex: 1, padding: '2px 4px', borderRadius: 3, border: 'none',
  fontSize: 10, fontWeight: 600, cursor: 'pointer',
};

const fieldStyle: React.CSSProperties = {
  width: '100%', padding: '3px 6px', borderRadius: 4,
  border: `1px solid ${theme.border.card}`, background: theme.bg.card,
  color: theme.text.primary, fontSize: 10, outline: 'none',
  boxSizing: 'border-box' as const,
};

function entityRow(bound: boolean): React.CSSProperties {
  return {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '3px 6px', cursor: 'pointer', borderRadius: 4, fontSize: 11,
    background: bound ? `${theme.accent.blue}10` : 'transparent',
    color: theme.text.primary,
  };
}

const arrowStyle: React.CSSProperties = {
  position: 'absolute', right: -12, top: '40px',
  color: theme.text.muted, fontSize: 14, zIndex: 1,
};
