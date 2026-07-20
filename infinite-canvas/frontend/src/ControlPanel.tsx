// 无限画布 · 控制面板：自然语言 + 参数面板 → /api/intent → /api/generate → 画布节点
// 支持：模型/尺寸/步数/CFG/批量/种子/负向提示词；图生图（上传或选中节点为输入 + denoise）
// v4.29: WebSocket 实时进度条（SSE → EventSource 流式推送）
import { useState, useEffect, useCallback, useRef } from 'react';
import { parseIntent, generate, generateStoryboard, previewWorkflow, uploadImage, imageUrl, fetchResult, listLoras, listControlnets, saveTemplate, listUserTemplates, loadUserTemplate, deleteUserTemplate } from './api';
import { useCanvasStore } from './store';
import { DEFAULT_GEN_PARAMS } from './types';
import type { IntentResponse, GenMode, GenParams, CanvasNode, Link, NodeKind } from './types';
import { MODE_META } from './types';
import { MaskEditor } from './MaskEditor';
import { theme } from './theme';

const DISPLAY_W = 280;

const smallBtnCss: React.CSSProperties = {
  padding: '4px 10px',
  fontSize: 11,
  borderRadius: 6,
  border: '1px solid',
  cursor: 'pointer',
  background: 'transparent',
  whiteSpace: 'nowrap',
};

const SIZE_PRESETS: { label: string; w: number; h: number }[] = [
  { label: '方图 1:1', w: 1024, h: 1024 },
  { label: '横图 16:9', w: 1024, h: 576 },
  { label: '竖图 9:16', w: 768, h: 1024 },
];

const DIR_LABEL: Record<'left' | 'right' | 'up' | 'down' | 'all', string> = {
  left: '左', right: '右', up: '上', down: '下', all: '四向',
};

const BLEND_MODES = [
  'normal', 'add', 'multiply', 'screen', 'overlay', 'soft_light',
  'difference', 'darken', 'lighten', 'color_dodge', 'color_burn',
  'linear_dodge', 'linear_burn', 'hue', 'saturation', 'color',
  'luminosity', 'subtract', 'divide',
];

/** 将 URL 图片取回并转 base64（用于「选中节点作为图生图输入」） */
async function urlToBase64(url: string): Promise<string> {
  const res = await fetch(url);
  const blob = await res.blob();
  return await new Promise<string>((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = reject;
    fr.readAsDataURL(blob);
  });
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = reject;
    fr.readAsDataURL(file);
  });
}

