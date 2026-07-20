// 无限画布 v4.57 · 故事板时间轴（拖拽排序 + 批量生成 + 状态追踪）
import React, { useState, useCallback, useRef } from 'react';
import { useCanvasStore } from './store';
import { batchGenerateStoryboard } from './api';
import { theme } from './theme';
import type { ShotStatus } from './types';

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
  generating: '生成中',
  done: '已完成',
  failed: '失败',
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
  } = useCanvasStore();

  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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
      setErrorMsg('所有分镜已生成或正在生成中');
      return;
    }

    setStoryboardBatchBusy(true);
    setErrorMsg(null);

    // Mark all idle/failed shots as pending
    idleShots.forEach((s) => updateShotStatus(s.nodeId, 'pending'));

    try {
      const prompts = idleShots.map((s) => s.prompt);

      // Mark as generating one by one as we submit (simplified: mark all)
      idleShots.forEach((s) => updateShotStatus(s.nodeId, 'generating'));

      const result = await batchGenerateStoryboard(
        { prompts, width: 1024, height: 1024, steps: 20, cfg: 7.0, seed: 42 + idleShots[0].shotIndex },
        (_done, _total) => {
          // Progress updates handled by per-frame results
        },
      );

      // Map results back to shots
      result.frames.forEach((frame) => {
        const shot = idleShots.find((s) => s.shotIndex === frame.index + 1) ?? idleShots[frame.index];
        if (shot) {
          if (frame.status === 'done' && frame.image) {
            updateShotStatus(shot.nodeId, 'done', frame.image);
          } else if (frame.status === 'failed') {
            updateShotStatus(shot.nodeId, 'failed');
          }
        }
      });

      // Any remaining pending/generating shots that didn't get results → mark failed
      const updated = useCanvasStore.getState().storyboardShots;
      updated.forEach((s) => {
        if (s.status === 'pending' || s.status === 'generating') {
          updateShotStatus(s.nodeId, 'failed');
        }
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '批量生成失败';
      setErrorMsg(msg);
      // Mark all pending/generating as failed
      useCanvasStore.getState().storyboardShots.forEach((s) => {
        if (s.status === 'pending' || s.status === 'generating') {
          updateShotStatus(s.nodeId, 'failed');
        }
      });
    } finally {
      setStoryboardBatchBusy(false);
      // Re-sync to reflect latest statuses
      syncStoryboardFromCanvas();
    }
  }, [setStoryboardBatchBusy, updateShotStatus, syncStoryboardFromCanvas]);

  // Simple drag-to-reorder
  const handleDragStart = useCallback((index: number) => {
    setDragIndex(index);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault();
    setOverIndex(index);
  }, []);

  const handleDragLeave = useCallback(() => {
    setOverIndex(null);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent, toIndex: number) => {
      e.preventDefault();
      if (dragIndex !== null && dragIndex !== toIndex) {
        reorderShots(dragIndex, toIndex);
      }
      setDragIndex(null);
      setOverIndex(null);
    },
    [dragIndex, reorderShots],
  );

  const handleDragEnd = useCallback(() => {
    setDragIndex(null);
    setOverIndex(null);
  }, []);

  // Horizontal scroll by mouse wheel
  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft += e.deltaY;
    }
  }, []);

  const doneCount = storyboardShots.filter((s) => s.status === 'done').length;
  const totalCount = storyboardShots.length;
  const hasShots = totalCount > 0;

  return (
    <div style={{
      position: 'fixed',
      bottom: 0,
      left: 0,
      right: 0,
      height: 200,
      background: theme.bg.panel,
      borderTop: `1px solid ${theme.border.default}`,
      zIndex: 100,
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Header bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '6px 16px',
        borderBottom: `1px solid ${theme.border.subtle}`,
        background: theme.bg.header,
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ color: theme.text.primary, fontWeight: 600, fontSize: 13 }}>
            🎬 故事板时间轴
          </span>
          {hasShots && (
            <span style={{
              fontSize: 11,
              color: theme.text.muted,
              background: theme.bg.input,
              borderRadius: 4,
              padding: '1px 8px',
            }}>
              {doneCount}/{totalCount} 已完成
            </span>
          )}
          {storyboardBatchBusy && (
            <span style={{
              fontSize: 11,
              color: theme.accent.blue,
              background: theme.bg.hover,
              borderRadius: 4,
              padding: '1px 8px',
              animation: 'pulse 1.5s infinite',
            }}>
              ⏳ 批量生成中...
            </span>
          )}
          {errorMsg && (
            <span style={{ fontSize: 11, color: theme.accent.danger, background: theme.danger.bg, borderRadius: 4, padding: '1px 8px' }}>
              {errorMsg}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={handleSync}
            title="从画布同步 storyboard 节点"
            style={actionBtnStyle('sync')}
          >
            🔄 同步画布
          </button>
          <button
            disabled={!hasShots || storyboardBatchBusy}
            onClick={handleBatchGenerate}
            title="批量生成所有待处理分镜"
            style={actionBtnStyle('generate', !hasShots || storyboardBatchBusy)}
          >
            ⚡ 批量生成
          </button>
          <button
            onClick={() => setStoryboardTimelineOpen(false)}
            title="关闭时间轴"
            style={actionBtnStyle('close')}
          >
            ✕
          </button>
        </div>
      </div>

      {/* Scrollable shot row */}
      <div
        ref={scrollRef}
        onWheel={handleWheel}
        style={{
          flex: 1,
          overflowX: 'auto',
          overflowY: 'hidden',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 16px',
          scrollBehavior: 'smooth',
        }}
      >
        {!hasShots && (
          <div style={{
            width: '100%',
            textAlign: 'center',
            color: theme.text.muted,
            fontSize: 13,
            padding: '36px 0',
          }}>
            <p style={{ margin: '0 0 8px' }}>暂无分镜数据</p>
            <p style={{ margin: 0, fontSize: 11, color: theme.text.hint }}>
              请在 <strong>StoryboardPanel</strong> 中规划分镜并「加载到画布」，
              然后点击「🔄 同步画布」同步到时间轴
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
              style={{
                flexShrink: 0,
                width: 200,
                height: 130,
                background: theme.bg.card,
                border: `1.5px solid ${isOver ? theme.border.accent : isDragging ? theme.border.dashed : theme.border.card}`,
                borderRadius: theme.radius.md,
                padding: '10px 12px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                cursor: 'grab',
                opacity: isDragging ? 0.5 : 1,
                transition: 'border-color 0.2s, opacity 0.2s',
                position: 'relative',
                overflow: 'hidden',
              }}
            >
              {/* Shot index badge */}
              <div style={{
                position: 'absolute',
                top: 6,
                right: 6,
                width: 24,
                height: 24,
                borderRadius: '50%',
                background: statusColor,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 11,
                fontWeight: 700,
                color: theme.bg.root,
              }}>
                {shot.shotIndex}
              </div>

              {/* Status label */}
              <div style={{
                fontSize: 10,
                fontWeight: 600,
                color: statusColor,
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
              }}>
                {STATUS_LABELS[shot.status]}
              </div>

              {/* Prompt preview */}
              <div style={{
                fontSize: 11,
                color: theme.text.primary,
                lineHeight: 1.4,
                overflow: 'hidden',
                display: '-webkit-box',
                WebkitLineClamp: 3,
                WebkitBoxOrient: 'vertical' as any,
                flex: 1,
              }}>
                {shot.prompt || '(无提示词)'}
              </div>

              {/* Bottom row: duration + asset count */}
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                fontSize: 10,
                color: theme.text.muted,
              }}>
                <span>{shot.duration ? `${shot.duration}s` : '--'}</span>
                {shot.referenceAssets.length > 0 && (
                  <span title="绑定的实体资产">
                    🔗 {shot.referenceAssets.length}
                  </span>
                )}
                {shot.generatedImage && (
                  <span title={shot.generatedImage} style={{ color: theme.accent.green }}>
                    📷
                  </span>
                )}
              </div>

              {/* Connecting arrow between shots */}
              {i < storyboardShots.length - 1 && (
                <div style={{
                  position: 'absolute',
                  right: -12,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: theme.text.muted,
                  fontSize: 12,
                  zIndex: 1,
                }}>
                  →
                </div>
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

// Shared button style helper
function actionBtnStyle(variant: 'sync' | 'generate' | 'close', disabled = false): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: '4px 12px',
    borderRadius: 6,
    border: `1px solid ${theme.border.subtle}`,
    background: theme.bg.input,
    color: theme.text.primary,
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontSize: 12,
    fontWeight: 500,
    opacity: disabled ? 0.4 : 1,
    transition: 'background 0.15s, border-color 0.15s',
  };

  if (variant === 'generate') {
    base.background = theme.accent.blue;
    base.color = '#fff';
    base.border = `1px solid ${theme.accent.blue}`;
  }

  return base;
}
