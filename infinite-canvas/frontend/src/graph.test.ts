import { describe, it, expect } from 'vitest';
import { computeEdges, computeLinks } from './graph';
import type { CanvasNode } from './types';

function node(id: string, parentId?: string | null): CanvasNode {
  return {
    id, filename: id + '.png', prompt: '', templateId: 't',
    x: 0, y: 0, width: 100, height: 100, parentId: parentId ?? null,
  };
}

describe('computeEdges (生成血缘)', () => {
  it('links parent -> child via parentId', () => {
    const edges = computeEdges([node('a'), node('b', 'a')]);
    expect(edges).toHaveLength(1);
    expect(edges[0].from.id).toBe('a');
    expect(edges[0].to.id).toBe('b');
  });

  it('ignores missing parent', () => {
    expect(computeEdges([node('b', 'ghost')])).toHaveLength(0);
  });

  it('handles multi-level lineage', () => {
    const edges = computeEdges([node('a'), node('b', 'a'), node('c', 'b')]);
    expect(edges).toHaveLength(2);
  });

  it('originals (no parent) contribute no edges', () => {
    expect(computeEdges([node('a'), node('b')])).toHaveLength(0);
  });
});

describe('computeLinks (手动关联)', () => {
  it('derives edges from links', () => {
    const links = [{ id: 'L1', from: 'a', to: 'b' }];
    const edges = computeLinks([node('a'), node('b')], links);
    expect(edges).toHaveLength(1);
    expect(edges[0].from.id).toBe('a');
    expect(edges[0].to.id).toBe('b');
  });

  it('ignores links with a missing endpoint', () => {
    const links = [{ id: 'L1', from: 'a', to: 'ghost' }];
    expect(computeLinks([node('a')], links)).toHaveLength(0);
  });

  it('returns [] for empty links', () => {
    expect(computeLinks([node('a'), node('b')], [])).toHaveLength(0);
  });
});
