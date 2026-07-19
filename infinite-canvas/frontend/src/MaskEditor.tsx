import React, { useCallback, useEffect, useRef, useState } from 'react';
import { theme } from './theme';

/**
 * 蒙版编辑器（§6.1.4 局部重绘）。
 *
 * 在底图上用画笔涂抹「待重绘」区域，导出与底图同尺寸的 **黑底白区 PNG**
 * （白=1.0=重绘，供后端 LoadImageMask + VAEEncodeForInpaint 使用）。
 *
 * - imageUrl：底图（同源 /api/image URL）。
 * - onConfirm：回调返回 mask 的 dataURL（image/png）。
 * - onCancel：关闭。
 */
export function MaskEditor({
  imageUrl,
  onConfirm,
  onCancel,
}: {
  imageUrl: string;
  onConfirm: (maskDataUrl: string) => void;
  onCancel: () => void;
}) {
  const baseRef = useRef<HTMLCanvasElement>(null);   // 底图（展示）
  const maskRef = useRef<HTMLCanvasElement>(null);   // 蒙版（白色笔迹，透明底）
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 512, h: 512 });   // 原图像素尺寸
  const [display, setDisplay] = useState({ w: 512, h: 512 }); // 展示尺寸
  const [brush, setBrush] = useState(48);
  const [ready, setReady] = useState(false);
  const drawing = useRef(false);
  const last = useRef<{ x: number; y: number } | null>(null);
  const hasStroke = useRef(false);

  // 载入底图，按视口自适应展示尺寸（画布内部仍用原图像素坐标）
  useEffect(() => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      const w = img.naturalWidth || 512;
      const h = img.naturalHeight || 512;
      setSize({ w, h });
      const maxW = Math.min(window.innerWidth * 0.8, 900);
      const maxH = window.innerHeight * 0.62;
      const scale = Math.min(maxW / w, maxH / h, 1);
      setDisplay({ w: Math.round(w * scale), h: Math.round(h * scale) });
      const base = baseRef.current;
      if (base) {
        base.width = w;
        base.height = h;
        const ctx = base.getContext('2d');
        if (ctx) ctx.drawImage(img, 0, 0, w, h);
      }
      const mask = maskRef.current;
      if (mask) {
        mask.width = w;
        mask.height = h;
      }
      setReady(true);
    };
    img.onerror = () => setReady(true);
    img.src = imageUrl;
  }, [imageUrl]);

  // 展示坐标 → 原图像素坐标
  const toImgCoord = useCallback(
    (clientX: number, clientY: number) => {
      const el = maskRef.current;
      if (!el) return { x: 0, y: 0 };
      const rect = el.getBoundingClientRect();
      const x = ((clientX - rect.left) / rect.width) * size.w;
      const y = ((clientY - rect.top) / rect.height) * size.h;
      return { x, y };
    },
    [size.w, size.h],
  );

  const paint = useCallback(
    (x: number, y: number) => {
      const ctx = maskRef.current?.getContext('2d');
      if (!ctx) return;
      ctx.fillStyle = 'rgba(255,255,255,1)';
      ctx.strokeStyle = 'rgba(255,255,255,1)';
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.lineWidth = brush;
      if (last.current) {
        ctx.beginPath();
        ctx.moveTo(last.current.x, last.current.y);
        ctx.lineTo(x, y);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(x, y, brush / 2, 0, Math.PI * 2);
      ctx.fill();
      last.current = { x, y };
      hasStroke.current = true;
    },
    [brush],
  );

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    drawing.current = true;
    last.current = null;
    const { x, y } = toImgCoord(e.clientX, e.clientY);
    paint(x, y);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drawing.current) return;
    const { x, y } = toImgCoord(e.clientX, e.clientY);
    paint(x, y);
  };
  const endStroke = () => {
    drawing.current = false;
    last.current = null;
  };

  const clearMask = () => {
    const ctx = maskRef.current?.getContext('2d');
    if (ctx && maskRef.current) {
      ctx.clearRect(0, 0, maskRef.current.width, maskRef.current.height);
      hasStroke.current = false;
    }
  };

  const confirm = () => {
    if (!hasStroke.current) {
      alert('请先用画笔涂抹要重绘的区域');
      return;
    }
    // 合成黑底 + 白色笔迹 → 导出 PNG（red 通道即为 mask）
    const out = document.createElement('canvas');
    out.width = size.w;
    out.height = size.h;
    const ctx = out.getContext('2d');
    if (!ctx || !maskRef.current) return;
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, size.w, size.h);
    ctx.drawImage(maskRef.current, 0, 0);
    onConfirm(out.toDataURL('image/png'));
  };

  return (
    <div style={overlayStyle} onPointerUp={endStroke}>
      <div style={panelStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
          <strong style={{ color: theme.text.white, fontSize: 15 }}>局部重绘 · 涂抹蒙版</strong>
          <span style={{ color: theme.text.slate, fontSize: 12 }}>白色区域将被重绘</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: theme.accent.ice, fontSize: 12 }}>笔刷 {brush}px</span>
            <input
              type="range" min={8} max={160} step={2} value={brush}
              onChange={(e) => setBrush(Number(e.target.value))}
              style={{ width: 130 }}
            />
          </div>
        </div>

        <div
          ref={wrapRef}
          style={{
            position: 'relative', width: display.w, height: display.h,
            margin: '0 auto', borderRadius: 8, overflow: 'hidden',
            background: theme.bg.deep, touchAction: 'none',
          }}
        >
          <canvas
            ref={baseRef}
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
          />
          <canvas
            ref={maskRef}
            data-testid="mask-canvas"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            style={{
              position: 'absolute', inset: 0, width: '100%', height: '100%',
              opacity: 0.5, cursor: 'crosshair',
            }}
          />
          {!ready && (
            <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: theme.text.slate }}>
              载入底图…
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 12, justifyContent: 'flex-end' }}>
          <button style={btnGhost} onClick={clearMask}>清除涂抹</button>
          <button style={btnGhost} onClick={onCancel}>取消</button>
          <button style={btnPrimary} data-testid="mask-confirm" onClick={confirm}>确认蒙版</button>
        </div>
      </div>
    </div>
  );
}

const overlayStyle: React.CSSProperties = {
  position: 'fixed', inset: 0, background: theme.bg.backdrop,
  display: 'grid', placeItems: 'center', zIndex: 1000,
};
const panelStyle: React.CSSProperties = {
  background: theme.bg.modal, border: `1px solid ${theme.border.modal}`, borderRadius: 12,
  padding: 16, boxShadow: '0 12px 40px rgba(0,0,0,0.5)', maxWidth: '90vw',
};
const btnGhost: React.CSSProperties = {
  padding: '8px 16px', borderRadius: 7, border: `1px solid ${theme.border.ghost}`,
  background: theme.bg.input, color: theme.accent.ice, fontSize: 13, cursor: 'pointer',
};
const btnPrimary: React.CSSProperties = {
  padding: '8px 18px', borderRadius: 7, border: 'none',
  background: theme.accent.sky, color: '#fff', fontSize: 13, cursor: 'pointer', fontWeight: 600,
};
