"""无限画布 · 端到端管线测试（§14.3 零人工代理循环实证）。

自然语言 → /api/intent（DeepSeek v4 解析意图）
           → /api/generate（意图→模板→参数填充→校验→提交 ComfyUI，wait 轮询出图）

验证两条路径：
  A. 默认文生图（NoobAI-XL checkpoint，已实测稳妥）
  B. Qwen-Image 2.0（UNET+CLIP+VAE，Apache 2.0 优先）
"""
from __future__ import annotations

import os
import sys

# 确保 .env 被加载（main 内也会加载，这里双保险）
if os.path.exists(".env"):
    for ln in open(".env", encoding="utf-8"):
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from fastapi.testclient import TestClient
import main as agent

client = TestClient(agent.app)


def run_case(label: str, user_input: str) -> dict:
    print(f"\n===== {label} =====\n  输入: {user_input}")
    r = client.post("/api/intent", json={"user_input": user_input})
    assert r.status_code == 200, f"/api/intent {r.status_code}: {r.text[:300]}"
    intent = r.json()
    print("  意图:", {k: intent[k] for k in ("action", "subject", "style")},
          "| params.model:", intent["params"].get("model"))

    g = client.post("/api/generate", json={"intent": intent, "wait": True})
    assert g.status_code == 200, f"/api/generate {g.status_code}: {g.text[:300]}"
    res = g.json()
    print("  → template_id:", res["template_id"],
          "| validated:", res["validated"],
          "| status:", res["status"],
          "| prompt_id:", res["prompt_id"][:12], "...")
    if res["meta"].get("note"):
        print("  ⚠ note:", res["meta"]["note"])
    print("  出图:", res["images"] if res["images"] else "(无/超时)")
    return res


if __name__ == "__main__":
    # 健康检查
    h = client.get("/health").json()
    print("health:", h)
    t = client.get("/api/templates").json()
    print("templates:", [x["id"] for x in t])

    ok = True
    # A. 默认文生图（NoobAI）
    ra = run_case("A. 默认文生图", "画一只在星空下奔跑的红色狐狸，赛博朋克风格，竖图")
    ok = ok and ra["validated"] and bool(ra["images"]) and ra["status"] == "success"

    # B. Qwen-Image 2.0（Apache 2.0 优先路径）
    rb = run_case("B. Qwen-Image 2.0", "用 Qwen-Image 画一座宁静的雪山湖泊，写实摄影风格，横图")
    ok = ok and rb["validated"]  # 即便 VRAM 不足降级，validated 应为真

    print("\n===== 结论 =====")
    print("端到端管线:", "✅ 通过" if ok else "❌ 存在问题")
    sys.exit(0 if ok else 1)
