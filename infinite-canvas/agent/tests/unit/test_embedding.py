"""v5.2 一致性审查 + IP 相似度预警 单元测试。

覆盖：
  - extract_embedding 确定性哈希嵌入
  - cosine_similarity 计算
  - extract_cached 缓存
  - cross_node_consistency 批量审查
  - batch_consistency_summary 汇总
  - ConsistencyReport grade 属性
  - store_entity_embedding / get_entity_embedding
  - check_ip_similarity 预警
  - ip_library_status
  - rebuild_all_embeddings
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

import embedding_service as es


# ═══════════════════════════════════════════
# extract_embedding
# ═══════════════════════════════════════════

def test_extract_embedding_deterministic():
    """同一文件两次提取结果相同。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"test_image_content_123")
        tmp = f.name
    try:
        e1 = es.extract_embedding(tmp)
        e2 = es.extract_embedding(tmp)
        assert e1 is not None
        assert e2 is not None
        np.testing.assert_array_almost_equal(e1, e2)
    finally:
        os.unlink(tmp)


def test_extract_embedding_shape():
    """嵌入维度 = EMBED_DIM (768)。"""
    e = es.extract_embedding("test_image_path")
    assert e is not None
    assert e.shape == (es.EMBED_DIM,)
    assert e.dtype == np.float32


def test_extract_embedding_normalized():
    """嵌入向量是 L2 归一化的。"""
    e = es.extract_embedding("some_image.png")
    assert e is not None
    norm = float(np.linalg.norm(e))
    assert abs(norm - 1.0) < 1e-5


# ═══════════════════════════════════════════
# cosine_similarity
# ═══════════════════════════════════════════

def test_cosine_identical():
    """相同嵌入→相似度≈1.0。"""
    e = es.extract_embedding("x")
    assert e is not None
    sim = es.cosine_similarity(e, e)
    assert 0.99 <= sim <= 1.01


def test_cosine_none_handles():
    """None 输入 → 0.0。"""
    assert es.cosine_similarity(None, None) == 0.0
    e = es.extract_embedding("x")
    assert e is not None
    assert es.cosine_similarity(e, None) == 0.0


def test_cosine_range():
    """相似度 ∈ [0, 1]。"""
    e1 = es.extract_embedding("a")
    e2 = es.extract_embedding("b")
    assert e1 is not None
    assert e2 is not None
    sim = es.cosine_similarity(e1, e2)
    assert 0.0 <= sim <= 1.0


# ═══════════════════════════════════════════
# extract_cached
# ═══════════════════════════════════════════

def test_extract_cached_returns_same():
    """缓存命中时返回相同对象。"""
    e1 = es.extract_cached("cache_test_path")
    e2 = es.extract_cached("cache_test_path")
    assert e1 is not None
    assert e2 is not None
    np.testing.assert_array_equal(e1, e2)


# ═══════════════════════════════════════════
# #17 cross_node_consistency
# ═══════════════════════════════════════════

def test_cross_node_consistency_basic():
    """双节点一致性审查。"""
    nodes = [
        {
            "node_id": "n1",
            "reference_image": "ref1.png",
            "generated_image": "gen1.png",
            "mode": "face",
        },
        {
            "node_id": "n2",
            "reference_image": "ref2.png",
            "generated_image": "gen2.png",
            "mode": "style",
        },
    ]
    reports = es.cross_node_consistency(nodes)
    assert len(reports) == 2
    for r in reports:
        assert isinstance(r, es.ConsistencyReport)
        assert 0.0 <= r.similarity_score <= 1.0
        assert r.mode in ("face", "style")
        assert r.grade in ("A", "B", "C", "D")


def test_cross_node_consistency_same_ref():
    """同一参考图 vs 生成图，相似度直接取决于哈希差异。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"same_content")
        same = f.name
    try:
        nodes = [
            {"node_id": "n1", "reference_image": same,
             "generated_image": same, "mode": "face"},
        ]
        reports = es.cross_node_consistency(nodes, threshold=0.9)
        assert reports[0].similarity_score > 0.99  # 同一文件
        assert reports[0].passed is True
    finally:
        os.unlink(same)


def test_cross_node_consistency_custom_threshold():
    """自定义阈值影响 passed 判定。"""
    nodes = [
        {"node_id": "n1", "reference_image": "a",
         "generated_image": "b", "mode": "face"},
    ]
    # 阈值很高 → 不通过
    strict = es.cross_node_consistency(nodes, threshold=0.999)
    assert strict[0].passed is False
    # 阈值很低 → 通过
    loose = es.cross_node_consistency(nodes, threshold=0.001)
    assert loose[0].passed is True


# ═══════════════════════════════════════════
# batch_consistency_summary
# ═══════════════════════════════════════════

def test_batch_summary():
    """批量审查汇总含 pass_rate / grade / by_mode。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"ref_content")
        ref = f.name
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"gen_content_diff")
        gen = f.name
    try:
        nodes = [
            {"node_id": "n1", "reference_image": ref,
             "generated_image": gen, "mode": "face"},
            {"node_id": "n2", "reference_image": ref,
             "generated_image": gen, "mode": "style"},
        ]
        reports = es.cross_node_consistency(nodes, threshold=0.75)
        summary = es.batch_consistency_summary(reports)
        assert summary["total_nodes"] == 2
        assert 0.0 <= summary["pass_rate"] <= 1.0
        assert "grade_distribution" in summary
        assert sum(summary["grade_distribution"].values()) == 2
        assert "face" in summary["by_mode"]
        assert "style" in summary["by_mode"]
    finally:
        os.unlink(ref)
        os.unlink(gen)


