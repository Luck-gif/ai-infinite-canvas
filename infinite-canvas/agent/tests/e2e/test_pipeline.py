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


# ── v4.50 Pipeline Orchestrator E2E ────────────────────────────────


def test_pipeline_run_basic():
    """E2E: PipelineOrchestrator /api/pipeline/run 基础执行。"""
    r = client.post("/api/pipeline/run", json={
        "prompt": "a cyberpunk city at night with neon lights, rain",
        "submit": False,
    })
    assert r.status_code == 200, f"pipeline/run {r.status_code}: {r.text[:300]}"
    data = r.json()
    assert data.get("validated") is True
    assert data.get("node_count", 0) > 0
    assert len(data.get("prompt_engineered", "")) > 0
    assert "pipeline_version" in data
    assert "blueprint" in data
    assert len(data.get("workflow_json", {})) > 0


def test_pipeline_run_with_blueprint():
    """E2E: PipelineOrchestrator 指定蓝图执行。"""
    r = client.post("/api/pipeline/run", json={
        "prompt": "动漫风格少女，精致线条，柔和上色",
        "image_blueprint": "txt2img_qwen",
        "consistency_mode": "auto",
        "width": 768,
        "height": 768,
        "submit": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["validated"]
    assert data["blueprint_id"] == "txt2img_qwen"


def test_pipeline_run_anime_auto():
    """E2E: PipelineOrchestrator 自动匹配动漫风格蓝图。"""
    r = client.post("/api/pipeline/run", json={
        "prompt": "动漫风格角色，二次元",
        "submit": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["validated"]
    assert "qwen" in data["blueprint_id"].lower() or data["blueprint_id"] == "txt2img_sdxl"


def test_pipeline_storyboard_basic():
    """E2E: PipelineOrchestrator 故事板管线。"""
    r = client.post("/api/pipeline/storyboard", json={
        "description": "日出时的海边灯塔; 海鸥飞翔在码头; 渔夫收网; 日落余晖中的灯塔",
        "num_shots": 3,
    })
    assert r.status_code == 200
    data = r.json()
    assert data.get("total_shots", 0) > 0
    assert len(data.get("shots", [])) > 0
    assert "storyboard_id" in data
    for shot in data["shots"]:
        assert "prompt" in shot
        assert "shot_id" in shot


def test_pipeline_storyboard_single_shot():
    """E2E: PipelineOrchestrator 单分镜故事板。"""
    r = client.post("/api/pipeline/storyboard", json={
        "description": "a single beautiful scene",
        "num_shots": 1,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["total_shots"] == 1


def test_workflow_generate_api():
    """E2E: /api/workflows/generate 端点。"""
    r = client.post("/api/workflows/generate", json={
        "prompt": "a beautiful landscape with mountains and a lake",
        "submit": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data.get("validated") is True
    assert data.get("node_count", 0) > 0
    assert data.get("shot_id", "")


def test_blueprints_api():
    """E2E: /api/blueprints 端点返回完整蓝图列表。"""
    r = client.get("/api/blueprints")
    assert r.status_code == 200
    data = r.json()
    assert "image" in data
    assert "video" in data
    assert len(data["image"]) > 0
    for bp in data["image"]:
        assert "id" in bp
        assert "name" in bp


def test_pipeline_error_handling():
    """E2E: 管线错误处理 - 空提示词。"""
    r = client.post("/api/pipeline/run", json={
        "prompt": "",
        "submit": False,
    })
    # 空提示词可能导致 422 或 200（取决于后端处理）
    assert r.status_code in (200, 422)


def test_health_check():
    """E2E: 健康检查端点仍可用。"""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


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
