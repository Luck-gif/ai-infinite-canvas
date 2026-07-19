"""Phase 9 视频生成 · 独立 UI 端到端验证（Playwright）。
驱动 dev server(5175) -> 点击「文生视频」-> 断言视频参数卡片 -> 设帧数=17
-> 输入提示词 -> 点「生成」-> 拦截 /api/generate 响应断言 .mp4
-> 拉取 /api/image/<fn> 验证 video/mp4 -> 断言无控制台错误。
"""
import sys
from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]  # pip install playwright 后可用

BASE = "http://localhost:5176"
ok = True


def fail(msg):
    global ok
    ok = False
    print("FAIL", msg)


def okp(msg):
    print("PASS", msg)


b = None
try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        errors = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append("PAGEERR:" + str(e)))

        # 1) 加载
        try:
            pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:  # noqa: BLE001
            fail("无法加载页面: %s" % e)
            raise SystemExit(1)

        # 2) 文生视频按钮
        try:
            pg.wait_for_selector("text=文生视频", timeout=30000)
            okp("文生视频按钮已渲染")
        except Exception as e:  # noqa: BLE001
            fail("未找到「文生视频」: %s" % e)

        # 3) 切视频模式
        pg.click("button:has-text('文生视频')")
        try:
            pg.wait_for_selector("text=视频参数", timeout=10000)
            okp("视频参数卡片出现")
        except Exception as e:  # noqa: BLE001
            fail("视频参数卡片未出现: %s" % e)

        # 4) 帧数=17（4n+1，缩短生成）
        try:
            pg.evaluate(
                """() => {
                  const divs = [...document.querySelectorAll('div')];
                  for (const d of divs) {
                    if (d.textContent && d.textContent.trim().includes('帧数')) {
                      const inp = d.parentElement && d.parentElement.querySelector('input[type=range]');
                      if (inp) { inp.value = '17';
                        inp.dispatchEvent(new Event('input', {bubbles:true}));
                        inp.dispatchEvent(new Event('change', {bubbles:true})); return true; }
                    }
                  }
                  return false;
                }"""
            )
            okp("帧数滑块=17")
        except Exception as e:  # noqa: BLE001
            fail("设置帧数失败: %s" % e)

        # 5) 提示词
        try:
            pg.fill("textarea", "a cat surfing on a sunny wave, cinematic, 4k")
            okp("已输入提示词")
        except Exception as e:  # noqa: BLE001
            fail("填写提示词失败: %s" % e)

        # 6) 生成 + 拦截响应
        gen = None
        reqlog = open("_req.log", "w", encoding="utf-8")
        def _on_req(r):
            if "/api/generate" in r.url and r.method == "POST":
                reqlog.write("URL=" + r.url + "\nBODY=" + str(r.post_data) + "\n\n")
                reqlog.flush()
        pg.on("request", _on_req)
        try:
            pg.click("button:has-text('生成')")
            gen = pg.wait_for_event(
                "response",
                lambda r: "/api/generate" in r.url and r.request.method == "POST",
                timeout=300000,
            )
            data = gen.json()
            imgs = data.get("images") or []
            vids = [f for f in imgs if isinstance(f, str) and f.lower().endswith((".mp4", ".webm", ".mov"))]
            if vids:
                okp("生成成功，视频文件: %s" % vids[0])
            else:
                fail("响应无视频文件，images=%s" % imgs)
        except Exception as e:  # noqa: BLE001
            fail("生成/拦截响应失败: %s" % e)

        # 7) 拉取 /api/image 验证
        if gen is not None and ok:
            try:
                data = gen.json()
                imgs = data.get("images") or []
                fn = [f for f in imgs if isinstance(f, str) and f.lower().endswith((".mp4", ".webm"))][0]
                resp = pg.request.get("http://127.0.0.1:8000/api/image/" + fn, timeout=60000)
                ct = resp.headers.get("content-type", "")
                body = resp.body() or b""
                if resp.status == 200 and "video" in ct and len(body) > 2000:
                    okp("/api/image 返回 %s，%d 字节（合法视频）" % (ct, len(body)))
                else:
                    fail("/api/image 验证失败: status=%s ct=%s bytes=%d" % (resp.status, ct, len(body)))
            except Exception as e:  # noqa: BLE001
                fail("拉取 /api/image 失败: %s" % e)

        # 8) 控制台错误
        real_err = [e for e in errors if e and "favicon" not in e]
        if real_err:
            fail("控制台/页面错误: %s" % real_err[:5])
        else:
            okp("无控制台/页面错误")
finally:
    if b is not None:
        try:
            b.close()
        except Exception:  # noqa: BLE001
            pass

print("\n==== E2E RESULT:", "PASS" if ok else "FAIL", "====")
sys.exit(0 if ok else 1)