export function ControlPanel() {
  const [text, setText] = useState('画一座宁静的雪山湖泊，写实摄影风格，横图');
  const [intent, setIntent] = useState<IntentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState('');
  const [error, setError] = useState<string | null>(null);
  // v4.29: WebSocket 实时进度（SSE → EventSource）
  const [progress, setProgress] = useState<{ value: number; max: number; node: string; phase: string } | null>(null);
  const [p, setP] = useState<GenParams>({ ...DEFAULT_GEN_PARAMS });
  const [randomSeed, setRandomSeed] = useState(true);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [uploadPreview, setUploadPreview] = useState<string | null>(null);
  const [maskOpen, setMaskOpen] = useState(false);
  const [maskDataUrl, setMaskDataUrl] = useState<string | null>(null);

  // v4.33: 角色一致性 - 人脸参考图独立上传
  const [faceUploadName, setFaceUploadName] = useState<string | null>(null);
  const [faceUploadPreview, setFaceUploadPreview] = useState<string | null>(null);

  // v4.34: 多图融合 - 图片B独立上传
  const [blendUploadNameB, setBlendUploadNameB] = useState<string | null>(null);

  // v4.35: 风格一致性 - 风格参考图独立上传
  const [styleUploadName, setStyleUploadName] = useState<string | null>(null);
  const [styleUploadPreview, setStyleUploadPreview] = useState<string | null>(null);

  // v4.36: 场景一致性 - 场景参考图独立上传
  const [sceneUploadName, setSceneUploadName] = useState<string | null>(null);
  const [sceneUploadPreview, setSceneUploadPreview] = useState<string | null>(null);

  // v4.37: 道具一致性 - 道具参考图独立上传
  const [propUploadName, setPropUploadName] = useState<string | null>(null);
  const [propUploadPreview, setPropUploadPreview] = useState<string | null>(null);

  // v4.27: 折叠分组 + 错误定时消失
  const [paramOpen, setParamOpen] = useState(true);
  const [selectedOpen, setSelectedOpen] = useState(true);
  const [controlOpen, setControlOpen] = useState(true);
  const errorTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearErrorTimer = useCallback(() => {
    if (errorTimer.current) { clearTimeout(errorTimer.current); errorTimer.current = null; }
  }, []);
  // 错误自动 8 秒消失
  useEffect(() => {
    if (!error) return;
    clearErrorTimer();
    errorTimer.current = setTimeout(() => setError(null), 8000);
    return clearErrorTimer;
  }, [error, clearErrorTimer]);

  const addNode = useCanvasStore((s) => s.addNode);
  const addTextNode = useCanvasStore((s) => s.addTextNode);
  const nodeCount = useCanvasStore((s) => s.nodes.length);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const nodes = useCanvasStore((s) => s.nodes);
  const selectedNode = nodes.find((n) => n.id === selectedId) || null;
  const requestFocus = useCanvasStore((s) => s.requestFocus);
  const removeNode = useCanvasStore((s) => s.removeNode);
  const links = useCanvasStore((s) => s.links);
  const removeLink = useCanvasStore((s) => s.removeLink);
  const addLink = useCanvasStore((s) => s.addLink);
  const updateNode = useCanvasStore((s) => s.updateNode);
  const setLiveWorkflow = useCanvasStore((s) => s.setLiveWorkflow);
  const select = useCanvasStore((s) => s.select);
  const replaceAll = useCanvasStore((s) => s.replaceAll);  // v4.31: 模板加载
  const addToTimeline = useCanvasStore((s) => s.addToTimeline);
  const setTimelineOpen = useCanvasStore((s) => s.setTimelineOpen);
  const timelineClips = useCanvasStore((s) => s.timelineClips);
  // v4.51: 三层画布上下文
  const activeLayer = useCanvasStore((s) => s.activeLayer);
  const [loras, setLoras] = useState<string[]>([]);
  useEffect(() => {
    listLoras().then(setLoras).catch(() => {});
  }, []);
  const [controlnets, setControlnets] = useState<string[]>([]);
  const [unionTypes, setUnionTypes] = useState<string[]>([]);
  useEffect(() => {
    listControlnets().then((r) => {
      setControlnets(r.controlnets);
      setUnionTypes(r.unionTypes);
    }).catch(() => {});
  }, []);

  // v4.31: 用户工作流模板保存/加载
  const [templateName, setTemplateName] = useState('');
  const [templates, setTemplates] = useState<{ name: string; saved_at: number; node_count: number }[]>([]);
  const [templateOpen, setTemplateOpen] = useState(false);
  const loadTemplates = useCallback(() => {
    listUserTemplates().then(setTemplates).catch(() => {});
  }, []);
  useEffect(() => { loadTemplates(); }, [loadTemplates]);

  const set = <K extends keyof GenParams>(k: K, v: GenParams[K]) =>
    setP((prev) => ({ ...prev, [k]: v }));

  const onPickFile = async (file: File | null) => {
    if (!file) return;
    setError(null);
    try {
      const dataUrl = await fileToBase64(file);
      setUploadPreview(dataUrl);
      setMaskDataUrl(null); // 换底图后旧蒙版失效
      const name = await uploadImage(file.name, dataUrl);
      setUploadName(name);
    } catch (e) {
      setError('上传失败：' + ((e as Error)?.message || String(e)));
    }
  };

  // v4.33: 角色一致性 - 人脸参考图上传
  const onPickFaceFile = async (file: File | null) => {
    if (!file) return;
    setError(null);
    try {
      const dataUrl = await fileToBase64(file);
      setFaceUploadPreview(dataUrl);
      const name = await uploadImage(`face_${Date.now()}_${file.name}`, dataUrl);
      setFaceUploadName(name);
    } catch (e) {
      setError('人脸图上传失败：' + ((e as Error)?.message || String(e)));
    }
  };

  // v5.1: 图生视频 - 尾帧上传
  const [endFrameUploadName, setEndFrameUploadName] = useState<string>('');
  const [_endFrameUploadPreview, setEndFrameUploadPreview] = useState<string>('');
  const _onPickEndFrameFile = async (file: File | null) => {
    if (!file) return;
    setError(null);
    try {
      const dataUrl = await fileToBase64(file);
      setEndFrameUploadPreview(dataUrl);
      const name = await uploadImage(`endframe_${Date.now()}_${file.name}`, dataUrl);
      setEndFrameUploadName(name);
    } catch (e) {
      setError('尾帧上传失败：' + ((e as Error)?.message || String(e)));
    }
  };

  // v4.34: 多图融合 - 图片B上传
  const onPickBlendFile = async (file: File | null) => {
    if (!file) return;
    setError(null);
    try {
      const name = await uploadImage(`blend_${Date.now()}_${file.name}`, await fileToBase64(file));
      setBlendUploadNameB(name);
    } catch (e) {
      setError('融合图B上传失败：' + ((e as Error)?.message || String(e)));
    }
  };

  // ── 控制节点（§6.22 LoRA / §6.23 ControlNet 节点化）──
  const addControlNode = (targetId: string, kind: 'lora' | 'controlnet') => {
    const t = nodes.find((n) => n.id === targetId);
    const id = crypto.randomUUID();
    const nx = t ? t.x + t.width + 60 : 80;
    const ny = t ? t.y : 80;
    const base: Parameters<typeof addNode>[0] = {
      id,
      filename: '',
      prompt: '',
      templateId: 'control',
      x: nx,
      y: ny,
      width: 200,
      height: 150,
      kind: 'control',
      controlKind: kind,
    };
    if (kind === 'lora') {
      base.loraName = loras[0] || '';
      base.loraStrength = 0.8;
    } else {
      base.controlModel = controlnets[0] || '';
      base.controlType = unionTypes[0] || 'canny/lineart/anime_lineart/mlsd';
      base.controlStrength = 1.0;
    }
    addNode(base);
    if (t) addLink(id, targetId); // 控制 → 图片（应用关系）
    select(id);
    requestFocus(id);
  };

  const applyControl = async () => {
    if (!selectedNode || selectedNode.kind !== 'control') return;
    const link = links.find((l) => l.from === selectedNode.id);
    if (!link) {
      setError('请先把控制节点连线到目标图片节点（拖右侧锚点）');
      return;
    }
    const tgt = nodes.find((n) => n.id === link.to);
    if (!tgt) {
      setError('未找到目标图片节点');
      return;
    }
    setLoading(true);
    setError(null);
    setPhase('应用控制…');
    try {
      const b64 = await urlToBase64(imageUrl(tgt.filename));
      const inputImage = await uploadImage(tgt.filename, b64);
      const loraList =
        selectedNode.controlKind === 'lora'
          ? [{ name: selectedNode.loraName || '', strength: selectedNode.loraStrength ?? 1.0 }]
          : [];
      // §6.23 ControlNet：仅有控制节点时注入（type 仅 union 模型有效）
      const cnList: { model: string; type?: string; strength: number; image: string }[] =
        selectedNode.controlKind === 'controlnet'
          ? [{
              model: selectedNode.controlModel || '',
              type: (selectedNode.controlModel || '').includes('union')
                ? selectedNode.controlType || undefined
                : undefined,
              strength: selectedNode.controlStrength ?? 1.0,
              image: selectedNode.controlImage || tgt.filename,
            }]
          : [];
      const seed = randomSeed ? Math.floor(Math.random() * 2_147_483_647) : p.seed;
      const res = await generate({
        intent: { action: 'img2img', params: { prompt: tgt.prompt || text } },
        wait: true,
        seed,
        input_image: inputImage,
        denoise: 0.6,
        loras: loraList,
        controlnets: cnList,
      });
      if (!res?.images?.length) {
        setError('生成失败：未返回图片（' + (res?.status || 'unknown') + '）');
        return;
      }
      const dw = DISPLAY_W;
      const dh = Math.max(120, Math.round(DISPLAY_W * (tgt.height / tgt.width)));
      addNode({
        id: crypto.randomUUID(),
        filename: res.images[0],
        prompt: tgt.prompt || text,
        templateId: res.template_id || 'unknown',
        x: tgt.x + tgt.width + 60,
        y: tgt.y,
        width: dw,
        height: dh,
        mode: 'img2img',
        parentId: selectedNode.parentId || tgt.id,
        seed,
        negative: p.negative,
        createdAt: Date.now(),
      });
      setPhase('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  // 切换生成模式；进入视频模式时套用 Wan2.2 友好的 16:9 预设（§6.4.1/§6.4.2）
  const setMode = (m: GenMode) => {
    const isVid = m === 'txt2vid' || m === 'img2vid';
    set('mode', m);
    if (isVid) {
      set('width', 832);
      set('height', 480);
      set('frames', 33);
      set('fps', 16);
    }
    if (m === 'face_consistency') {
      set('width', 1024);
      set('height', 1024);
    }
    if (m === 'image_blend') {
      set('width', 1024);
      set('height', 1024);
    }
    if (m === 'style_consistency') {
      set('width', 1024);
      set('height', 1024);
    }
    if (m === 'scene_consistency') {
      set('width', 1024);
      set('height', 1024);
    }
    if (m === 'prop_consistency') {
      set('width', 1024);
      set('height', 1024);
    }
    if (m === 'storyboard') {
      set('width', 1024);
      set('height', 1024);
    }
  };

  const run = async () => {
    if (!text.trim() || loading) return;
    setLoading(true);
    setError(null);
    setIntent(null);
    try {
      // 1) 意图解析
      setPhase('解析意图…');
      const it = await parseIntent(text);
      setIntent(it);

      // 2) 组装参数：面板显式值覆盖意图默认
      const seed = randomSeed ? Math.floor(Math.random() * 2_147_483_647) : p.seed;
      const intentPayload: Record<string, unknown> = {
        ...(it as unknown as Record<string, unknown>),
        action: (p.mode === 'outpaint' || p.mode === 'txt2vid' || p.mode === 'img2vid' || p.mode === 'face_consistency' || p.mode === 'image_blend' || p.mode === 'style_consistency' || p.mode === 'scene_consistency' || p.mode === 'prop_consistency' || p.mode === 'storyboard') ? p.mode : it.action,
        params: {
          ...(it.params || {}),
          ...(p.model ? { model: p.model } : {}),
          width: p.width,
          height: p.height,
          steps: p.steps,
          cfg: p.cfg,
          negative_prompt: p.negative || (it.params?.negative_prompt as string) || '',
        },
      };

      // 3) 图生图/局部重绘/扩图 输入图（上传优先，否则选中节点）
      let inputImage: string | null = null;
      let maskImage: string | null = null;
      if (p.mode === 'img2img' || p.mode === 'inpaint' || p.mode === 'outpaint' || p.mode === 'img2vid' || p.mode === 'image_blend') {
        const needMsg =
          p.mode === 'inpaint' ? '局部重绘' : p.mode === 'outpaint' ? '扩图' : p.mode === 'image_blend' ? '图像融合' : '图生图';
        if (uploadName) {
          inputImage = uploadName;
        } else if (selectedNode) {
          setPhase('准备输入图…');
          const b64 = await urlToBase64(imageUrl(selectedNode.filename));
          inputImage = await uploadImage(selectedNode.filename, b64);
        } else {
          setError(`${needMsg}需要输入图：请上传图片或先在画布选中一个节点`);
          setLoading(false);
          setPhase('');
          return;
        }
      }
      if (p.mode === 'inpaint') {
        if (!maskDataUrl) {
          setError('局部重绘需要蒙版：请点击「绘制蒙版」涂抹要重绘的区域');
          setLoading(false);
          setPhase('');
          return;
        }
        setPhase('上传蒙版…');
        maskImage = await uploadImage(`mask_${Date.now()}.png`, maskDataUrl);
      }

      // v4.33: 角色一致性 - 人脸参考图
      let faceImage: string | null = null;
      if (p.mode === 'face_consistency') {
        if (faceUploadName) {
          faceImage = faceUploadName;
        } else if (selectedNode) {
          setPhase('准备人脸参考图…');
          const b64 = await urlToBase64(imageUrl(selectedNode.filename));
          faceImage = await uploadImage(`face_ref_${Date.now()}.png`, b64);
        } else {
          setError('角色一致性需要人脸参考图：请上传或选中画布节点');
          setLoading(false);
          setPhase('');
          return;
        }
      }

      // v4.34: 多图融合 - 图片B
      let blendImageB: string | null = null;
      if (p.mode === 'image_blend') {
        if (!blendUploadNameB) {
          setError('图像融合需要图片B：请上传叠加层图片');
          setLoading(false);
          setPhase('');
          return;
        }
        blendImageB = blendUploadNameB;
      }

      // v4.35: 风格一致性 - 风格参考图
      let styleImage: string | null = null;
      if (p.mode === 'style_consistency') {
        if (!styleUploadName) {
          setError('风格一致性需要上传一张风格参考图（例如油画、水彩、赛博朋克风格图片）');
          setLoading(false);
          setPhase('');
          return;
        }
        styleImage = styleUploadName;
      }

      // v4.36: 场景一致性 - 场景参考图
      let sceneImage: string | null = null;
      if (p.mode === 'scene_consistency') {
        if (!sceneUploadName) {
          setError('场景一致性需要上传一张场景参考图（例如森林、城市、海滩、室内等环境图片）');
          setLoading(false);
          setPhase('');
          return;
        }
        sceneImage = sceneUploadName;
      }

      // v4.37: 道具一致性 - 道具参考图
      let propImage: string | null = null;
      if (p.mode === 'prop_consistency') {
        if (!propUploadName) {
          setError('道具一致性需要上传一张道具参考图（例如武器、饰品、家具、服装单品等物品图片）');
          setLoading(false);
          setPhase('');
          return;
        }
        propImage = propUploadName;
      }

      // ── v4.38 分镜编排：独立端点，跳过预览 ──
      if (p.mode === 'storyboard') {
        const prompts = p.storyboardPrompts.filter((s: string) => s.trim());
        if (prompts.length === 0) {
          setError('请在分镜文本框中输入至少一条分镜提示词（每行一个镜头）');
          setLoading(false);
          setPhase('');
          return;
        }
        setPhase(`${prompts.length} 帧并行生成中…`);
        try {
          const res = await generateStoryboard({
            prompts,
            checkpoint: p.model || undefined,
            width: p.width, height: p.height,
            steps: p.steps, cfg: p.cfg,
            seed,
          });
          if (!res.validated) {
            setError(res.issues.join('; ') || '分镜生成失败');
            setLoading(false);
            setPhase('');
            return;
          }
          // 逐个放置帧节点到画布（4 列 grid 排列）
          const outW = p.width;
          const outH = p.height;
          const dw = DISPLAY_W;
          const dh = Math.max(120, Math.round(DISPLAY_W * (outH / outW)));
          let placed = 0;
          const existingCount = useCanvasStore.getState().nodes.length;
          const baseX = 60 + (existingCount > 0 ? 320 : 0);
          const baseY = 60 + (existingCount > 0 ? existingCount * 18 : 0);
          for (let i = 0; i < res.frames.length; i++) {
            const frame = res.frames[i];
            if (!frame.image) continue;
            const col = placed % 4;
            const row = Math.floor(placed / 4);
            addNode({
              id: crypto.randomUUID(),
              filename: frame.image,
              prompt: frame.prompt,
              templateId: 'storyboard_sdxl',
              x: baseX + col * (dw + 40),
              y: baseY + row * (dh + 70),
              width: dw,
              height: dh,
              mode: 'storyboard',
              seed: seed + i,
              negative: p.negative,
              createdAt: Date.now(),
            });
            placed++;
          }
        } catch (e: unknown) {
          setError(`分镜生成异常: ${(e as Error)?.message || String(e)}`);
          setLoading(false);
          setPhase('');
        }
        return;
      }

      // 3.5) 生成前预览工作流（不提交 ComfyUI，前端面板实时显示）
      setPhase('预览工作流…');
      try {
        const preview = await previewWorkflow({
          intent: intentPayload,
          wait: false,
          frames: p.frames,
          fps: p.fps,
          seed,
          batch_size: p.mode === 'txt2img' ? p.batchSize : 1,
          input_image: inputImage,
          denoise: p.denoise,
          mask_image: maskImage,
          grow_mask_by: p.growMaskBy,
          outpaint_direction: p.mode === 'outpaint' ? p.outpaintDir : undefined,
          outpaint_pixels: p.mode === 'outpaint' ? p.outpaintPixels : undefined,
          face_image: faceImage,
          face_weight: p.faceWeight,
          blend_image_b: blendImageB,
          blend_mode: p.blendMode,
          blend_factor: p.blendFactor,
          style_image: styleImage,
          style_weight: p.styleWeight,
          composition_weight: p.compositionWeight,
          scene_image: sceneImage,
          scene_weight: p.sceneWeight,
          prop_image: propImage,
          prop_weight: p.propWeight,
          end_image: p.mode === 'img2vid' ? endFrameUploadName || undefined : undefined,
        });
        setLiveWorkflow(preview.workflow);
      } catch {
        // 预览失败不影响生成流程
        setLiveWorkflow(null);
      }

      // 4) 生成（v4.29: 非阻塞提交 + SSE 实时进度 + 轮询取结果）
      setPhase('提交中…');
      const res = await generate({
        intent: intentPayload,
        wait: false,  // 非阻塞：立即返回 prompt_id
        frames: p.frames,
        fps: p.fps,
        video_quality: p.videoQuality,  // v5.0 LightX2V
        seed,
        batch_size: p.mode === 'txt2img' ? p.batchSize : 1,
        input_image: inputImage,
        denoise: p.denoise,
        mask_image: maskImage,
        grow_mask_by: p.growMaskBy,
        outpaint_direction: p.mode === 'outpaint' ? p.outpaintDir : undefined,
        outpaint_pixels: p.mode === 'outpaint' ? p.outpaintPixels : undefined,
        face_image: faceImage,
        face_weight: p.faceWeight,
        blend_image_b: blendImageB,
        blend_mode: p.blendMode,
        blend_factor: p.blendFactor,
        style_image: styleImage,
        style_weight: p.styleWeight,
        composition_weight: p.compositionWeight,
        scene_image: sceneImage,
        scene_weight: p.sceneWeight,
        prop_image: propImage,
        prop_weight: p.propWeight,
        end_image: p.mode === 'img2vid' ? endFrameUploadName || undefined : undefined,
      });
      const promptId = res.prompt_id;
      if (!promptId) {
        setError('生成失败：未返回 prompt_id');
        return;
      }
      setPhase('接收实时进度…');

      // v4.29: SSE 实时进度 + 等待完成 + 拉取结果
      const result = await new Promise<{ images: string[] }>((resolve, reject) => {
        const es = new EventSource('/api/stream/' + promptId);
        es.onmessage = (e) => {
          try {
            const ev = JSON.parse(e.data);
            if (ev.type === 'progress') {
              setProgress({ value: ev.value, max: ev.max, node: ev.node || '', phase: `采样 ${ev.value}/${ev.max}` });
            } else if (ev.type === 'executing') {
              if (ev.node) {
                setPhase(`运行节点 ${ev.node}…`);
                setProgress((prev) => prev ? { ...prev, phase: `运行节点 ${ev.node}` } : null);
              }
            } else if (ev.type === 'start') {
              setPhase('ComfyUI 开始执行…');
            } else if (ev.type === 'done') {
              es.close();
              setPhase('拉取结果…');
              setProgress(null);
              // 轮询获取最终出图
              fetchResult(promptId)
                .then((r) => { if (r.images.length > 0) resolve(r); else reject(new Error('未出图')); })
                .catch(reject);
            } else if (ev.type === 'error') {
              es.close();
              setProgress(null);
              reject(new Error(ev.message || 'ComfyUI 执行出错'));
            } else if (ev.type === 'timeout') {
              es.close();
              setProgress(null);
              reject(new Error('生成超时'));
            }
          } catch {
            // 解析失败静默
          }
        };
        es.onerror = () => {
          es.close();
          setProgress(null);
          // EventSource 有时触发 onerror 后自动重连；对于非阻塞生成，仅当 10 秒无消息时认为断连
          setTimeout(() => {
            setPhase('拉取结果（备选）…');
            fetchResult(promptId)
              .then((r) => { if (r.images.length > 0) resolve(r); else reject(new Error('未出图')); })
              .catch(reject);
          }, 2000);
        };
        setTimeout(() => { es.close(); reject(new Error('生成超时（240s）')); }, 240_000);
      });

      if (result.images.length === 0) {
        setError('生成未返回图片');
        return;
      }
      const images = result.images;

      // 5) 落图到画布（扩图按方向贴源节点旁；其余网格散布）
      const templateId = res.template_id || 'unknown';
      const outW = p.width;
      const outH = p.height;
      const dw = DISPLAY_W;
      const dh = Math.max(120, Math.round(DISPLAY_W * (outH / outW)));
      const parentId =
        (p.mode === 'img2img' || p.mode === 'inpaint' || p.mode === 'outpaint' || p.mode === 'img2vid' || p.mode === 'face_consistency' || p.mode === 'image_blend' || p.mode === 'style_consistency' || p.mode === 'scene_consistency') && selectedNode && !uploadName ? selectedNode.id : null;

      const isOutpaint = p.mode === 'outpaint' && selectedNode && !uploadName;
      if (isOutpaint && selectedNode) {
        const pad = 60;
        const dir = p.outpaintDir;
        let nx = selectedNode.x, ny = selectedNode.y;
        if (dir === 'right') nx = selectedNode.x + selectedNode.width + pad;
        else if (dir === 'left') nx = selectedNode.x - dw - pad;
        else if (dir === 'down') ny = selectedNode.y + selectedNode.height + pad;
        else if (dir === 'up') ny = selectedNode.y - dh - pad;
        addNode({
          id: crypto.randomUUID(),
          filename: images[0],
          prompt: (intentPayload.params as { prompt?: string })?.prompt || text,
          templateId,
          x: nx, y: ny, width: dw, height: dh,
          mode: 'outpaint',
          parentId: selectedNode.id,
          seed,
          negative: p.negative,
          createdAt: Date.now(),
        });
      } else {
        const base = nodeCount;
        images.forEach((fn, i) => {
          const idx = base + i;
          const col = idx % 4;
          const row = Math.floor(idx / 4);
          addNode({
            id: crypto.randomUUID(),
            filename: fn,
            prompt: (intentPayload.params as { prompt?: string })?.prompt || text,
            templateId,
            x: 60 + col * (dw + 40) + (i % 2) * 18,
            y: 60 + row * (dh + 70),
            width: dw,
            height: dh,
            mode: p.mode,
            parentId,
            kind: (p.mode === 'txt2vid' || p.mode === 'img2vid') ? 'video' : undefined,
            frames: (p.mode === 'txt2vid' || p.mode === 'img2vid') ? p.frames : undefined,
            fps: (p.mode === 'txt2vid' || p.mode === 'img2vid') ? p.fps : undefined,
            seed,
            negative: p.negative,
            createdAt: Date.now(),
            endFrameImage: p.mode === 'img2vid' ? endFrameUploadName || undefined : undefined,
          });
        });
      }
    } catch (e: unknown) {
      setError((e as Error)?.message || String(e));
    } finally {
      setLoading(false);
      setPhase('');
    }
  };

  return (
    <aside style={panelStyle}>
      <div>
        <div style={labelStyle}>自然语言描述</div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          style={textareaStyle}
          placeholder="例如：用 Qwen-Image 画一只在星空下奔跑的红色狐狸，赛博朋克风格"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !loading) { e.preventDefault(); run(); }
          }}
        />
      </div>

      {/* 空画布友好提示 */}
      {nodes.length === 0 && !text.trim() && (
        <div style={{ ...cardStyle, background: 'rgba(99,102,241,0.08)', borderColor: 'rgba(99,102,241,0.25)' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: theme.text.primary, marginBottom: 6 }}>
            快速开始
          </div>
          <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: theme.text.secondary, lineHeight: 1.7 }}>
            <li>在上方输入自然语言描述</li>
            <li>选择生成模式（文生图 / 文生视频等）</li>
            <li>点击底部「生成」按钮，结果会自动落到画布</li>
          </ol>
        </div>
      )}

      {/* 模式：文生图 / 图生图 / 局部重绘 / 扩图（第1行）+ 视频 / 角色一致（第2行） */}
      {/* v4.51: 模式选择器（带层级色彩标记） */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        <SegBtn small active={p.mode === 'txt2img'} onClick={() => set('mode', 'txt2img')} label="文生图" />
        <SegBtn small active={p.mode === 'img2img'} onClick={() => set('mode', 'img2img')} label="图生图" />
        <SegBtn small active={p.mode === 'inpaint'} onClick={() => set('mode', 'inpaint')} label="局部重绘" />
        <SegBtn small active={p.mode === 'outpaint'} onClick={() => set('mode', 'outpaint')} label="扩图" />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        <SegBtn small active={p.mode === 'txt2vid'} onClick={() => setMode('txt2vid')} label="文生视频" layer="output" />
        <SegBtn small active={p.mode === 'img2vid'} onClick={() => setMode('img2vid')} label="图生视频" layer="output" />
        <SegBtn small active={p.mode === 'face_consistency'} onClick={() => setMode('face_consistency')} label="角色" />
        <SegBtn small active={p.mode === 'image_blend'} onClick={() => setMode('image_blend')} label="融合" />
        <SegBtn small active={p.mode === 'style_consistency'} onClick={() => setMode('style_consistency')} label="风格" />
        <SegBtn small active={p.mode === 'scene_consistency'} onClick={() => setMode('scene_consistency')} label="场景" />
        <SegBtn small active={p.mode === 'prop_consistency'} onClick={() => setMode('prop_consistency')} label="道具" />
        <SegBtn small active={p.mode === 'storyboard'} onClick={() => setMode('storyboard')} label="分镜" layer="planning" />
      </div>
      {/* v4.51: 层级上下文提示 */}
      <PanelHint layer={activeLayer} />

      {/* v5.1 画布元素快捷添加: 文本注释 / 音频节点 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        <button
          onClick={() => { addTextNode(); }}
          style={{
            ...smallBtnCss,
            background: 'rgba(164, 107, 255, 0.12)',
            borderColor: 'rgba(164, 107, 255, 0.3)',
            color: '#c4a0ff',
          }}
        >
          📝 添加文本
        </button>
        <button
          onClick={() => {
            addNode({
              id: crypto.randomUUID(),
              filename: 'audio_placeholder',
              prompt: '',
              x: 320, y: 80,
              width: 300, height: 80,
              kind: 'audio' as NodeKind,
              mode: 'txt2vid',
              templateId: '',
            } as CanvasNode);
          }}
          style={{
            ...smallBtnCss,
            background: 'rgba(160, 107, 255, 0.12)',
            borderColor: 'rgba(160, 107, 255, 0.3)',
            color: '#c4a0ff',
          }}
        >
          🎵 添加音频
        </button>
      </div>

      {/* 图生图 / 局部重绘 输入区 */}
      {(p.mode === 'img2img' || p.mode === 'inpaint' || p.mode === 'img2vid') && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>{p.mode === 'img2vid' ? '首帧' : '输入图'}</div>
          <label style={fileBtnStyle}>
            {p.mode === 'img2vid' ? '上传首帧' : '上传图片'}
            <input
              type="file"
              accept="image/*"
              style={{ display: 'none' }}
              onChange={(e) => onPickFile(e.target.files?.[0] || null)}
            />
          </label>
          {(uploadPreview || selectedNode) && (
            <div style={{ marginTop: 8, fontSize: 12, color: theme.text.soft }}>
              {uploadName ? `已上传：${uploadName}` : selectedNode ? '将使用选中节点作为输入' : ''}
            </div>
          )}
          {!uploadName && !selectedNode && (
            <div style={{ marginTop: 8, fontSize: 12, color: theme.accent.amber }}>
              请上传{ p.mode === 'img2vid' ? '首帧' : '' }图片，或在画布中选中一个已生成节点
            </div>
          )}

          {/* v5.1: 图生视频 - 尾帧上传 */}
          {p.mode === 'img2vid' && (
            <>
              <div style={{ ...labelStyle, marginTop: 12, marginBottom: 8 }}>尾帧（可选）</div>
              <label style={fileBtnStyle}>
                上传尾帧
                <input
                  type="file"
                  accept="image/*"
                  style={{ display: 'none' }}
                  onChange={(e) => _onPickEndFrameFile(e.target.files?.[0] || null)}
                />
              </label>
              {_endFrameUploadPreview && (
                <div style={{ marginTop: 8 }}>
                  <img src={_endFrameUploadPreview} alt="尾帧预览"
                    style={{ width: '100%', maxHeight: 100, objectFit: 'contain', borderRadius: 6, border: `1px solid ${theme.border.subtle}` }} />
                  <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 4 }}>
                    {endFrameUploadName}
                  </div>
                </div>
              )}
              {!endFrameUploadName && (
                <div style={{ marginTop: 6, fontSize: 11, color: theme.text.dim }}>
                  留空则无尾帧约束；也可在画布中通过端口连线传入
                </div>
              )}
            </>
          )}

          {p.mode === 'inpaint' && (
            <div style={{ marginTop: 10 }}>
              <button
                style={{ ...fileBtnStyle, width: '100%', textAlign: 'center', border: `1px solid ${maskDataUrl ? theme.accent.sky : theme.border.dashed}` }}
                onClick={() => {
                  if (!uploadPreview && !selectedNode) {
                    setError('请先上传图片或选中画布节点作为底图');
                    return;
                  }
                  setError(null);
                  setMaskOpen(true);
                }}
              >
                {maskDataUrl ? '✓ 已绘制蒙版（点击重绘）' : '绘制蒙版'}
              </button>
              {maskDataUrl && (
                <img
                  src={maskDataUrl}
                  alt="mask"
                  style={{ marginTop: 8, width: '100%', maxHeight: 120, objectFit: 'contain', background: '#000', borderRadius: 6 }}
                />
              )}
              <div style={{ marginTop: 10 }}>
                <SliderRow label="蒙版外扩 grow" value={p.growMaskBy} min={0} max={32} step={1}
                  onChange={(v) => set('growMaskBy', v)} fmt={(v) => `${v}px`} />
              </div>
            </div>
          )}

          <div style={{ marginTop: 10 }}>
            <SliderRow
              label={p.mode === 'inpaint' ? '重绘强度 denoise' : '重绘幅度 denoise'}
              value={p.denoise}
              min={p.mode === 'inpaint' ? 0.4 : 0.2}
              max={1.0} step={0.05}
              onChange={(v) => set('denoise', v)} fmt={(v) => v.toFixed(2)} />
          </div>
        </div>
      )}

      {/* 扩图 参数区 */}
      {p.mode === 'outpaint' && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>扩图（Outpainting）</div>
          <div style={{ fontSize: 12, color: theme.text.soft, marginBottom: 8 }}>
            将选中节点向指定方向延展：原图内容保留，新增区域由模型生成。请在画布选中一个节点作为源。
          </div>
          <div style={labelSm}>扩展方向</div>
          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            {(['right', 'left', 'up', 'down', 'all'] as const).map((d) => (
              <SegBtn small key={d} active={p.outpaintDir === d}
                onClick={() => set('outpaintDir', d)} label={DIR_LABEL[d]} />
            ))}
          </div>
          <SliderRow label="扩展像素" value={p.outpaintPixels} min={64} max={1024} step={32}
            onChange={(v) => set('outpaintPixels', v)} fmt={(v) => `${v}px`} />
          {!selectedNode && (
            <div style={{ marginTop: 8, fontSize: 12, color: theme.accent.amber }}>
              尚未选中节点：请先在画布点击一个已生成节点作为扩图源
            </div>
          )}
        </div>
      )}

      {/* v4.33: 角色一致性（IPAdapterFaceID） */}
      {p.mode === 'face_consistency' && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>角色一致性 · IPAdapterFaceID</div>
          <div style={{ fontSize: 12, color: theme.text.soft, marginBottom: 10 }}>
            上传一张人脸参考图，生成的新图片将保持该角色面部特征一致。支持上传或选中画布节点作为参考。
          </div>

          {/* 人脸参考图上传 */}
          <div style={labelSm}>人脸参考图</div>
          <label style={{ ...fileBtnStyle, marginTop: 6 }}>
            上传人脸图
            <input
              type="file"
              accept="image/*"
              style={{ display: 'none' }}
              onChange={(e) => onPickFaceFile(e.target.files?.[0] || null)}
            />
          </label>

          {(faceUploadPreview || selectedNode) && (
            <div style={{ marginTop: 8, fontSize: 12, color: theme.text.soft }}>
              {faceUploadName ? `已上传：${faceUploadName}` : selectedNode ? '将使用选中节点作为参考' : ''}
            </div>
          )}
          {!faceUploadName && !selectedNode && (
            <div style={{ marginTop: 8, fontSize: 12, color: theme.accent.amber }}>
              请上传人脸参考图，或在画布中选中一个已生成节点
            </div>
          )}

          {/* face_weight 滑块 */}
          <div style={{ marginTop: 12 }}>
            <SliderRow
              label="面部保持强度 face_weight"
              value={p.faceWeight}
              min={0.1} max={1.5} step={0.05}
              onChange={(v) => set('faceWeight', v)}
              fmt={(v) => v.toFixed(2)} />
          </div>
          <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 2 }}>
            建议 0.6-0.9；越高面部越像参考图，越低越自由。
          </div>
        </div>
      )}

      {/* v4.34: 多图融合 ImageBlend */}
      {p.mode === 'image_blend' && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>多图融合 · ImageBlend</div>
          <div style={{ fontSize: 12, color: theme.text.soft, marginBottom: 10 }}>
            将两张图片按指定模式和强度混合。图片 A 为底图，图片 B 叠加在上。
          </div>

          {/* 图片 A（复用现有上传机制） */}
          <div style={labelSm}>图片 A（底图）</div>
          <label style={{ ...fileBtnStyle, marginTop: 6 }}>
            {uploadName ? '更换图片A' : '上传图片A'}
            <input type="file" accept="image/*" style={{ display: 'none' }}
              onChange={(e) => onPickFile(e.target.files?.[0] || null)} />
          </label>
          {(uploadPreview || selectedNode) && (
            <div style={{ marginTop: 6, fontSize: 12, color: theme.text.soft }}>
              {uploadName ? `已上传：${uploadName}` : selectedNode ? '将使用选中节点作为图片A' : ''}
            </div>
          )}
          {!uploadName && !selectedNode && (
            <div style={{ marginTop: 6, fontSize: 12, color: theme.accent.amber }}>请上传或选中节点作为图片A</div>
          )}

          {/* 图片 B */}
          <div style={{ ...labelSm, marginTop: 12 }}>图片 B（叠加层）</div>
          <label style={{ ...fileBtnStyle, marginTop: 6 }}>
            {blendUploadNameB ? '更换图片B' : '上传图片B'}
            <input type="file" accept="image/*" style={{ display: 'none' }}
              onChange={(e) => onPickBlendFile(e.target.files?.[0] || null)} />
          </label>
          {blendUploadNameB && (
            <div style={{ marginTop: 6, fontSize: 12, color: theme.text.soft }}>已上传：{blendUploadNameB}</div>
          )}
          {!blendUploadNameB && (
            <div style={{ marginTop: 6, fontSize: 12, color: theme.accent.amber }}>请上传图片B</div>
          )}

          {/* 混合模式选择 */}
          <div style={{ ...labelSm, marginTop: 12 }}>混合模式</div>
          <select
            value={p.blendMode}
            onChange={(e) => set('blendMode', e.target.value)}
            style={{
              width: '100%', marginTop: 4, marginBottom: 10,
              background: theme.bg.dropdown, color: theme.text.secondary,
              border: `1px solid ${theme.border.subtle}`, borderRadius: 6,
              padding: '6px 8px', fontSize: 12,
            }}
          >
            {BLEND_MODES.map((m) => (<option key={m} value={m}>{m}</option>))}
          </select>

          {/* 混合强度 */}
          <SliderRow label="混合强度 blend_factor" value={p.blendFactor} min={0} max={1} step={0.05}
            onChange={(v) => set('blendFactor', v)} fmt={(v) => v.toFixed(2)} />
          <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 2 }}>
            0=纯A / 0.5=各半 / 1=纯B
          </div>
        </div>
      )}

      {/* v4.35: 风格一致性 IPAdapterStyleComposition */}
      {p.mode === 'style_consistency' && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>风格一致性 · IPAdapterStyle</div>
          <div style={{ fontSize: 12, color: theme.text.soft, marginBottom: 10 }}>
            上传一张风格参考图（如油画、水彩、赛博朋克、水墨风），将风格迁移到你的提示词生成中。
            推荐选择高对比度、特征明显的风格图片。
          </div>

          <div style={labelSm}>风格参考图</div>
          <label style={{ ...fileBtnStyle, marginTop: 6 }}>
            {styleUploadName ? '更换风格图' : '上传风格参考图'}
            <input type="file" accept="image/*" style={{ display: 'none' }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                (async () => {
                  if (!f) return;
                  setError(null);
                  try {
                    const dataUrl = await fileToBase64(f);
                    setStyleUploadPreview(dataUrl);
                    const name = await uploadImage(`style_${Date.now()}_${f.name}`, dataUrl);
                    setStyleUploadName(name);
                  } catch { setError('风格图上传失败'); }
                })();
              }} />
          </label>
          {styleUploadPreview && (
            <div style={{ marginTop: 8 }}>
              <img src={styleUploadPreview} alt="风格参考"
                style={{ width: '100%', maxHeight: 120, objectFit: 'contain', borderRadius: 6, border: `1px solid ${theme.border.subtle}` }} />
              <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 4 }}>
                {styleUploadName}
              </div>
            </div>
          )}
          {!styleUploadName && (
            <div style={{ marginTop: 6, fontSize: 12, color: theme.accent.amber }}>请上传风格参考图</div>
          )}

          <div style={{ marginTop: 12 }}>
            <SliderRow
              label="风格强度 style_weight"
              value={p.styleWeight}
              min={0.1} max={1.5} step={0.05}
              onChange={(v) => set('styleWeight', v)}
              fmt={(v) => v.toFixed(2)} />
          </div>
          <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 2 }}>
            推荐 0.5-0.8；越低越像提示词原图，越高风格越强烈
          </div>

          <div style={{ marginTop: 10 }}>
            <SliderRow
              label="构图影响 composition_weight"
              value={p.compositionWeight}
              min={0} max={1} step={0.05}
              onChange={(v) => set('compositionWeight', v)}
              fmt={(v) => v.toFixed(2)} />
          </div>
          <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 2 }}>
            0=构图完全由提示词决定 / 1=构图跟随参考图。推荐 0.1-0.4
          </div>
        </div>
      )}

      {/* v4.36: 场景一致性 IPAdapterApply */}
      {p.mode === 'scene_consistency' && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>场景一致性 · IPAdapter</div>
          <div style={{ fontSize: 12, color: theme.text.soft, marginBottom: 10 }}>
            上传一张场景参考图（如森林、城市、海滩、室内空间），保持场景的整体布局和空间结构，
            在提示词中自由替换内容元素。适合构建系列场景图。
          </div>

          <div style={labelSm}>场景参考图</div>
          <label style={{ ...fileBtnStyle, marginTop: 6 }}>
            {sceneUploadName ? '更换场景图' : '上传场景参考图'}
            <input type="file" accept="image/*" style={{ display: 'none' }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                (async () => {
                  if (!f) return;
                  setError(null);
                  try {
                    const dataUrl = await fileToBase64(f);
                    setSceneUploadPreview(dataUrl);
                    const name = await uploadImage(`scene_${Date.now()}_${f.name}`, dataUrl);
                    setSceneUploadName(name);
                  } catch { setError('场景图上传失败'); }
                })();
              }} />
          </label>
          {sceneUploadPreview && (
            <div style={{ marginTop: 8 }}>
              <img src={sceneUploadPreview} alt="场景参考"
                style={{ width: '100%', maxHeight: 120, objectFit: 'contain', borderRadius: 6, border: `1px solid ${theme.border.subtle}` }} />
              <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 4 }}>
                {sceneUploadName}
              </div>
            </div>
          )}
          {!sceneUploadName && (
            <div style={{ marginTop: 6, fontSize: 12, color: theme.accent.amber }}>请上传场景参考图</div>
          )}

          <div style={{ marginTop: 12 }}>
            <SliderRow
              label="场景保持力 scene_weight"
              value={p.sceneWeight}
              min={0.1} max={1.5} step={0.05}
              onChange={(v) => set('sceneWeight', v)}
              fmt={(v) => v.toFixed(2)} />
          </div>
          <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 2 }}>
            推荐 0.5-0.8；越低越像提示词原图，越高场景结构越强
          </div>
        </div>
      )}

      {/* v4.37: 道具一致性 IPAdapter */}
      {p.mode === 'prop_consistency' && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>道具一致性 · IPAdapter</div>
          <div style={{ fontSize: 12, color: theme.text.soft, marginBottom: 10 }}>
            上传一张道具/物品参考图（如武器、家具、装饰品、服装单品），保持道具的
            纹理、材质和视觉特征。适合生成不同角度或场景下的同一物品系列图。
          </div>

          <div style={labelSm}>道具参考图</div>
          <label style={{ ...fileBtnStyle, marginTop: 6 }}>
            {propUploadName ? '更换道具图' : '上传道具参考图'}
            <input type="file" accept="image/*" style={{ display: 'none' }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                (async () => {
                  if (!f) return;
                  setError(null);
                  try {
                    const dataUrl = await fileToBase64(f);
                    setPropUploadPreview(dataUrl);
                    const name = await uploadImage(`prop_${Date.now()}_${f.name}`, dataUrl);
                    setPropUploadName(name);
                  } catch { setError('道具图上传失败'); }
                })();
              }} />
          </label>
          {propUploadPreview && (
            <div style={{ marginTop: 8 }}>
              <img src={propUploadPreview} alt="道具参考"
                style={{ width: '100%', maxHeight: 120, objectFit: 'contain', borderRadius: 6, border: `1px solid ${theme.border.subtle}` }} />
              <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 4 }}>
                {propUploadName}
              </div>
            </div>
          )}
          {!propUploadName && (
            <div style={{ marginTop: 6, fontSize: 12, color: theme.accent.amber }}>请上传道具参考图</div>
          )}

          <div style={{ marginTop: 12 }}>
            <SliderRow
              label="道具保持力 prop_weight"
              value={p.propWeight}
              min={0.1} max={1.5} step={0.05}
              onChange={(v) => set('propWeight', v)}
              fmt={(v) => v.toFixed(2)} />
          </div>
          <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 2 }}>
            推荐 0.5-0.8；越低道具特征越弱，越高道具纹理材质越强
          </div>
        </div>
      )}

      {/* v4.38: 分镜编排 Storyboard */}
      {p.mode === 'storyboard' && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>分镜编排 · Storyboard</div>
          <div style={{ fontSize: 12, color: theme.text.soft, marginBottom: 10 }}>
            每行一个分镜提示词，描述一个独立镜头画面。全部镜头共享相同的模型和参数设置，
            并行生成后按顺序排列为故事板序列。最多支持 25 个分镜。
          </div>

          <div style={labelSm}>分镜提示词（每行一个镜头）</div>
          <textarea
            value={p.storyboardPrompts.join('\n')}
            onChange={(e) => set('storyboardPrompts', e.target.value.split('\n'))}
            placeholder={`分镜01：广角镜头，森林入口，清晨薄雾缭绕，阳光穿过树叶洒在小径上

分镜02：中景，主角站在岔路口，面对两条不同的道路，神情犹豫

分镜03：特写，主角的手握紧剑柄，下定决心

分镜04：远景，主角走进右侧小径，镜头缓缓拉升展现整片奇幻森林`}
            rows={10}
            style={{
              width: '100%', resize: 'vertical',
              padding: '8px 10px', borderRadius: 6,
              border: `1px solid ${theme.border.subtle}`,
              background: theme.bg.input,
              color: theme.text.primary,
              fontSize: 12, fontFamily: 'inherit', lineHeight: 1.6,
              outline: 'none', marginTop: 6,
            }}
          />
          <div style={{ fontSize: 11, color: theme.text.hint, marginTop: 4 }}>
            {p.storyboardPrompts.filter((s: string) => s.trim()).length} 个分镜 · 每行一个镜头描述
          </div>
        </div>
      )}

      {/* 参数面板（可折叠） */}
      <div style={cardStyle}>
        <CollapseHeader
          open={paramOpen}
          onToggle={() => setParamOpen(!paramOpen)}
          title="生成参数"
        />
        {paramOpen && (
          <>
        <div style={labelSm}>模型引擎</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 12, marginTop: 4 }}>
          <SegBtn small active={p.model === ''} onClick={() => set('model', '')} label="自动" />
          <SegBtn small active={p.model === 'qwen2'} onClick={() => set('model', 'qwen2')} label="Qwen-Image" />
          <SegBtn small active={p.model === 'sdxl'} onClick={() => set('model', 'sdxl')} label="NoobAI-XL" />
        </div>

        <div style={labelSm}>画幅</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
          {SIZE_PRESETS.map((sp) => (
            <SegBtn
              small
              key={sp.label}
              active={p.width === sp.w && p.height === sp.h}
              onClick={() => { set('width', sp.w); set('height', sp.h); }}
              label={sp.label}
            />
          ))}
        </div>

        <SliderRow label="步数 steps" value={p.steps} min={4} max={40} step={1}
          onChange={(v) => set('steps', v)} fmt={(v) => String(v)} />
        <SliderRow label="引导 CFG" value={p.cfg} min={1} max={12} step={0.5}
          onChange={(v) => set('cfg', v)} fmt={(v) => v.toFixed(1)} />
        <SliderRow label="批量张数" value={p.batchSize} min={1} max={4} step={1}
          onChange={(v) => set('batchSize', v)} fmt={(v) => String(v)} />

        <div style={{ marginTop: 10 }}>
          <div style={labelSm}>负向提示词（可选）</div>
          <input
            value={p.negative}
            onChange={(e) => set('negative', e.target.value)}
            placeholder="low quality, blurry, watermark"
            style={inputStyle}
          />
        </div>

        <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ fontSize: 12, color: theme.text.soft, display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={randomSeed} onChange={(e) => setRandomSeed(e.target.checked)} />
            随机种子
          </label>
          {!randomSeed && (
            <input
              type="number"
              value={p.seed}
              onChange={(e) => set('seed', Number(e.target.value) || 0)}
              style={{ ...inputStyle, width: 130 }}
            />
          )}
        </div>
          </>
        )}
      </div>

      {(p.mode === 'txt2vid' || p.mode === 'img2vid') && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: 8 }}>视频参数 · Wan2.2 {p.mode === 'txt2vid' ? '文生视频' : '图生视频'}</div>
          {/* v5.0: 速度/质量切换（LightX2V 4步蒸馏 vs 标准20步） */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
            <button
              onClick={() => set('videoQuality', 'speed')}
              style={{
                flex: 1, padding: '6px 0', borderRadius: 6, border: 'none',
                cursor: 'pointer', fontSize: 12, fontWeight: 600,
                background: p.videoQuality === 'speed' ? theme.accent.fuchsia : 'rgba(255,255,255,0.06)',
                color: p.videoQuality === 'speed' ? '#fff' : theme.text.gray,
              }}
            >⚡ 快速 (4步)</button>
            <button
              onClick={() => set('videoQuality', 'quality')}
              style={{
                flex: 1, padding: '6px 0', borderRadius: 6, border: 'none',
                cursor: 'pointer', fontSize: 12, fontWeight: 600,
                background: p.videoQuality === 'quality' ? theme.accent.blue : 'rgba(255,255,255,0.06)',
                color: p.videoQuality === 'quality' ? '#fff' : theme.text.gray,
              }}
            >🎬 质量 (20步)</button>
          </div>
          <SliderRow label="帧数" value={p.frames ?? 33} min={17} max={81} step={8}
            onChange={(v) => set('frames', v)} fmt={(v) => `${v}（4n+1）`} />
          <SliderRow label="帧率 FPS" value={p.fps ?? 16} min={8} max={30} step={1}
            onChange={(v) => set('fps', v)} fmt={(v) => `${v}`} />
          <div style={{ fontSize: 11, color: theme.text.gray, marginTop: 2 }}>
            {p.videoQuality === 'speed'
              ? 'LightX2V 4步蒸馏 · ~5x 加速 · 搭配 SageAttention 可再提速 2-3x'
              : '标准 20 步 · 高质量输出 · 建议 832×480；帧数须为 4n+1'}
          </div>
        </div>
      )}
      <div style={{ position: 'sticky', bottom: -16, margin: '16px -16px -16px', padding: 12, background: theme.bg.panel, borderTop: `1px solid ${theme.border.default}` }}>
        <button onClick={run} disabled={loading} style={genBtnStyle(loading)}>
          {loading
            ? (phase || '处理中…')
            : p.mode === 'outpaint' ? '扩图 ▶' : p.mode === 'inpaint' ? '局部重绘 ▶' : p.mode === 'img2img' ? '图生图 ▶' : p.mode === 'face_consistency' ? '角色一致 ▶' : p.mode === 'image_blend' ? '图像融合 ▶' : p.mode === 'style_consistency' ? '风格一致 ▶' : p.mode === 'scene_consistency' ? '场景一致 ▶' : p.mode === 'prop_consistency' ? '道具一致 ▶' : p.mode === 'storyboard' ? '分镜生成 ▶' : '生成 ▶'}
        </button>

      {/* v4.29: 实时进度条 */}
      {loading && progress && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: theme.text.dim, marginBottom: 4 }}>{progress.phase}</div>
          <div style={{ height: 4, borderRadius: 2, background: 'rgba(79,140,255,0.15)', overflow: 'hidden' }}>
            <div
              style={{
                height: '100%',
                width: `${Math.min(100, (progress.value / progress.max) * 100)}%`,
                borderRadius: 2,
                background: 'linear-gradient(90deg, #4f8cff, #a06bff)',
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <div style={{ fontSize: 10, color: theme.text.tiny, marginTop: 2, textAlign: 'right' }}>
            {progress.value}/{progress.max}
          </div>
        </div>
      )}
      </div>

      {error && <div style={errStyle}>{error}</div>}

      {/* 选中节点详情（可折叠） */}
      {selectedNode && (
        <div style={cardStyle}>
          <CollapseHeader
            open={selectedOpen}
            onToggle={() => setSelectedOpen(!selectedOpen)}
            title={`选中节点${selectedNode.kind === 'control' ? ' · ' + (selectedNode.controlKind === 'controlnet' ? 'ControlNet' : 'LoRA') : ' · ' + (MODE_META[selectedNode.mode || 'txt2img'].label)}`}
          />
          {selectedOpen && (<>          <div style={{ fontSize: 11, color: theme.text.hint, marginBottom: 8, marginTop: 2 }}>
            提示：在画布任意节点右侧黄色锚点按住，拖拽到另一节点即可建立关联
          </div>
          <span
            style={{
              display: 'inline-block', padding: '2px 8px', borderRadius: 5, fontSize: 12,
              fontWeight: 600, color: '#fff', background: MODE_META[selectedNode.mode || 'txt2img'].color,
              marginBottom: 8,
            }}
          >
            {MODE_META[selectedNode.mode || 'txt2img'].label}
            {selectedNode.parentId ? ' · 派生' : ' · 原创'}
          </span>
          {(selectedNode.kind === 'video' || /\.(mp4|webm|mov)$/i.test(selectedNode.filename || '')) && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, color: theme.accent.fuchsia, marginBottom: 4 }}>▶ 视频预览（点击播放）</div>
              <video controls autoPlay loop muted playsInline src={imageUrl(selectedNode.filename)} style={{ width: '100%', borderRadius: 8, background: '#000', maxHeight: 260 }} />
              <button
                onClick={() => {
                  const alreadyIn = timelineClips.some((c) => c.nodeId === selectedNode.id);
                  if (alreadyIn) return;
                  addToTimeline({
                    nodeId: selectedNode.id,
                    filename: selectedNode.filename,
                    frames: selectedNode.frames || 0,
                    fps: selectedNode.fps || 24,
                    prompt: selectedNode.prompt || '',
                  });
                  setTimelineOpen(true);
                }}
                disabled={timelineClips.some((c) => c.nodeId === selectedNode.id)}
                style={{
                  marginTop: 6, width: '100%', height: 28,
                  background: timelineClips.some((c) => c.nodeId === selectedNode.id)
                    ? '#1a2a1a' : theme.bg.card,
                  border: `1px solid ${theme.border.subtle}`,
                  borderRadius: 6, color: timelineClips.some((c) => c.nodeId === selectedNode.id)
                    ? theme.accent.emerald : theme.text.secondary,
                  fontSize: 12, cursor: timelineClips.some((c) => c.nodeId === selectedNode.id)
                    ? 'default' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
                  transition: 'all 0.15s',
                }}
              >
                {timelineClips.some((c) => c.nodeId === selectedNode.id)
                  ? '✅ 已加入时间轴'
                  : '⚡ 添加到时间轴'}
              </button>
            </div>
          )}
          <Row k="prompt" v={selectedNode.prompt} />
          <Row k="模板" v={selectedNode.templateId} />
          <Row k="种子" v={String(selectedNode.seed ?? '—')} />
          {selectedNode.parentId && (
            <Row k="源节点" v={`${selectedNode.parentId.slice(0, 8)}…`} />
          )}
          {selectedNode.createdAt && (
            <Row k="时间" v={new Date(selectedNode.createdAt).toLocaleString()} />
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button onClick={() => requestFocus(selectedNode.id)} style={miniBtn}>聚焦</button>
            <button
              onClick={() => { set('mode', 'img2img'); setError(null); }}
              style={miniBtn}
            >
              图生图输入
            </button>
            <button
              onClick={() => { set('mode', 'outpaint'); setError(null); }}
              style={miniBtn}
            >
              扩图源
            </button>
            {selectedNode.kind !== 'control' && (
              <>
                <button onClick={() => addControlNode(selectedNode.id, 'lora')} style={miniBtn}>
                  +LoRA
                </button>
                <button onClick={() => addControlNode(selectedNode.id, 'controlnet')} style={miniBtn}>
                  +ControlNet
                </button>
              </>
            )}
            <button onClick={() => removeNode(selectedNode.id)} style={{ ...miniBtn, color: theme.danger.text, borderColor: theme.danger.border }}>
              删除
            </button>
          </div>
          <LinkList selectedId={selectedNode.id} links={links} nodes={nodes} onRemove={removeLink} />
          </>)}
        </div>
      )}

      {/* 控制节点编辑面板（§6.22 LoRA / §6.23 ControlNet） */}
      {selectedNode?.kind === 'control' && (
        <div style={cardStyle}>
          <CollapseHeader
            open={controlOpen}
            onToggle={() => setControlOpen(!controlOpen)}
            title={`控制节点 · ${selectedNode.controlKind === 'controlnet' ? 'ControlNet' : 'LoRA'}`}
          />
          {controlOpen && (<>
          {selectedNode.controlKind === 'lora' ? (
            <>
              <div style={labelSm}>LoRA 模型</div>
              <select
                value={selectedNode.loraName || ''}
                onChange={(e) => updateNode(selectedNode.id, { loraName: e.target.value })}
                style={{ width: '100%', background: theme.bg.dropdown, color: theme.text.secondary, border: `1px solid ${theme.border.subtle}`, borderRadius: 6, padding: '6px 8px', fontSize: 12, marginBottom: 10 }}
              >
                {loras.length === 0 && <option value="">（无可用 LoRA）</option>}
                {loras.map((l) => (<option key={l} value={l}>{l}</option>))}
              </select>
              <SliderRow label="强度" value={selectedNode.loraStrength ?? 1.0} min={0} max={2} step={0.05}
                onChange={(v) => updateNode(selectedNode.id, { loraStrength: v })} fmt={(v) => v.toFixed(2)} />
            </>
          ) : (
            <>
              <div style={labelSm}>ControlNet 模型</div>
              <select
                value={selectedNode.controlModel || ''}
                onChange={(e) => updateNode(selectedNode.id, { controlModel: e.target.value })}
                style={{ width: '100%', background: theme.bg.dropdown, color: theme.text.secondary, border: `1px solid ${theme.border.subtle}`, borderRadius: 6, padding: '6px 8px', fontSize: 12, marginBottom: 10 }}
              >
                {controlnets.length === 0 && <option value="">（无可用 ControlNet）</option>}
                {controlnets.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
              {(selectedNode.controlModel || '').includes('union') && (
                <>
                  <div style={labelSm}>类型（union）</div>
                  <select
                    value={selectedNode.controlType || ''}
                    onChange={(e) => updateNode(selectedNode.id, { controlType: e.target.value })}
                    style={{ width: '100%', background: theme.bg.dropdown, color: theme.text.secondary, border: `1px solid ${theme.border.subtle}`, borderRadius: 6, padding: '6px 8px', fontSize: 12, marginBottom: 10 }}
                  >
                    {unionTypes.length === 0 && <option value="">（无类型）</option>}
                    {unionTypes.map((t) => (<option key={t} value={t}>{t}</option>))}
                  </select>
                </>
              )}
              <SliderRow label="强度" value={selectedNode.controlStrength ?? 1.0} min={0} max={2} step={0.05}
                onChange={(v) => updateNode(selectedNode.id, { controlStrength: v })} fmt={(v) => v.toFixed(2)} />
              {/* v4.30: ControlNet 参考图独立上传 */}
              <div style={labelSm}>参考图</div>
              {selectedNode.controlImage ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 4, overflow: 'hidden',
                    border: `1px solid ${theme.border.subtle}`, flex: '0 0 auto',
                  }}>
                    <img src={imageUrl(selectedNode.controlImage)} alt="control ref"
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  </div>
                  <div style={{ flex: 1, fontSize: 10, color: theme.text.secondary, wordBreak: 'break-all', lineHeight: 1.3 }}>
                    {selectedNode.controlImage}
                  </div>
                  <button onClick={() => updateNode(selectedNode.id, { controlImage: '' })}
                    style={{
                      border: `1px solid ${theme.border.subtle}`, background: theme.bg.surface,
                      color: theme.text.muted, borderRadius: 4, padding: '2px 6px', fontSize: 11, cursor: 'pointer',
                    }}>
                    清除
                  </button>
                </div>
              ) : (
                <div style={{ fontSize: 11, color: theme.text.hint, marginBottom: 8 }}>
                  未设置（默认使用目标图）
                </div>
              )}
              <label style={{
                display: 'inline-block', cursor: 'pointer', marginBottom: 10,
                padding: '5px 10px', borderRadius: 4, fontSize: 12,
                border: `1px solid ${theme.border.subtle}`,
                background: theme.bg.surface, color: theme.text.secondary,
              }}>
                {selectedNode.controlImage ? '更换参考图' : '上传参考图'}
                <input type="file" accept="image/*" style={{ display: 'none' }}
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    try {
                      const b64 = await fileToBase64(file);
                      const name = await uploadImage(file.name, b64);
                      updateNode(selectedNode.id, { controlImage: name });
                    } catch (err) {
                      setError('参考图上传失败：' + ((err as Error)?.message || String(err)));
                    }
                  }}
                />
              </label>
            </>
          )}
          <button onClick={() => applyControl()} disabled={loading} style={{ ...genBtnStyle(loading), marginTop: 10 }}>
            {loading ? (phase || '处理中…') : '应用控制 ▶'}
          </button>
          {!links.some((l) => l.from === selectedNode.id) && (
            <div style={{ marginTop: 8, fontSize: 12, color: theme.accent.amber }}>请拖拽本节点右侧锚点连线到目标图片节点</div>
          )}
          </>)}
        </div>
      )}

      {intent && (
        <div style={cardStyle}>
          <CollapseHeader
            open={true}
            onToggle={() => {}}
            title="解析意图（DeepSeek v4）"
          />
          <Row k="action" v={intent.action} />
          <Row k="subject" v={intent.subject} />
          <Row k="style" v={intent.style} />
          <Row k="elements" v={intent.elements.join('、') || '—'} />
        </div>
      )}

      {/* v4.31: 用户工作流模板保存/加载 */}
      <div style={cardStyle}>
        <CollapseHeader
          open={templateOpen}
          onToggle={() => setTemplateOpen(!templateOpen)}
          title={`工作流模板 (${templates.length})`}
        />
        {templateOpen && (<>
          {/* 保存当前画布为模板 */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            <input
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') {
                if (!templateName.trim()) return;
                saveTemplate(templateName.trim(), nodes, links).then(() => {
                  setTemplateName(''); loadTemplates();
                  setError(null);
                }).catch((err) => setError('保存模板失败：' + (err as Error).message));
              }}}
              placeholder="模板名称"
              style={{
                flex: 1, padding: '5px 8px', borderRadius: 4, fontSize: 12,
                background: theme.bg.input, color: theme.text.primary,
                border: `1px solid ${theme.border.subtle}`,
              }}
            />
            <button
              onClick={() => {
                if (!templateName.trim()) return;
                saveTemplate(templateName.trim(), nodes, links).then(() => {
                  setTemplateName(''); loadTemplates();
                  setError(null);
                }).catch((err) => setError('保存模板失败：' + (err as Error).message));
              }}
              disabled={loading}
              style={{
                padding: '5px 10px', borderRadius: 4, fontSize: 12, cursor: 'pointer',
                border: `1px solid ${theme.border.subtle}`,
                background: theme.bg.surface, color: theme.text.secondary,
              }}
            >
              保存
            </button>
          </div>

          {/* 已保存模板列表 */}
          {templates.length === 0 ? (
            <div style={{ fontSize: 11, color: theme.text.hint }}>暂无模板，保存当前画布以创建模板</div>
          ) : (
            <div style={{ maxHeight: 160, overflowY: 'auto' }}>
              {templates.map((t) => (
                <div key={t.name} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '4px 0', borderBottom: `1px solid ${theme.border.subtle}`,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: theme.text.primary, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {t.name}
                    </div>
                    <div style={{ fontSize: 10, color: theme.text.hint }}>
                      {t.node_count} 节点 · {new Date(t.saved_at * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      loadUserTemplate(t.name).then((data) => {
                        replaceAll(data.nodes as Parameters<typeof replaceAll>[0]);
                        setError(null);
                      }).catch((err) => setError('加载模板失败：' + (err as Error).message));
                    }}
                    style={{
                      padding: '2px 6px', borderRadius: 3, fontSize: 11, cursor: 'pointer',
                      border: `1px solid ${theme.border.subtle}`,
                      background: theme.bg.surface, color: theme.text.secondary,
                    }}
                  >
                    加载
                  </button>
                  <button
                    onClick={() => {
                      deleteUserTemplate(t.name).then(() => {
                        loadTemplates();
                      }).catch((err) => setError('删除模板失败：' + (err as Error).message));
                    }}
                    style={{
                      padding: '2px 6px', borderRadius: 3, fontSize: 11, cursor: 'pointer',
                      border: `1px solid ${theme.border.subtle}`,
                      background: 'transparent', color: theme.accent.danger,
                    }}
                  >
                    删除
                  </button>
                </div>
              ))}
            </div>
          )}
        </>)}
      </div>

      <div style={{ marginTop: 'auto', color: theme.text.hint, fontSize: 12 }}>
        画布节点：{nodeCount}（自动本地保存）
      </div>

      {maskOpen && (uploadPreview || selectedNode) && (
        <MaskEditor
          imageUrl={uploadPreview || imageUrl(selectedNode!.filename)}
          onConfirm={(url) => { setMaskDataUrl(url); setMaskOpen(false); }}
          onCancel={() => setMaskOpen(false)}
        />
      )}
    </aside>
  );
}

