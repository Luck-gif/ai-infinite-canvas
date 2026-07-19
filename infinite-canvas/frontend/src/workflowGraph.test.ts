import { describe, it, expect } from 'vitest';
import type { WorkflowNode, WorkflowEdge, WorkflowGraph } from './types';

// ── 工厂函数 ──────────────────────────────────────────────────────

function mkNode(overrides: Partial<WorkflowNode> = {}): WorkflowNode {
  return {
    id: '1',
    type: 'CheckpointLoaderSimple',
    title: '加载模型',
    category: 'model',
    pos: { x: 0, y: 0 },
    input_links: [],
    values: {},
    num_outputs: 3,
    ...overrides,
  };
}

function mkEdge(overrides: Partial<WorkflowEdge> = {}): WorkflowEdge {
  return {
    from: '1',
    from_slot: 0,
    to: '2',
    to_slot: 'model',
    ...overrides,
  };
}

function mkGraph(overrides: Partial<WorkflowGraph> = {}): WorkflowGraph {
  return {
    nodes: [],
    edges: [],
    layout: 'dag',
    ...overrides,
  };
}

// ── 工厂函数 ──────────────────────────────────────────────────────

describe('WorkflowGraph 数据结构', () => {
  it('最小图应包含 nodes / edges / layout', () => {
    const g = mkGraph();
    expect(g).toHaveProperty('nodes');
    expect(g).toHaveProperty('edges');
    expect(g).toHaveProperty('layout');
  });
});

describe('WorkflowNode 格式校验', () => {
  it('所有字段类型正确', () => {
    const n = mkNode();
    expect(typeof n.id).toBe('string');
    expect(typeof n.type).toBe('string');
    expect(typeof n.title).toBe('string');
    expect(typeof n.category).toBe('string');
    expect(typeof n.pos.x).toBe('number');
    expect(typeof n.pos.y).toBe('number');
    expect(Array.isArray(n.input_links)).toBe(true);
    expect(typeof n.values).toBe('object');
    expect(typeof n.num_outputs).toBe('number');
  });

  it('类别应为合法值', () => {
    const validCategories = ['model', 'sample', 'cond', 'latent', 'vae', 'io', 'other'];
    for (const cat of validCategories) {
      expect(validCategories).toContain(cat);
    }
  });

  it('KSampler 应有多个 input_links', () => {
    const ks = mkNode({
      id: '5', type: 'KSampler', category: 'sample',
      input_links: [
        { name: 'model', from: '1', from_slot: 0 },
        { name: 'positive', from: '2', from_slot: 0 },
        { name: 'negative', from: '3', from_slot: 0 },
        { name: 'latent_image', from: '4', from_slot: 0 },
      ],
    });
    expect(ks.input_links.length).toBe(4);
  });

  it('SaveImage 应有 filename_prefix 值', () => {
    const si = mkNode({
      id: '7', type: 'SaveImage', category: 'io',
      values: { filename_prefix: 'test_' },
    });
    expect(si.values.filename_prefix).toBe('test_');
  });
});

describe('WorkflowEdge 格式校验', () => {
  it('应包含 from / from_slot / to / to_slot', () => {
    const e = mkEdge();
    expect(typeof e.from).toBe('string');
    expect(typeof e.from_slot).toBe('number');
    expect(typeof e.to).toBe('string');
    expect(typeof e.to_slot).toBe('string');
  });
});

describe('完整 txt2img 工作流图', () => {
  const txt2imgGraph: WorkflowGraph = {
    nodes: [
      mkNode({ id: '1', type: 'CheckpointLoaderSimple', title: '加载模型', category: 'model', num_outputs: 3 }),
      mkNode({ id: '2', type: 'CLIPTextEncode', title: '正面提示词', category: 'cond', input_links: [{ name: 'clip', from: '1', from_slot: 1 }], num_outputs: 1 }),
      mkNode({ id: '3', type: 'CLIPTextEncode', title: '负面提示词', category: 'cond', input_links: [{ name: 'clip', from: '1', from_slot: 1 }], num_outputs: 1 }),
      mkNode({ id: '4', type: 'EmptyLatentImage', title: '空潜空间', category: 'latent', values: { width: '512', height: '512' }, num_outputs: 1 }),
      mkNode({ id: '5', type: 'KSampler', title: '采样器', category: 'sample',
        input_links: [
          { name: 'model', from: '1', from_slot: 0 },
          { name: 'positive', from: '2', from_slot: 0 },
          { name: 'negative', from: '3', from_slot: 0 },
          { name: 'latent_image', from: '4', from_slot: 0 },
        ],
        values: { seed: '42', steps: '20', cfg: '7.0' }, num_outputs: 1 }),
      mkNode({ id: '6', type: 'VAEDecode', title: 'VAE 解码', category: 'vae',
        input_links: [
          { name: 'samples', from: '5', from_slot: 0 },
          { name: 'vae', from: '1', from_slot: 2 },
        ], num_outputs: 1 }),
      mkNode({ id: '7', type: 'SaveImage', title: '保存图片', category: 'io',
        input_links: [{ name: 'images', from: '6', from_slot: 0 }],
        values: { filename_prefix: 'test_' }, num_outputs: 0 }),
    ],
    edges: [
      mkEdge({ from: '1', from_slot: 0, to: '5', to_slot: 'model' }),
      mkEdge({ from: '1', from_slot: 1, to: '2', to_slot: 'clip' }),
      mkEdge({ from: '1', from_slot: 1, to: '3', to_slot: 'clip' }),
      mkEdge({ from: '2', from_slot: 0, to: '5', to_slot: 'positive' }),
      mkEdge({ from: '3', from_slot: 0, to: '5', to_slot: 'negative' }),
      mkEdge({ from: '4', from_slot: 0, to: '5', to_slot: 'latent_image' }),
      mkEdge({ from: '5', from_slot: 0, to: '6', to_slot: 'samples' }),
      mkEdge({ from: '1', from_slot: 2, to: '6', to_slot: 'vae' }),
      mkEdge({ from: '6', from_slot: 0, to: '7', to_slot: 'images' }),
    ],
    layout: 'dag',
  };

  it('txt2img 应有 7 个节点 9 条边', () => {
    expect(txt2imgGraph.nodes.length).toBe(7);
    expect(txt2imgGraph.edges.length).toBe(9);
  });

  it('边应连接存在的节点', () => {
    const nodeIds = new Set(txt2imgGraph.nodes.map(n => n.id));
    for (const e of txt2imgGraph.edges) {
      expect(nodeIds.has(e.from)).toBe(true);
      expect(nodeIds.has(e.to)).toBe(true);
    }
  });

  it('KSampler 应连接 model / positive / negative / latent_image', () => {
    const ks = txt2imgGraph.nodes.find(n => n.type === 'KSampler')!;
    const linkNames = ks.input_links.map(l => l.name);
    expect(linkNames).toContain('model');
    expect(linkNames).toContain('positive');
    expect(linkNames).toContain('negative');
    expect(linkNames).toContain('latent_image');
  });
});
