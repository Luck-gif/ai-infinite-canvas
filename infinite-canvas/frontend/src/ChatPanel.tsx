// 无限画布 v5.3 · Agent 对话面板（自然语言 → 意图解析 → 画布生成）
import { useState, useRef, useEffect, useCallback } from 'react';
import { parseIntent, generate, imageUrl, generateStoryboard } from './api';
import { useCanvasStore } from './store';
import { theme } from './theme';
import type { Intent, CanvasNode } from './types';

// ── 消息类型 ───────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  role: 'user' | 'agent' | 'system';
  text: string;
  intent?: Intent | null;
  images?: string[];
  promptId?: string;
  timestamp: number;
}

// ── 快捷指令 ───────────────────────────────────────────────────

const QUICK_COMMANDS = [
  { label: '生成图片', prompt: '生成一张图片：' },
  { label: '分镜编排', prompt: '帮我规划分镜：' },
  { label: '图生图', prompt: '用这张参考图生成：' },
  { label: '视频', prompt: '生成一段视频：' },
  { label: '角色', prompt: '创建一个角色：' },
  { label: '清理', prompt: '/clear' },
];

const WELCOME_MSG: ChatMessage = {
  id: 'welcome',
  role: 'agent',
  text: '你好！我是无限画布 Agent。用自然语言告诉我你想创作什么：\n\n• **生成图片**："画一只猫在月光下"\n• **分镜编排**："帮我做5个太空站的分镜"\n• **创作角色**："创建一个白发红瞳的少女角色"\n• **生成视频**："把这张图变成动态视频"\n\n直接说就好 🎨',
  timestamp: Date.now(),
};

// ── 组件 ───────────────────────────────────────────────────────

interface ChatPanelProps {
  onClose: () => void;
}

