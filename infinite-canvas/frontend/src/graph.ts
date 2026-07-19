// 纯函数图计算：血缘边（computeEdges）与手动关联边（computeLinks）
// 抽离到无 React 依赖的模块，便于复用与单元测试（v4.19 / v4.20）。
import type { CanvasNode, Link } from './types';

export interface Edge {
  id: string;
  from: CanvasNode; // 派生来源（parentId 指向的节点）
  to: CanvasNode;   // 派生节点
}

/** 由 parentId 推导血缘边（源 → 派生）；父子任一缺失则忽略（v4.19） */
export function computeEdges(nodes: CanvasNode[]): Edge[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges: Edge[] = [];
  for (const n of nodes) {
    if (n.parentId && byId.has(n.parentId) && n.parentId !== n.id) {
      edges.push({ id: `e-${n.parentId}-${n.id}`, from: byId.get(n.parentId)!, to: n });
    }
  }
  return edges;
}

export interface LinkEdge {
  id: string;
  from: CanvasNode;
  to: CanvasNode;
}

/** 由 links 推导手动关联边（源 → 目标）；端点缺失则忽略（v4.20） */
export function computeLinks(nodes: CanvasNode[], links: Link[]): LinkEdge[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges: LinkEdge[] = [];
  for (const l of links) {
    const a = byId.get(l.from);
    const b = byId.get(l.to);
    if (a && b) edges.push({ id: l.id, from: a, to: b });
  }
  return edges;
}