// ── 小组件 ──────────────────────────────────────────────
function CollapseHeader({ open, onToggle, title }: { open: boolean; onToggle: () => void; title: string }) {
  return (
    <div
      onClick={onToggle}
      style={{
        display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
        marginBottom: open ? 8 : 0, userSelect: 'none',
      }}
    >
      <span style={{
        display: 'inline-flex', width: 16, height: 16, alignItems: 'center', justifyContent: 'center',
        transition: 'transform 0.15s', transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
      }}>
        <svg width="10" height="10" viewBox="0 0 10 10"><path d="M3 1l4 4-4 4" stroke={theme.text.dim} strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round"/></svg>
      </span>
      <span style={{ fontSize: 13, fontWeight: 600, color: theme.text.label }}>{title}</span>
    </div>
  );
}

// ── v4.51 层级色彩 ────────────────────────────────────────────────
const LAYER_COLORS: Record<string, string> = { planning: '#f0a030', generation: '#4f8cff', output: '#44cc66' };

function SegBtn({ active, onClick, label, small, layer }: { active: boolean; onClick: () => void; label: string; small?: boolean; layer?: string }) {
  const accentColor = layer ? LAYER_COLORS[layer] || theme.accent.blue : theme.accent.blue;
  const accentIce = layer === 'planning' ? '#ffe8c0' : layer === 'output' ? '#c0ffd0' : theme.accent.ice;
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        padding: small ? '6px 4px' : '9px 8px',
        borderRadius: 7,
        border: `1px solid ${active ? accentColor : theme.border.card}`,
        background: active ? (layer === 'planning' ? '#2a1f10' : layer === 'output' ? '#102a18' : theme.bg.hoverStrong) : theme.bg.card,
        color: active ? accentIce : theme.text.soft,
        fontSize: small ? 12 : 13,
        fontWeight: active ? 600 : 400,
        cursor: 'pointer',
        whiteSpace: 'nowrap',
      }}
      onMouseEnter={(e) => {
        if (!active) (e.target as HTMLButtonElement).style.borderColor = accentColor;
      }}
      onMouseLeave={(e) => {
        if (!active) (e.target as HTMLButtonElement).style.borderColor = theme.border.card;
      }}
    >
      {label}
    </button>
  );
}