export function ChatPanel({ onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MSG]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [statusText, setStatusText] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const addNode = useCanvasStore((s) => s.addNode);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, statusText]);

  // 发送消息
  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;

    if (trimmed === '/clear') {
      setMessages([WELCOME_MSG]);
      setInput('');
      return;
    }

    setInput('');
    setBusy(true);

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: 'user', text: trimmed, timestamp: Date.now() };
    setMessages((prev) => [...prev, userMsg]);

    try {
      // 第一步：解析意图
      setStatusText('正在理解意图…');
      const intent = await parseIntent(trimmed);

      const intentSummary = formatIntent(intent);
      const intentMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'agent',
        text: intentSummary,
        intent,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, intentMsg]);

      // 第二步：判断是否为分镜
      const isStoryboard = intent.action === 'storyboard';

      if (isStoryboard) {
        // 分镜模式 — 批量生成
        // v5.3.1: 优先使用 LLM 返回的 shots（含英文 prompt），
        // 不再回退到中文 subject（会被 NoobAI-XL 误解为动漫角色）
        const shotPrompts = (intent.shots && intent.shots.length > 0)
          ? intent.shots.map(s => s.prompt).filter(Boolean)
          : intent.elements.length > 0
            ? intent.elements
            : [intent.params?.prompt || trimmed];

        if (!shotPrompts.length || !shotPrompts[0]) {
          setStatusText('');
          const errMsg: ChatMessage = {
            id: crypto.randomUUID(), role: 'agent',
            text: '无法解析分镜描述，请提供更详细的场景描述（如"太空站外景、星际飞船内部、宇航员特写"）。',
            timestamp: Date.now(),
          };
          setMessages((prev) => [...prev, errMsg]);
          setBusy(false);
          return;
        }

        setStatusText(`正在生成 ${shotPrompts.length} 个分镜…`);
        const sbResult = await generateStoryboard({
          prompts: shotPrompts,
          width: intent.params?.width ?? 1024,
          height: intent.params?.height ?? 1024,
          steps: intent.params?.steps ?? 20,
          cfg: intent.params?.cfg ?? 7,
          seed: (intent.params?.seed ?? 0) as number,
        });

        if (sbResult.validated && sbResult.frames) {
          // 将分镜帧添加到画布
          sbResult.frames.forEach((frame, i) => {
            if (frame.image) {
              const node: CanvasNode = {
                id: `chat-sb-${Date.now()}-${i}`,
                filename: frame.image,
                prompt: frame.prompt,
                templateId: 'storyboard',
                x: 100 + (i % 3) * 360,
                y: 80 + Math.floor(i / 3) * 300,
                width: 1024,
                height: 1024,
                mode: 'storyboard',
                kind: 'image',
                createdAt: Date.now(),
              };
              addNode(node);
            }
          });

          const doneMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: 'agent',
            text: `分镜生成完成：${sbResult.frames.length} 帧已添加到画布`,
            images: sbResult.frames.map((f) => f.image).filter(Boolean) as string[],
            timestamp: Date.now(),
          };
          setMessages((prev) => [...prev, doneMsg]);
        }
      } else {
        // ── v5.3.1 根据 intent.action 路由到不同工作流 ──
        // 之前所有动作都走同一个 generate()，没有传 batch_size/input_image
        // img2vid 降级为 txt2img → 生成动漫画风图片而非视频
        const action = intent.action || 'txt2img';
        const isVideo = action === 'txt2vid' || action === 'img2vid';
        const needsInput = action === 'img2img' || action === 'img2vid' || action === 'inpaint' || action === 'outpaint';

        // 需要底图的动作：从画布获取已选中节点作为 input_image
        let inputImage: string | null = null;
        if (needsInput) {
          const store = useCanvasStore.getState();
          const selectedIds = store.getAllSelectedIds();
          if (selectedIds.length > 0) {
            const selectedNode = store.nodes.find((n) => n.id === selectedIds[0]);
            if (selectedNode?.filename) {
              inputImage = selectedNode.filename;
            }
          }
          if (!inputImage) {
            const actionName = actionLabel(action);
            const errMsg: ChatMessage = {
              id: crypto.randomUUID(),
              role: 'system',
              text: `「${actionName}」需要一张参考图片。\n请先在画布上点击选中一个图片节点，再发送此指令。`,
              timestamp: Date.now(),
            };
            setMessages((prev) => [...prev, errMsg]);
            setBusy(false);
            setStatusText('');
            return;
          }
        }

        // batch_size：LLM 放在 params.count 或 params.batch_size（如"需要5张"）
        const batch = (intent.params?.batch_size ?? intent.params?.count ?? 1) as number;
        const frameCount = (intent.params?.frames ?? 16) as number;  // 视频默认 16 帧
        const videoH = (intent.params?.height ?? 576) as number;      // 视频默认 16:9

        setStatusText(isVideo ? '正在生成视频…' : '正在生成…');
        const result = await generate({
          intent: intent as unknown as Record<string, unknown>,
          prompt: intent.params?.prompt || trimmed,
          width: intent.params?.width ?? (isVideo ? 1024 : 1024),
          height: isVideo ? videoH : (intent.params?.height ?? 1024),
          steps: intent.params?.steps ?? (isVideo ? 8 : 20),
          cfg: intent.params?.cfg ?? (isVideo ? 1.0 : 7),
          seed: (intent.params?.seed as number | undefined) ?? 0,
          checkpoint: intent.params?.model,
          negative: intent.params?.negative_prompt,
          batch_size: batch as number,
          input_image: inputImage,
          denoise: (intent.params?.denoise as number | undefined) ?? (action === 'inpaint' ? 1.0 : 0.6),
          frames: isVideo ? frameCount : undefined,
          fps: (intent.params?.fps as number | undefined) ?? 8,
          video_quality: intent.params?.video_quality as 'speed' | 'quality' | undefined,
        });

        if (result.validated && result.images?.length) {
          // 根据实际动作类型创建不同 node（mode/kind 不再硬编码 txt2img/image）
          const baseX = 150;
          const baseY = 100;
          result.images.forEach((img, i) => {
            const node: CanvasNode = {
              id: `chat-gen-${Date.now()}-${i}`,
              filename: img,
              prompt: trimmed,
              templateId: action,
              x: baseX + i * 40 + Math.random() * 60,
              y: baseY + i * 40 + Math.random() * 60,
              width: intent.params?.width ?? 1024,
              height: isVideo ? videoH : (intent.params?.height ?? 1024),
              mode: (isVideo ? 'txt2vid' : action) as CanvasNode['mode'],
              kind: isVideo ? 'video' : 'image',
              frames: isVideo ? frameCount : undefined,
              fps: isVideo ? ((intent.params?.fps ?? 8) as number) : undefined,
              createdAt: Date.now(),
            };
            addNode(node);
          });

          const label = isVideo ? '视频' : '张图片';
          const doneMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: 'agent',
            text: `生成完成！${result.images.length} ${label}已添加到画布`,
            images: result.images,
            promptId: result.prompt_id,
            timestamp: Date.now(),
          };
          setMessages((prev) => [...prev, doneMsg]);
        } else if (result.issues?.length) {
          const errMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: 'system',
            text: `生成遇到问题：${result.issues.join('；')}`,
            timestamp: Date.now(),
          };
          setMessages((prev) => [...prev, errMsg]);
        }

        if (result.workflow) {
          useCanvasStore.getState().setLiveWorkflow(result.workflow);
        }
      }
    } catch (e) {
      const errMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'system',
        text: `请求失败：${(e as Error).message || '未知错误'}。请确认后端服务已启动。`,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setBusy(false);
      setStatusText('');
    }
  }, [busy, addNode]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  const handleQuickCmd = (prompt: string) => {
    if (prompt === '/clear') {
      send(prompt);
      return;
    }
    setInput(prompt);
    inputRef.current?.focus();
  };

  return (
    <div style={{
      position: 'fixed',
      bottom: 16,
      right: 16,
      width: 400,
      maxHeight: 'calc(100vh - 100px)',
      background: theme.bg.panel,
      borderRadius: theme.radius.lg,
      border: `1px solid ${theme.border.default}`,
      boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 200,
      animation: 'chat-slide-up 0.25s ease',
    }}>
      <style>{`@keyframes chat-slide-up{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}`}</style>

      {/* ── 头部 ── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 14px',
        borderBottom: `1px solid ${theme.border.default}`,
        background: theme.bg.header,
        borderRadius: `${theme.radius.lg}px ${theme.radius.lg}px 0 0`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 15 }}>🤖</span>
          <span style={{ fontSize: 14, fontWeight: 600, color: theme.text.primary }}>Agent 对话</span>
          {busy && (
            <span style={{ fontSize: 11, color: theme.accent.blue }}>
              {statusText}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'transparent',
            border: 'none',
            color: theme.text.muted,
            cursor: 'pointer',
            fontSize: 16,
            padding: '2px 6px',
            borderRadius: 4,
          }}
        >✕</button>
      </div>

      {/* ── 快捷指令 ── */}
      <div style={{
        display: 'flex',
        gap: 6,
        padding: '8px 12px',
        borderBottom: `1px solid ${theme.border.subtle}`,
        flexWrap: 'wrap',
      }}>
        {QUICK_COMMANDS.map((cmd) => (
          <button
            key={cmd.label}
            onClick={() => handleQuickCmd(cmd.prompt)}
            disabled={busy}
            style={{
              padding: '3px 10px',
              borderRadius: 12,
              border: `1px solid ${theme.border.subtle}`,
              background: theme.bg.card,
              color: theme.text.muted,
              fontSize: 11,
              cursor: busy ? 'not-allowed' : 'pointer',
              opacity: busy ? 0.5 : 1,
              transition: 'border-color 0.15s',
              whiteSpace: 'nowrap',
            }}
            onMouseEnter={(e) => {
              if (!busy) (e.target as HTMLButtonElement).style.borderColor = theme.accent.blue;
            }}
            onMouseLeave={(e) => {
              (e.target as HTMLButtonElement).style.borderColor = theme.border.subtle;
            }}
          >
            {cmd.label}
          </button>
        ))}
      </div>

      {/* ── 消息列表 ── */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          minHeight: 200,
          maxHeight: 420,
          overflowY: 'auto',
          padding: '12px',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        {messages.map((msg) => (
          <ChatBubble key={msg.id} msg={msg} />
        ))}

        {/* 加载指示器 */}
        {busy && statusText && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 4 }}>
            <TypingDots />
            <span style={{ fontSize: 12, color: theme.text.hint }}>{statusText}</span>
          </div>
        )}
      </div>

      {/* ── 输入区域 ── */}
      <div style={{
        padding: '10px 12px',
        borderTop: `1px solid ${theme.border.default}`,
        display: 'flex',
        gap: 8,
        alignItems: 'flex-end',
      }}>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={busy}
          placeholder="描述你想要创作的内容…"
          rows={1}
          style={{
            flex: 1,
            resize: 'none',
            padding: '8px 12px',
            borderRadius: theme.radius.md,
            border: `1px solid ${theme.border.default}`,
            background: theme.bg.input,
            color: theme.text.primary,
            fontSize: 13,
            fontFamily: 'inherit',
            outline: 'none',
            maxHeight: 100,
          }}
        />
        <button
          onClick={() => send(input)}
          disabled={busy || !input.trim()}
          style={{
            padding: '8px 14px',
            borderRadius: theme.radius.md,
            border: 'none',
            background: busy || !input.trim()
              ? theme.bg.card
              : theme.accent.blue,
            color: busy || !input.trim()
              ? theme.text.hint
              : '#fff',
            fontSize: 13,
            fontWeight: 600,
            cursor: busy || !input.trim() ? 'not-allowed' : 'pointer',
            transition: 'background 0.15s',
          }}
        >
          发送
        </button>
      </div>
    </div>
  );
}

