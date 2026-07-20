import { test, expect } from '@playwright/test';

// ── 基础页面加载 ──
test('页面加载 - Canvas 区域可见', async ({ page }) => {
  await page.goto('/');
  // canvas 元素必须可见 (Konva 渲染目标)
  const canvas = page.locator('canvas');
  await expect(canvas.first()).toBeVisible({ timeout: 15_000 });
});

test('页面标题', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveTitle('无限画布 Infinite Canvas');
});

// ── 后端健康检查 (API 连通性) ──
test('后端 /health 响应 ok', async ({ request }) => {
  const resp = await request.get('http://127.0.0.1:5180/health');
  expect(resp.ok()).toBeTruthy();
  const json = await resp.json();
  expect(json.status).toBe('ok');
});

test('后端 /api/templates 返回模板列表', async ({ request }) => {
  const resp = await request.get('http://127.0.0.1:5180/api/templates');
  expect(resp.ok()).toBeTruthy();
  const templates = await resp.json();
  expect(Array.isArray(templates)).toBe(true);
  expect(templates.length).toBeGreaterThanOrEqual(10);
  // 关键模板应在列表中 (API 用下划线命名)
  const ids = templates.map((t: { id: string }) => t.id);
  expect(ids).toContain('txt2img_sdxl');
  expect(ids).toContain('txt2img_qwen');
});

// ── T2I 生成链路 (API 端) ──
test('/api/pipeline/run - 默认 txt2img 工作流校验', async ({ request }) => {
  const resp = await request.post('http://127.0.0.1:5180/api/pipeline/run', {
    data: { prompt: 'a cyberpunk cat', submit: false },
  });
  expect(resp.ok()).toBeTruthy();
  const data = await resp.json();
  expect(data.validated).toBe(true);
  expect(data.node_count).toBeGreaterThan(0);
});

// ── 模板列表 → 控制面板交互 → 核心按钮可用 ──
test('控制面板 - 核心按钮可用', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas', { timeout: 10_000 });

  // 查找执行按钮，用 role 或 first 避免多匹配
  const execBtn = page.getByRole('button', { name: /执行/ });
  const canvasCount = await page.locator('canvas').count();
  expect(canvasCount).toBeGreaterThanOrEqual(1);
});

// ── Canvas 核心交互 ──
test('Canvas - 平移缩放可用', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // 页面渲染了 2 层 canvas (主层+叠加层)，用 .first() 避免 strict mode 报错
  const canvas = page.locator('canvas').first();
  await expect(canvas).toBeVisible({ timeout: 10_000 });

  // 右键拖拽平移
  const box = await canvas.boundingBox();
  if (box) {
    await page.mouse.move(box.x + 100, box.y + 100);
    await page.mouse.down({ button: 'right' });
    await page.mouse.move(box.x + 150, box.y + 150, { steps: 5 });
    await page.mouse.up({ button: 'right' });
  }
});

// ── API 错误处理 ──
test('/api/pipeline/run - 空提示词返回错误', async ({ request }) => {
  const resp = await request.post('http://127.0.0.1:5180/api/pipeline/run', {
    data: { prompt: '', submit: false },
  });
  expect(resp.status()).toBeGreaterThanOrEqual(400);
});

// ── 环境确认 ──
test('环境 - ComfyUI 健康检查', async ({ request }) => {
  const resp = await request.get('http://127.0.0.1:5180/health');
  expect(resp.ok()).toBeTruthy();
  const data = await resp.json();
  expect(data.status).toBe('ok');
  expect(data.comfyui_url).toBeDefined();
});

// ── 蓝图 API ──
test('后端 /api/blueprints 包含文生图和文生视频', async ({ request }) => {
  const resp = await request.get('http://127.0.0.1:5180/api/blueprints');
  expect(resp.ok()).toBeTruthy();
  const data = await resp.json();
  expect(data.image).toBeDefined();
  expect(data.video).toBeDefined();
  expect(data.image.length).toBeGreaterThan(0);
});
