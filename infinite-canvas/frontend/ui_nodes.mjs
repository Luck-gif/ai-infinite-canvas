// 节点可视化 e2e：文生图 → 选中节点 → 图生图 → 验证血缘 parentId 落库 + 连线渲染
import { chromium } from 'playwright';

const BASE = process.env.BASE || 'http://localhost:5173';
const KEY = 'infinite-canvas.nodes.v1';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(m.text());
  if (m.text().includes('[persist]')) console.log('>>>', m.text());
});
page.on('pageerror', (e) => errors.push(String(e)));

const nodeCount = () => page.evaluate((k) => {
  try { const a = JSON.parse(localStorage.getItem(k)); return Array.isArray(a) ? a.length : (a?.nodes?.length || 0); } catch { return 0; }
}, KEY);

try {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.evaluate((k) => localStorage.removeItem(k), KEY);
  await sleep(400);

  // 1) 文生图
  await page.getByRole('button', { name: '生成 ▶', exact: true }).click();
  await page.waitForFunction(
    (k) => { try { const a = JSON.parse(localStorage.getItem(k)); const n = Array.isArray(a) ? a : (a?.nodes || []); return n.length >= 1; } catch { return false; } },
    KEY, { timeout: 90000 },
  );
  const n1 = (await page.evaluate((k) => { const a = JSON.parse(localStorage.getItem(k)); return Array.isArray(a) ? a : a.nodes; }, KEY))[0];
  if (!n1) throw new Error('node1 missing');
  if (n1.parentId) throw new Error('origin node should have no parent');
  console.log('N1 ok mode=', n1.mode, 'parent=', n1.parentId);

  // 2) 在画布上点击选中节点 1（默认视图 scale=1, x=0,y=0 → 屏幕坐标即节点左上）
  const box = await page.locator('canvas').first().boundingBox();
  await page.mouse.click(box.x + 150, box.y + 150);
  await page.getByText('选中节点', { exact: true }).waitFor({ timeout: 5000 });
  console.log('NODE SELECTED (panel visible), count=', await nodeCount());

  // 3) 切到图生图（以选中节点为输入）并生成
  await page.getByRole('button', { name: '图生图', exact: true }).click();
  await page.getByRole('button', { name: '图生图 ▶', exact: true }).click();
  await page.waitForFunction(
    (k) => { try { const a = JSON.parse(localStorage.getItem(k)); const n = Array.isArray(a) ? a : (a?.nodes || []); return n.length >= 2; } catch { return false; } },
    KEY, { timeout: 90000 },
  );

  const nodes = await page.evaluate((k) => { const a = JSON.parse(localStorage.getItem(k)); return Array.isArray(a) ? a : a.nodes; }, KEY);
  const child = nodes.find((n) => n.parentId);
  if (!child) throw new Error('no derived node with parentId');
  if (child.parentId !== n1.id) throw new Error(`parentId mismatch: ${child.parentId} != ${n1.id}`);
  console.log('CHILD ok id=', child.id.slice(0, 8), 'parent=', child.parentId.slice(0, 8), 'mode=', child.mode);

  await sleep(800);
  await page.screenshot({ path: 'ui_nodes_lineage.png' });

  if (errors.length) throw new Error('console errors: ' + errors.join(' | '));
  console.log('UI_NODE_VIZ_PASSED');
} catch (e) {
  console.error('UI_NODE_VIZ_FAILED:', e.message);
  const lc = await nodeCount().catch(() => -1);
  console.error('current node count=', lc);
  process.exitCode = 1;
} finally {
  await browser.close();
}