// ── 消息气泡 ───────────────────────────────────────────────────

function ChatBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user';
  const isSystem = msg.role === 'system';

  const bubbleBg = isUser
    ? '#1a3a5c'
    : isSystem
      ? theme.danger.bg
      : theme.bg.card;

  const bubbleBorder = isUser
    ? '#2a5a8c'
    : isSystem
      ? theme.danger.border
      : theme.border.card;

  const align = isUser ? 'flex-end' : 'flex-start';

  // 渲染意图卡片
  const intentCard = msg.intent ? (
    <div style={{
      marginTop: 6,
      padding: '6px 10px',
      background: 'rgba(79,140,255,0.08)',
      borderRadius: 6,
      border: `1px solid rgba(79,140,255,0.2)`,
      fontSize: 11,
    }}>
      <div style={{ color: theme.accent.blue, fontWeight: 600, marginBottom: 3 }}>
        {actionLabel(msg.intent.action)}
      </div>
      <div style={{ color: theme.text.muted }}>
        主题：{msg.intent.subject || '未识别'}
        {msg.intent.style && ` · 风格：${msg.intent.style}`}
      </div>
      {msg.intent.elements && msg.intent.elements.length > 0 && (
        <div style={{ color: theme.text.hint, marginTop: 2 }}>
          元素：{msg.intent.elements.slice(0, 5).join('、')}
        </div>
      )}
    </div>
  ) : null;

  // 渲染生成的图片预览
  const imagePreviews = msg.images && msg.images.length > 0 ? (
    <div style={{
      display: 'flex',
      gap: 6,
      marginTop: 8,
      flexWrap: 'wrap',
    }}>
      {msg.images.slice(0, 4).map((img, i) => (
        <img
          key={i}
          src={imageUrl(img)}
          alt={`生成结果 ${i + 1}`}
          style={{
            width: 80,
            height: 80,
            objectFit: 'cover',
            borderRadius: 6,
            border: `1px solid ${theme.border.card}`,
            cursor: 'pointer',
          }}
          onClick={() => window.open(imageUrl(img), '_blank')}
        />
      ))}
      {msg.images.length > 4 && (
        <span style={{ fontSize: 11, color: theme.text.hint, alignSelf: 'flex-end' }}>
          +{msg.images.length - 4} 张
        </span>
      )}
    </div>
  ) : null;

  // 简单 Markdown 文本（安全渲染，避免用户注入 HTML）
  const textHtml = msg.text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br/>');

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: align,
      maxWidth: '100%',
    }}>
      <div style={{
        padding: '8px 12px',
        borderRadius: theme.radius.md,
        background: bubbleBg,
        border: `1px solid ${bubbleBorder}`,
        maxWidth: '90%',
        wordBreak: 'break-word',
        fontSize: 13,
        lineHeight: 1.5,
        color: isSystem ? theme.danger.text : theme.text.secondary,
      }}>
        <span dangerouslySetInnerHTML={{ __html: textHtml }} />
        {intentCard}
        {imagePreviews}
      </div>
      <span style={{
        fontSize: 10,
        color: theme.text.tiny,
        marginTop: 2,
        padding: '0 4px',
      }}>
        {new Date(msg.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
      </span>
    </div>
  );
}

