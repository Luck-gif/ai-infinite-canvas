import ReactDOM from 'react-dom/client';
import { App } from './App';
import { ErrorBoundary } from './ErrorBoundary';

// 不使用 StrictMode：react-konva 在 dev 双挂载下会重复创建/销毁 Konva Stage，
// 在内嵌 WebView 中易触发画布测量崩溃。ErrorBoundary 兜底隔离渲染错误。
ReactDOM.createRoot(document.getElementById('root')!).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
