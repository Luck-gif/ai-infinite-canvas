import React from 'react';

interface State {
  error: Error | null;
}

// 顶层错误隔离：避免单个渲染错误（如内嵌 WebView 下 Konva 画布测量异常）
// 冲掉整棵 React 树导致白屏。出错时显示可读信息并提供重试。
export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (error) {
      return (
        <div
          style={{
            padding: 24,
            color: '#ff9b9b',
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap',
            lineHeight: 1.6,
          }}
        >
          <h3 style={{ marginTop: 0 }}>渲染出错（已隔离，未白屏）</h3>
          <div>{String(error?.message || error)}</div>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              marginTop: 12,
              padding: '6px 12px',
              borderRadius: 6,
              border: '1px solid #232c3d',
              background: '#11161f',
              color: '#cfd8e3',
              cursor: 'pointer',
            }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
