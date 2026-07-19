"""验证 agent HTTP 契约（前端将调用的真实端点）。

运行：cd infinite-canvas/agent && .venv\\Scripts\\python.exe agent_api_test.py
"""
from fastapi.testclient import TestClient

from main import app

c = TestClient(app)

print("[health]", c.get("/health").json())
print("[models]", c.get("/api/models").json())

r = c.post("/api/generate", json={"prompt": "a cute cat on a desk", "width": 512, "height": 512})
print("[generate] status", r.status_code)
print("[generate] body", r.json())

assert r.status_code == 200
body = r.json()
assert body["validated"] is True
assert body["prompt_id"], "未返回 prompt_id"
print("✅ AGENT API 契约通过（/api/generate 已对接真实 ComfyUI）")
