// 无限画布 · store 单元测试（vitest）：撤销/重做 + 序列化/反序列化（Phase 1 验收）
import { beforeEach, describe, expect, it } from 'vitest';
import { useCanvasStore, serializeNodes, deserializeNodes, deserializeLinks } from './store';
import type { CanvasNode } from './types';

function makeNode(id: string): CanvasNode {
  return {
    id,
    filename: `${id}.png`,
    prompt: 'test',
    templateId: 'txt2img_sdxl',
    x: 0,
    y: 0,
    width: 280,
    height: 280,
  };
}

beforeEach(() => {
  useCanvasStore.setState({ nodes: [], links: [], past: [], future: [], selectedId: null });
});

describe('serialize / deserialize', () => {
  it('round-trips node arrays', () => {
    const nodes = [makeNode('a'), makeNode('b')];
    const raw = serializeNodes(nodes);
    const back = deserializeNodes(raw);
    expect(back).toHaveLength(2);
    expect(back[0].filename).toBe('a.png');
  });

  it('returns [] for invalid JSON', () => {
    expect(deserializeNodes('not-json{')).toEqual([]);
  });

  it('filters malformed entries', () => {
    const raw = JSON.stringify({ nodes: [{ id: 'x', filename: 'x.png' }, { bad: 1 }, null] });
    const back = deserializeNodes(raw);
    expect(back).toHaveLength(1);
  });

  it('accepts bare array form', () => {
    const raw = JSON.stringify([makeNode('z')]);
    expect(deserializeNodes(raw)).toHaveLength(1);
  });
});

describe('store actions', () => {
  it('adds a node and selects it', () => {
    useCanvasStore.getState().addNode(makeNode('a'));
    const s = useCanvasStore.getState();
    expect(s.nodes).toHaveLength(1);
    expect(s.selectedId).toBe('a');
  });

  it('undo reverts last add, redo re-applies', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    st.addNode(makeNode('b'));
    expect(useCanvasStore.getState().nodes).toHaveLength(2);

    useCanvasStore.getState().undo();
    expect(useCanvasStore.getState().nodes).toHaveLength(1);

    useCanvasStore.getState().redo();
    expect(useCanvasStore.getState().nodes).toHaveLength(2);
  });

  it('removeNode deletes by id', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    st.addNode(makeNode('b'));
    useCanvasStore.getState().removeNode('a');
    const ids = useCanvasStore.getState().nodes.map((n) => n.id);
    expect(ids).toEqual(['b']);
  });

  it('commitMove updates position and is undoable', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    useCanvasStore.getState().commitMove('a', 111, 222);
    let node = useCanvasStore.getState().nodes[0];
    expect([node.x, node.y]).toEqual([111, 222]);

    useCanvasStore.getState().undo();
    node = useCanvasStore.getState().nodes[0];
    expect([node.x, node.y]).toEqual([0, 0]);
  });

  it('replaceAll swaps all nodes and is undoable', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    useCanvasStore.getState().replaceAll([makeNode('x'), makeNode('y')]);
    expect(useCanvasStore.getState().nodes.map((n) => n.id)).toEqual(['x', 'y']);

    useCanvasStore.getState().undo();
    expect(useCanvasStore.getState().nodes.map((n) => n.id)).toEqual(['a']);
  });

  it('clear empties the canvas but keeps history', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    useCanvasStore.getState().clear();
    expect(useCanvasStore.getState().nodes).toHaveLength(0);
    useCanvasStore.getState().undo();
    expect(useCanvasStore.getState().nodes).toHaveLength(1);
  });

  it('requestFocus sets pendingFocus with a nonce', () => {
    useCanvasStore.getState().requestFocus('abc');
    const f = useCanvasStore.getState().pendingFocus;
    expect(f).not.toBeNull();
    expect(f!.id).toBe('abc');
    expect(typeof f!.nonce).toBe('number');
  });
});

describe('node visualization metadata', () => {
  it('addNode preserves lineage + meta fields', () => {
    const n: CanvasNode = {
      ...makeNode('child'), id: 'child', parentId: 'parent', seed: 12345, createdAt: 1700000000000,
    };
    useCanvasStore.getState().addNode(n);
    const node = useCanvasStore.getState().nodes[0];
    expect(node.parentId).toBe('parent');
    expect(node.seed).toBe(12345);
    expect(node.createdAt).toBe(1700000000000);
  });

  it('deserialize keeps parentId/seed (lineage survives reload)', () => {
    const n: CanvasNode = {
      ...makeNode('c'), id: 'c', parentId: 'p', seed: 7,
    };
    const raw = serializeNodes([n]);
    const back = deserializeNodes(raw);
    expect(back[0].parentId).toBe('p');
    expect(back[0].seed).toBe(7);
  });
});

describe('manual links (v4.20)', () => {
  it('addLink creates a link between two nodes', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    st.addNode(makeNode('b'));
    useCanvasStore.getState().addLink('a', 'b');
    const s = useCanvasStore.getState();
    expect(s.links).toHaveLength(1);
    expect(s.links[0].from).toBe('a');
    expect(s.links[0].to).toBe('b');
  });

  it('addLink dedupes both directions (unordered)', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    st.addNode(makeNode('b'));
    st.addLink('a', 'b');
    useCanvasStore.getState().addLink('b', 'a'); // 反向应被忽略
    expect(useCanvasStore.getState().links).toHaveLength(1);
  });

  it('addLink rejects self-link and missing nodes', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    useCanvasStore.getState().addLink('a', 'a');
    useCanvasStore.getState().addLink('a', 'ghost');
    expect(useCanvasStore.getState().links).toHaveLength(0);
  });

  it('removeLink deletes by id', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    st.addNode(makeNode('b'));
    useCanvasStore.getState().addLink('a', 'b');
    const id = useCanvasStore.getState().links[0].id;
    useCanvasStore.getState().removeLink(id);
    expect(useCanvasStore.getState().links).toHaveLength(0);
  });

  it('removeNode also removes its links', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    st.addNode(makeNode('b'));
    st.addNode(makeNode('c'));
    useCanvasStore.getState().addLink('a', 'b');
    useCanvasStore.getState().addLink('b', 'c');
    useCanvasStore.getState().removeNode('b');
    const ids = useCanvasStore.getState().nodes.map((n) => n.id);
    expect(ids).toEqual(['a', 'c']);
    expect(useCanvasStore.getState().links).toHaveLength(0);
  });

  it('clear empties links too and is undoable', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    st.addNode(makeNode('b'));
    useCanvasStore.getState().addLink('a', 'b');
    useCanvasStore.getState().clear();
    expect(useCanvasStore.getState().links).toHaveLength(0);
    useCanvasStore.getState().undo();
    expect(useCanvasStore.getState().links).toHaveLength(1);
  });

  it('serializes and deserializes links round-trip', () => {
    const st = useCanvasStore.getState();
    st.addNode(makeNode('a'));
    st.addNode(makeNode('b'));
    useCanvasStore.getState().addLink('a', 'b');
    const raw = serializeNodes(useCanvasStore.getState().nodes, useCanvasStore.getState().links);
    const back = deserializeLinks(raw);
    expect(back).toHaveLength(1);
    expect(back[0].from).toBe('a');
    expect(back[0].to).toBe('b');
  });
});
