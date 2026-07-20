// v4.50 三层画布面板：策划层 / 生成层 / 输出层 切换
// 紧凑水平标签，集成到画布底部
import { useCanvasStore } from './store';
import type { CanvasLayerKind } from './types';
import { theme } from './theme';

const LAYER_COLORS: Record<CanvasLayerKind, string> = {
  planning: '#f0a030',
  generation: '#4f8cff',
  output: '#44cc66',
};

export function LayerPanel() {
  const activeLayer = useCanvasStore((s) => s.activeLayer);
  const layers = useCanvasStore((s) => s.layers);
  const setActiveLayer = useCanvasStore((s) => s.setActiveLayer);
  const toggleLayerVisibility = useCanvasStore((s) => s.toggleLayerVisibility);
  const toggleLayerLock = useCanvasStore((s) => s.toggleLayerLock);

  return (
    <div
      style={{
        position: 'absolute',
        bottom: 16,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 900,
        display: 'flex',
        gap: 0,
        background: theme.bg.surface,
        border: `1px solid ${theme.border.default}`,
        borderRadius: 10,
        boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
        overflow: 'hidden',
        userSelect: 'none',
        backdropFilter: 'blur(8px)',
      }}
    >
      {layers.map((layer) => {
        const isActive = activeLayer === layer.kind;
        const color = LAYER_COLORS[layer.kind];
        return (
          <div
            key={layer.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 16px',
              cursor: 'pointer',
              background: isActive ? `${color}20` : 'transparent',
              borderBottom: isActive ? `2px solid ${color}` : '2px solid transparent',
              borderRight: layer.order < 2 ? `1px solid ${theme.border.subtle}` : 'none',
              transition: 'background 0.15s, border-color 0.15s',
              position: 'relative',
            }}
            onClick={() => setActiveLayer(layer.kind)}
            title={layer.description}
          >
            {/* 图标 */}
            <span style={{
              width: 8, height: 8,
              borderRadius: '50%',
              background: isActive ? color : theme.text.hint,
              flexShrink: 0,
            }} />

            {/* 名称 */}
            <span style={{
              fontSize: 12,
              fontWeight: isActive ? 600 : 400,
              color: isActive ? theme.text.primary : theme.text.label,
              whiteSpace: 'nowrap',
            }}>
              {layer.name}
            </span>

            {/* 可见性切换 */}
            <span
              style={{
                fontSize: 12,
                color: layer.visible ? color : theme.text.hint,
                cursor: 'pointer',
                opacity: layer.visible ? 1 : 0.4,
              }}
              onClick={(e) => {
                e.stopPropagation();
                toggleLayerVisibility(layer.id);
              }}
              title={layer.visible ? '隐藏' : '显示'}
            >
              {layer.visible ? '👁' : '─'}
            </span>

            {/* 锁定切换 */}
            <span
              style={{
                fontSize: 11,
                color: layer.locked ? theme.accent.amber : theme.text.hint,
                cursor: 'pointer',
                opacity: layer.locked ? 1 : 0.3,
              }}
              onClick={(e) => {
                e.stopPropagation();
                toggleLayerLock(layer.id);
              }}
              title={layer.locked ? '已锁定' : '未锁定'}
            >
              {layer.locked ? '🔒' : '🔓'}
            </span>
          </div>
        );
      })}
    </div>
  );
}