# ═══════════════════════════════════════════
# ConsistencyReport.grade
# ═══════════════════════════════════════════

def test_grade_a():
    r = es.ConsistencyReport(
        node_id="n", reference_image="a", generated_image="a",
        similarity_score=0.95, passed=True, mode="face")
    assert r.grade == "A"


def test_grade_b():
    r = es.ConsistencyReport(
        node_id="n", reference_image="a", generated_image="a",
        similarity_score=0.82, passed=True, mode="face")
    assert r.grade == "B"


def test_grade_c():
    r = es.ConsistencyReport(
        node_id="n", reference_image="a", generated_image="a",
        similarity_score=0.65, passed=False, mode="face")
    assert r.grade == "C"


def test_grade_d():
    r = es.ConsistencyReport(
        node_id="n", reference_image="a", generated_image="a",
        similarity_score=0.30, passed=False, mode="face")
    assert r.grade == "D"


# ═══════════════════════════════════════════
# #18 IP 相似度预警 — 嵌入库
# ═══════════════════════════════════════════

def test_store_and_get_embedding():
    """存储并检索实体嵌入。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"entity_ref_image")
        ref = f.name
    try:
        # 先备份已有的 index
        original_index = {}
        if es.EMBEDDING_INDEX_FILE.exists():
            with open(es.EMBEDDING_INDEX_FILE, "r") as fi:
                original_index = json.load(fi)

        ok = es.store_entity_embedding("test_entity_v5", ref)
        assert ok is True

        emb = es.get_entity_embedding("test_entity_v5")
        assert emb is not None
        assert emb.shape == (es.EMBED_DIM,)

        # 恢复
        if original_index:
            with open(es.EMBEDDING_INDEX_FILE, "w") as fo:
                json.dump(original_index, fo)
        else:
            es.EMBEDDING_INDEX_FILE.unlink(missing_ok=True)
    finally:
        os.unlink(ref)


def test_get_embedding_missing():
    """不存在的实体返回 None。"""
    emb = es.get_entity_embedding("nonexistent_id_xyz")
    assert emb is None


# ═══════════════════════════════════════════
# check_ip_similarity
# ═══════════════════════════════════════════

def test_ip_check_no_reference():
    """无参考库时 passed=True 但给出 register 建议。"""
    result = es.check_ip_similarity("entity_no_ref", "some_image.png")
    assert result.passed is True
    assert result.suggested_action == "register_reference"
    assert result.reference_embedding_available is False


def test_ip_check_with_reference():
    """有参考库时检查相似度。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"ip_ref_content_unique")
        ref = f.name
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"ip_gen_content")
        gen = f.name
    try:
        es.store_entity_embedding("ip_test_char", ref)
        result = es.check_ip_similarity("ip_test_char", gen, entity_name="TestChar")
        assert result.reference_embedding_available is True
        assert isinstance(result.generated_similarity, float)
        assert 0.0 <= result.generated_similarity <= 1.0
    finally:
        os.unlink(ref)
        os.unlink(gen)


def test_ip_check_same_image_passes():
    """同一图像 → 高分通过。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"same_image_for_ip_check")
        img = f.name
    try:
        es.store_entity_embedding("same_img_char", img)
        result = es.check_ip_similarity("same_img_char", img, "SameImg")
        assert result.passed is True
        assert result.generated_similarity > 0.99
    finally:
        os.unlink(img)


# ═══════════════════════════════════════════
# ip_library_status
# ═══════════════════════════════════════════

def test_ip_library_status():
    """返回嵌入库状态（维度、实体数、索引路径）。"""
    status = es.ip_library_status()
    assert "total_entities" in status
    assert "embedding_dim" in status
    assert status["embedding_dim"] == es.EMBED_DIM
    assert "entity_ids" in status
    assert "index_file" in status
