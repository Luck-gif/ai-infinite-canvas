// 无限画布 · v4.39 视频时间轴面板 - 拖拽排序 + 多段拼接
import React, { useCallback, useRef, useState } from 'react';
import { useCanvasStore } from './store';
import { concatVideos, imageUrl } from './api';
import { theme } from './theme';

const TIMELINE_HEIGHT = 136;
const HEADER_H = 34;
const TRACK_H = TIMELINE_HEIGHT - HEADER_H;

const styles = {
  wrapper: {
    position: 'fixed' as const,
    bottom: 0, left: 0, right: 0,
    height: TIMELINE_HEIGHT,
    background: theme.bg.panel,
    borderTop: `1px solid ${theme.border.default}`,
    zIndex: 60,
    display: 'flex',
    flexDirection: 'column' as const,
    boxShadow: '0 -4px 24px rgba(0,0,0,0.5)',
  },
  header: {
    height: HEADER_H,
    display: 'flex',
    alignItems: 'center',
    padding: '0 12px',
    gap: 8,
    borderBottom: `1px solid ${theme.border.subtle}`,
    background: theme.bg.header,
    minHeight: HEADER_H,
    flexShrink: 0,
  },
  title: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.text.primary,
    letterSpacing: '0.3px',
  },
  count: {
    fontSize: 11,
    color: theme.text.muted,
    marginLeft: 4,
  },
  spacer: { flex: 1 },
  btn: {
    height: 22,
    padding: '0 10px',
    fontSize: 11,
    fontWeight: 500,
    borderRadius: 5,
    border: 'none',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    transition: 'all 0.15s',
  },
  track: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '0 12px',
    overflowX: 'auto' as const,
    overflowY: 'hidden' as const,
    minHeight: 0,
    scrollbarWidth: 'thin' as const,
  },
  clip: {
    minWidth: 140,
    width: 140,
    height: TRACK_H - 18,
    background: theme.bg.card,
    borderRadius: 7,
    border: `1px solid ${theme.border.card}`,
    cursor: 'grab',
    display: 'flex',
    flexDirection: 'column' as const,
    flexShrink: 0,
    position: 'relative' as const,
    overflow: 'hidden',
    transition: 'border-color 0.15s, box-shadow 0.15s',
  },
  clipDrag: {
    minWidth: 140,
    width: 140,
    height: TRACK_H - 18,
    background: theme.bg.card,
    borderRadius: 7,
    border: `1px solid ${theme.border.accent}`,
    cursor: 'grabbing',
    display: 'flex',
    flexDirection: 'column' as const,
    flexShrink: 0,
    position: 'relative' as const,
    overflow: 'hidden',
    boxShadow: `0 0 0 2px ${theme.accent.blue}40`,
    transition: 'border-color 0.15s, box-shadow 0.15s',
  },
  clipPreview: {
    flex: '1 1 auto',
    background: '#1a2233',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 10,
    color: theme.text.hint,
    minHeight: 0,
    overflow: 'hidden',
  },
  clipInfo: {
    flex: '0 0 auto',
    padding: '2px 7px 3px',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    fontSize: 10,
    color: theme.text.muted,
    borderTop: `1px solid ${theme.border.subtle}`,
    background: 'rgba(0,0,0,0.15)',
    lineHeight: '14px',
  },
  clipIndex: {
    position: 'absolute' as const,
    top: 2, left: 5,
    fontSize: 9,
    fontWeight: 700,
    color: theme.accent.blue,
    background: 'rgba(0,0,0,0.6)',
    padding: '0 4px',
    borderRadius: 3,
    lineHeight: '16px',
  },
  removeBtn: {
    position: 'absolute' as const,
    top: 2, right: 2,
    width: 16,
    height: 16,
    borderRadius: 4,
    border: 'none',
    background: 'rgba(0,0,0,0.45)',
    color: theme.text.muted,
    fontSize: 12,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    lineHeight: '16px',
    padding: 0,
  },
  empty: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: theme.text.hint,
    fontSize: 12,
    gap: 6,
  },
  dropIndicator: {
    minWidth: 2,
    width: 2,
    height: TRACK_H - 24,
    background: theme.accent.blue,
    borderRadius: 1,
    flexShrink: 0,
    alignSelf: 'center',
  },
};

