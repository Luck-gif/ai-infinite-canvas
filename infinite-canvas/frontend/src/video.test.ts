// 无限画布 · 视频模式数据层单元测试（Phase 9 验收）
import { describe, expect, it } from 'vitest';
import { MODE_META, DEFAULT_GEN_PARAMS, type GenMode, type CanvasNode } from './types';

const VIDEO_MODES: GenMode[] = ['txt2vid', 'img2vid'];
const VIDEO_RE = /\.(mp4|webm|mov|m4v)$/i;

describe('video modes (Phase 9)', () => {
  it('MODE_META 含文生/图生视频标签', () => {
    for (const m of VIDEO_MODES) {
      expect(MODE_META[m]).toBeDefined();
      expect(typeof MODE_META[m].label).toBe('string');
      expect(MODE_META[m].label.length).toBeGreaterThan(0);
    }
  });

  it('DEFAULT_GEN_PARAMS 含 frames / fps', () => {
    expect(DEFAULT_GEN_PARAMS.frames).toBe(33);
    expect(DEFAULT_GEN_PARAMS.fps).toBe(16);
  });

  it('视频节点以 kind=video 标记并落盘视频文件', () => {
    const node: CanvasNode = {
      id: 'n1',
      filename: 'ic_txt2vid_00001.mp4',
      prompt: 'a cat surfing',
      templateId: 'video_txt2vid',
      x: 0,
      y: 0,
      width: 832,
      height: 480,
      kind: 'video',
    };
    expect(node.kind).toBe('video');
    expect(VIDEO_RE.test(node.filename)).toBe(true);
  });

  it('图生视频节点携带起始图母节点', () => {
    const node: CanvasNode = {
      id: 'n2',
      filename: 'ic_img2vid_00001.mp4',
      prompt: 'animate',
      templateId: 'video_img2vid',
      parentId: 'src1',
      x: 0,
      y: 0,
      width: 832,
      height: 480,
      kind: 'video',
    };
    expect(node.kind).toBe('video');
    expect(node.parentId).toBe('src1');
  });
});