/** v4.51 层级上下文提示条 */
function PanelHint({ layer }: { layer: string }) {
  const hints: Record<string, { label: string; tip: string; color: string }> = {
    planning: { label: '策划层', tip: '分镜规划 / 概念设计', color: '#f0a030' },
    generation: { label: '生成层', tip: '图像 & 视频 AI 生成', color: '#4f8cff' },
    output: { label: '输出层', tip: '视频合成 / 导出发布', color: '#44cc66' },
  };
  const h = hints[layer] || hints.generation;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '4px 10px',
      background: `${h.color}12`,
      border: `1px solid ${h.color}40`,
      borderRadius: 6,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: h.color, flexShrink: 0 }} />
      <span style={{ fontSize: 11, fontWeight: 600, color: h.color }}>{h.label}</span>
      <span style={{ fontSize: 10, color: theme.text.hint }}>{h.tip}</span>
    </div>
  );
}

function SliderRow({ label, value, min, max, step, onChange, fmt }: {
  label: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void; fmt: (v: number) => string;
}) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
        <span style={labelSm}>{label}</span>
        <span style={{ fontSize: 12, color: theme.accent.ice, fontVariantNumeric: 'tabular-nums' }}>{fmt(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: theme.accent.blue }}
      />
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
      <span style={{ color: theme.text.hint, flexShrink: 0, width: 56 }}>{k}</span>
      <span style={{ color: theme.text.bright, wordBreak: 'break-all' }}>{v || '—'}</span>
    </div>
  );
}