const Timeline: React.FC = () => {
  const clips = useCanvasStore((s) => s.timelineClips);
  const setClips = useCanvasStore((s) => s.reorderTimeline);
  const removeClip = useCanvasStore((s) => s.removeFromTimeline);
  const clearTimeline = useCanvasStore((s) => s.clearTimeline);

  const [concatting, setConcatting] = useState(false);
  const [concatMsg, setConcatMsg] = useState('');
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);
  const trackRef = useRef<HTMLDivElement>(null);

  const handleConcat = useCallback(async () => {
    if (clips.length < 2) {
      setConcatMsg('至少需要2个视频片段才能拼接');
      return;
    }
    setConcatting(true);
    setConcatMsg('');
    try {
      const res = await concatVideos({
        video_names: clips.map((c) => c.filename),
      });
      if (res.validated && res.filename) {
        setConcatMsg(`拼接完成：${res.filename}`);
      } else {
        setConcatMsg(`拼接失败：${res.issues.join('；')}`);
      }
    } catch (e: any) {
      setConcatMsg(`网络错误：${e.message}`);
    } finally {
      setConcatting(false);
    }
  }, [clips]);

  const handleDragStart = useCallback((e: React.DragEvent, idx: number) => {
    setDragIdx(idx);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(idx));
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, idx: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDropIdx(idx);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDropIdx(null);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent, toIdx: number) => {
    e.preventDefault();
    setDropIdx(null);
    if (dragIdx === null || dragIdx === toIdx) {
      setDragIdx(null);
      return;
    }
    const next = [...clips];
    const [moved] = next.splice(dragIdx, 1);
    next.splice(toIdx, 0, moved);
    setClips(next);
    setDragIdx(null);
  }, [clips, dragIdx, setClips]);

  const handleDragEnd = useCallback(() => {
    setDragIdx(null);
    setDropIdx(null);
  }, []);

  // 空状态
  if (clips.length === 0) {
    return (
      <div style={styles.wrapper}>
        <div style={styles.header}>
          <span style={styles.title}>⚡ 视频时间轴</span>
          <span style={styles.count}>— 空</span>
          <div style={styles.spacer} />
        </div>
        <div style={styles.track}>
          <div style={styles.empty}>
            <span style={{ opacity: 0.7 }}>📼</span>
            在控制面板中将视频节点「添加到时间轴」以开始编排
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.wrapper}>
      {/* Header */}
      <div style={styles.header}>
        <span style={styles.title}>⚡ 视频时间轴</span>
        <span style={styles.count}>
          {clips.length} 段 · 共{' '}
          {clips.reduce((s, c) => s + (c.fps > 0 ? c.frames / c.fps : 0), 0).toFixed(1)}s
        </span>
        <div style={styles.spacer} />

        <button
          style={{
            ...styles.btn,
            background: '#1a3a2a',
            color: theme.accent.emerald,
          }}
          onClick={handleConcat}
          disabled={concatting || clips.length < 2}
        >
          {concatting ? '拼接中...' : '🎬 拼接导出'}
        </button>

        <button
          style={{
            ...styles.btn,
            background: theme.danger.bg,
            color: theme.danger.text,
          }}
          onClick={clearTimeline}
        >
          🗑 清空
        </button>
      </div>

      {concatMsg && (
        <div style={{
          padding: '2px 12px 0',
          fontSize: 11,
          color: concatMsg.includes('失败') || concatMsg.includes('错误')
            ? theme.danger.text : theme.accent.emerald,
          background: theme.bg.panel,
        }}>
          {concatMsg}
        </div>
      )}

      {/* Track */}
      <div ref={trackRef} style={styles.track}>
        {clips.map((clip, idx) => {
          const isDrag = dragIdx === idx;
          const showIndicator = dropIdx === idx && dragIdx !== null && dragIdx !== idx;
          return (
            <React.Fragment key={clip.nodeId}>
              {/* Drop indicator before clip */}
              {showIndicator && dropIdx! <= idx && <div style={styles.dropIndicator} />}

              <div
                draggable
                style={isDrag ? styles.clipDrag : styles.clip}
                onDragStart={(e) => handleDragStart(e, idx)}
                onDragOver={(e) => handleDragOver(e, idx)}
                onDragLeave={handleDragLeave}
                onDrop={(e) => handleDrop(e, idx)}
                onDragEnd={handleDragEnd}
                title={clip.prompt}
              >
                {/* Index badge */}
                <span style={styles.clipIndex}>{idx + 1}</span>

                {/* Remove button */}
                <button
                  style={styles.removeBtn}
                  onClick={(e) => { e.stopPropagation(); removeClip(clip.nodeId); }}
                  title="从时间轴移除"
                >
                  ✕
                </button>

                {/* Preview area */}
                <div style={styles.clipPreview}>
                  {clip.filename.endsWith('.mp4') || clip.filename.endsWith('.webm') ? (
                    <span style={{ fontSize: 18, opacity: 0.6 }}>🎞️</span>
                  ) : (
                    <img
                      src={imageUrl(clip.filename)}
                      alt=""
                      style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'cover',
                        opacity: 0.8,
                      }}
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  )}
                </div>

                {/* Info bar */}
                <div style={styles.clipInfo}>
                  <span style={{
                    maxWidth: 70,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {clip.filename}
                  </span>
                  <span>{clip.frames}fr {clip.fps}fps</span>
                </div>
              </div>

              {/* Drop indicator after last clip */}
              {showIndicator && dropIdx! > idx && <div style={styles.dropIndicator} />}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};

export default Timeline;