// ── 输入指示器 ─────────────────────────────────────────────────

function TypingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: theme.accent.blue,
            animation: `chat-dot-bounce 0.6s ${i * 0.15}s infinite alternate`,
          }}
        />
      ))}
      <style>{`@keyframes chat-dot-bounce{from{opacity:.3;transform:translateY(0)}to{opacity:1;transform:translateY(-3px)}}`}</style>
    </span>
  );
}

// ── 工具函数 ──────────────────────────────────────────────────

function formatIntent(intent: Intent): string {
  const action = actionLabel(intent.action);
  const subject = intent.subject || '未指定主题';
  const style = intent.style ? `【${intent.style}】` : '';
  const parts = [
    `已理解：${action}`,
    `主题：${subject}${style}`,
  ];
  // v5.3.1: 优先展示 shots 的剧情大纲（LLM 分解的镜头梗概）
  const shotList = intent.shots ?? [];
  if (shotList.length > 0) {
    parts.push('');
    parts.push(`🎬 分镜大纲（${shotList.length} 个镜头）：`);
    shotList.slice(0, 8).forEach((s) => {
      const desc = s.description || s.prompt?.slice(0, 50) || s.shot_id;
      parts.push(`  ${s.shot_id}. ${desc}`);
    });
    if (shotList.length > 8) {
      parts.push(`  … 还有 ${shotList.length - 8} 个镜头`);
    }
  } else if (intent.elements?.length) {
    parts.push(`关键元素：${intent.elements.slice(0, 6).join('、')}`);
  }
  return parts.join('\n');
}

function actionLabel(action: string): string {
  const map: Record<string, string> = {
    txt2img: '文生图 🖼️',
    img2img: '图生图 🔄',
    txt2vid: '文生视频 🎬',
    img2vid: '图生视频 🎥',
    inpaint: '局部重绘 ✏️',
    outpaint: '扩图 📐',
    storyboard: '分镜编排 📋',
    audio: '音频生成 🎵',
    generate: '生成',
    character: '角色创建 👤',
    entity: '实体管理 📦',
  };
  return map[action] || action;
}