function LinkList({ selectedId, links, nodes, onRemove }: {
  selectedId: string;
  links: Link[];
  nodes: CanvasNode[];
  onRemove: (id: string) => void;
}) {
  const rel = links.filter((l) => l.from === selectedId || l.to === selectedId);
  if (rel.length === 0) {
    return <div style={{ marginTop: 12, fontSize: 12, color: theme.text.hint }}>暂无手动关联</div>;
  }
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ ...labelSm, marginBottom: 6 }}>手动关联（{rel.length}）</div>
      {rel.map((l) => {
        const otherId = l.from === selectedId ? l.to : l.from;
        const other = nodes.find((n) => n.id === otherId);
        const label = (other?.prompt || other?.filename || otherId).slice(0, 14);
        return (
          <div key={l.id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: theme.text.stream, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {l.from === selectedId ? '→ ' : '← '} {label}
            </span>
            <button
              onClick={() => onRemove(l.id)}
              style={{ ...miniBtn, flex: 'none', width: 52, color: theme.danger.text, borderColor: theme.danger.border }}
            >
              断开
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ── 样式 ────────────────────────────────────────────────
const panelStyle: React.CSSProperties = {
  width: 320, flexShrink: 0, borderRight: `1px solid ${theme.border.default}`, padding: 16,
  display: 'flex', flexDirection: 'column', gap: 12, overflowY: 'auto', background: theme.bg.panel,
};
const labelStyle: React.CSSProperties = { fontSize: 13, color: theme.text.label, marginBottom: 6 };
const labelSm: React.CSSProperties = { fontSize: 12, color: theme.text.faint };
const cardStyle: React.CSSProperties = { background: theme.bg.card, border: `1px solid ${theme.border.card}`, borderRadius: 8, padding: 12, fontSize: 13 };
const textareaStyle: React.CSSProperties = {
  width: '100%', resize: 'vertical', background: theme.bg.card, color: theme.text.primary,
  border: `1px solid ${theme.border.card}`, borderRadius: 8, padding: 10, fontSize: 14, lineHeight: 1.5,
  minHeight: 84,
};
const inputStyle: React.CSSProperties = {
  width: '100%', background: theme.bg.input, color: theme.text.primary, border: `1px solid ${theme.border.card}`,
  borderRadius: 6, padding: '7px 9px', fontSize: 13,
};
const fileBtnStyle: React.CSSProperties = {
  display: 'inline-block', padding: '7px 14px', borderRadius: 7, border: `1px dashed ${theme.border.dashed}`,
  background: theme.bg.input, color: theme.accent.ice, fontSize: 13, cursor: 'pointer',
};
const errStyle: React.CSSProperties = {
  background: theme.danger.bg, color: theme.danger.text, border: `1px solid ${theme.danger.border}`, borderRadius: 8, padding: 10, fontSize: 13,
};
const miniBtn: React.CSSProperties = {
  flex: 1, padding: '6px 4px', borderRadius: 6, border: `1px solid ${theme.border.card}`,
  background: theme.bg.card, color: theme.text.tertiary, fontSize: 12, cursor: 'pointer', whiteSpace: 'nowrap',
};
function genBtnStyle(loading: boolean): React.CSSProperties {
  return {
    width: '100%', padding: '12px 14px', borderRadius: 8, border: 'none',
    background: loading ? theme.accent.night : 'linear-gradient(90deg, #4f8cff, #8b5cf6)', color: '#fff',
    fontSize: 15, fontWeight: 600, cursor: loading ? 'default' : 'pointer',
    boxShadow: '0 4px 14px rgba(79,140,255,0.25)',
    transition: 'transform 0.1s ease, box-shadow 0.2s ease',
  };
}
