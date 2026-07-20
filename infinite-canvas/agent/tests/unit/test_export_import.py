"""无限画布 · v5.4 项目导出/导入管线 单元测试。

覆盖 /api/export_project 和 /api/import_project 端点。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


# ── 项目导出（JSON 格式）───────────────────────────────────────────

def test_export_project_json_empty(client: TestClient):
    """空画布导出 JSON 应该返回有效快照。"""
    payload = {"export_format": "json"}
    resp = client.post("/api/export_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["version"] == "v5.4"
    assert data["meta"]["node_count"] == 0
    assert "canvas" in data
    assert "entities" in data


def test_export_project_json_with_nodes(client: TestClient):
    """含节点的画布导出。"""
    payload = {
        "export_format": "json",
        "nodes": [
            {"id": "n1", "kind": "image", "filename": "test.png", "x": 0, "y": 0, "width": 512, "height": 512},
            {"id": "n2", "kind": "video", "filename": "test.mp4", "x": 600, "y": 0, "width": 512, "height": 512},
        ],
        "links": [{"fromId": "n1", "toId": "n2"}],
        "layers": [{"id": "l1", "name": "主层", "kind": "image"}],
    }
    resp = client.post("/api/export_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["node_count"] == 2
    assert data["meta"]["link_count"] == 1
    assert data["meta"]["layer_count"] == 1
    assert len(data["canvas"]["nodes"]) == 2
    assert data["canvas"]["links"][0]["fromId"] == "n1"


def test_export_project_json_with_entities(client: TestClient):
    """含实体的画布导出。"""
    # 先创建实体
    resp1 = client.post("/api/entities", json={
        "kind": "character", "name": "孙悟空", "description": "齐天大圣",
    })
    assert resp1.status_code == 200
    eid = resp1.json()["entity"]["entity_id"]

    payload = {
        "export_format": "json",
        "entity_ids": [eid],
    }
    resp = client.post("/api/export_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["entity_count"] == 1
    assert data["entities"][0]["name"] == "孙悟空"


def test_export_project_zip_format(client: TestClient):
    """ZIP 格式导出。"""
    payload = {
        "export_format": "zip",
        "nodes": [{"id": "n1", "kind": "image", "filename": "test.png", "x": 0, "y": 0, "width": 512, "height": 512}],
    }
    resp = client.post("/api/export_project", json=payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    assert len(resp.content) > 0


def test_export_project_with_timeline(client: TestClient):
    """含时间线和分镜的导出。"""
    payload = {
        "export_format": "json",
        "timeline": [{"id": "t1", "nodeId": "n1", "startMs": 0, "endMs": 5000}],
        "storyboard_shots": [{"id": "s1", "index": 0, "prompt": "开场景色", "shotStatus": "done"}],
    }
    resp = client.post("/api/export_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["timeline_count"] == 1
    assert data["meta"]["storyboard_shot_count"] == 1


def test_export_project_with_workflow(client: TestClient):
    """含工作流图的导出。"""
    payload = {
        "export_format": "json",
        "workflow_graph": {"nodes": [{"id": "w1", "type": "KSampler"}], "links": []},
    }
    resp = client.post("/api/export_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_graph"] is not None
    assert data["workflow_graph"]["nodes"][0]["type"] == "KSampler"


# ── 项目导入 ───────────────────────────────────────────────────────

def test_import_project_preview(client: TestClient):
    """preview 策略：仅验证不写入。"""
    payload = {
        "data": {
            "meta": {"version": "v5.4", "node_count": 3},
            "canvas": {"nodes": [], "links": [], "port_edges": [], "layers": []},
            "entities": [],
        },
        "strategy": "preview",
    }
    resp = client.post("/api/import_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "preview"
    assert data["valid"] is True
    assert data["summary"]["node_count"] == 3


def test_import_project_merge_empty(client: TestClient):
    """merge 空快照不报错。"""
    payload = {
        "data": {
            "meta": {"version": "v5.4"},
            "canvas": {"nodes": [], "links": [], "port_edges": [], "layers": []},
            "entities": [],
        },
        "strategy": "merge",
    }
    resp = client.post("/api/import_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "merge"
    assert "canvas" in data


def test_import_project_replace(client: TestClient):
    """replace 策略返回画布数据。"""
    payload = {
        "data": {
            "meta": {"version": "v5.4"},
            "canvas": {"nodes": [{"id": "x1"}], "links": [], "port_edges": [], "layers": []},
            "entities": [],
        },
        "strategy": "replace",
    }
    resp = client.post("/api/import_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "replace"
    assert len(data["canvas"]["nodes"]) == 1


def test_import_project_with_entities(client: TestClient):
    """导入含实体的项目快照。"""
    payload = {
        "data": {
            "meta": {"version": "v5.4", "entity_count": 1},
            "canvas": {"nodes": [], "links": [], "port_edges": [], "layers": []},
            "entities": [
                {"kind": "scene", "name": "龙宫", "description": "海底龙宫"},
            ],
        },
        "strategy": "merge",
    }
    resp = client.post("/api/import_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "merge"


def test_import_project_with_timeline(client: TestClient):
    """导入含时间线的项目快照。"""
    payload = {
        "data": {
            "meta": {"version": "v5.4"},
            "canvas": {"nodes": [], "links": [], "port_edges": [], "layers": []},
            "timeline": [{"id": "t1", "nodeId": "n1", "startMs": 0, "endMs": 3000}],
            "storyboard_shots": [{"id": "s1", "index": 0}],
            "entities": [],
        },
        "strategy": "merge",
    }
    resp = client.post("/api/import_project", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["timeline"]) == 1
    assert len(data["storyboard_shots"]) == 1


def test_import_project_default_strategy(client: TestClient):
    """默认策略为 merge。"""
    payload = {
        "data": {
            "meta": {"version": "v5.4"},
            "canvas": {"nodes": [], "links": [], "port_edges": [], "layers": []},
            "entities": [],
        },
    }
    resp = client.post("/api/import_project", json=payload)
    assert resp.status_code == 200
    assert resp.json()["strategy"] == "merge"


# ── 跨端点集成测试 ────────────────────────────────────────────────

def test_export_import_roundtrip(client: TestClient):
    """导出 → 导入 往返一致性测试。"""
    nodes = [{"id": "n-round", "kind": "image", "filename": "roundtrip.png", "x": 100, "y": 200, "width": 512, "height": 512}]
    links = [{"fromId": "n-round", "toId": "n2"}]
    layers = [{"id": "l-round", "name": "测试层", "kind": "image"}]

    # 导出
    export_payload = {
        "export_format": "json",
        "nodes": nodes,
        "links": links,
        "layers": layers,
    }
    resp = client.post("/api/export_project", json=export_payload)
    assert resp.status_code == 200
    snapshot = resp.json()

    # 导入
    import_payload = {"data": snapshot, "strategy": "preview"}
    resp2 = client.post("/api/import_project", json=import_payload)
    assert resp2.status_code == 200
    assert resp2.json()["summary"]["node_count"] == 1
    assert resp2.json()["summary"]["link_count"] == 1
    assert resp2.json()["summary"]["layer_count"] == 1


def test_export_port_edges(client: TestClient):
    """端口连线也能正常导出。"""
    payload = {
        "export_format": "json",
        "port_edges": [
            {"id": "pe1", "fromNodeId": "n1", "fromPortId": "out-0", "toNodeId": "n2", "toPortId": "in-0"},
        ],
    }
    resp = client.post("/api/export_project", json=payload)
    assert resp.status_code == 200
    assert resp.json()["meta"]["port_edge_count"] == 1
