"""无限画布 v5.2 · CLIP 嵌入服务 + 一致性审查 + IP 相似度预警。

共享 CLIP 嵌入提取管线，支撑两类应用：
1. 一致性自动审查（#17）— 跨节点 CLIP embedding 相似度评分
2. IP 相似度预警（#18）— 角色嵌入库 + 生成图与参考图对比

核心流程：
  - extract_embedding(image_path) → CLIP ViT-L/14 256-dim → np.array
  - cosine_similarity(emb1, emb2) → float ∈ [0, 1]
  - cross_node_consistency(node_images) → list[ConsistencyReport]
  - check_ip_similarity(entity_id, generated_image) → IPSimilarityResult

设计要点（§6.3.2 一致性策略 + §9.5 IP 管理）：
  - 图像嵌入使用 CLIP ViT-L/14（OpenCLIP 兼容）
  - 阈值：一致性 ≥ 0.75，IP 相似度 ≥ 0.65
  - 嵌入库持久化到 JSON（entity_id → embedding）
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from entity_registry import Entity, get_entity


# ── 嵌入库持久化 ──────────────────────────────────────────────────────

EMBEDDING_STORE_DIR = Path(__file__).parent / "data" / "embeddings"
EMBEDDING_STORE_DIR.mkdir(parents=True, exist_ok=True)
EMBEDDING_INDEX_FILE = EMBEDDING_STORE_DIR / "index.json"

# 嵌入维度（CLIP ViT-L/14）
EMBED_DIM = 768


def _load_index() -> dict[str, list[float]]:
    """加载嵌入索引 JSON（entity_id → embedding 列表）。"""
    if EMBEDDING_INDEX_FILE.exists():
        try:
            with open(EMBEDDING_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_index(index: dict[str, list[float]]) -> None:
    """保存嵌入索引。"""
    with open(EMBEDDING_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


# ── 模拟 CLIP 嵌入提取（生产环境替换为 OpenCLIP/transformers 调用）────

def extract_embedding(image_path: str, model: str = "ViT-L/14") -> np.ndarray | None:
    """从图像提取 CLIP embedding。

    当前使用确定性哈希模拟（生产环境替换为 OpenCLIP）。
    同一图像始终返回相同嵌入，保证测试可重现。

    返回 shape=(EMBED_DIM,) 的归一化向量。
    """
    try:
        if os.path.isfile(image_path):
            with open(image_path, "rb") as f:
                img_bytes = f.read()
        else:
            # 文件不存在时使用路径字符串作为种子
            img_bytes = image_path.encode("utf-8")

        # 确定性哈希 → 伪嵌入
        h = hashlib.sha256(img_bytes).digest()
        seed = int.from_bytes(h[:8], "big")
        # NumPy ≥1.17: 使用 Generator (RandomState 已废弃)
        try:
            rng = np.random.default_rng(seed)
        except TypeError:
            rng = np.random.RandomState(seed)  # type: ignore[attr-defined]
        emb = rng.standard_normal(EMBED_DIM).astype(np.float32)
        # L2 归一化
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb
    except Exception:
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个嵌入向量的余弦相似度。

    返回值 ∈ [0, 1]（已截断，保证非负）。
    """
    if a is None or b is None:
        return 0.0
    dot = float(np.dot(a, b))
    return max(0.0, min(1.0, dot))


# ── 图像缓存 ─────────────────────────────────────────────────────────

_embed_cache: dict[str, np.ndarray] = {}


def extract_cached(image_path: str) -> np.ndarray | None:
    """带缓存的嵌入提取。"""
    cache_key = os.path.normpath(image_path)
    if cache_key in _embed_cache:
        return _embed_cache[cache_key]
    emb = extract_embedding(image_path)
    if emb is not None:
        _embed_cache[cache_key] = emb
    return emb


# ═══════════════════════════════════════════════════════════════════════
# #17 一致性自动审查
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ConsistencyReport:
    """单节点一致性审查报告。"""
    node_id: str
    reference_image: str
    generated_image: str
    similarity_score: float           # 余弦相似度 ∈ [0, 1]
    passed: bool                      # 是否通过 ≥ 阈值
    mode: str = "face"                # face | style | scene
    threshold: float = 0.75
    issues: list[str] = field(default_factory=list)

    @property
    def grade(self) -> str:
        """相似度等级：A(≥0.9) / B(≥0.75) / C(≥0.6) / D(<0.6)。"""
        if self.similarity_score >= 0.90:
            return "A"
        if self.similarity_score >= 0.75:
            return "B"
        if self.similarity_score >= 0.60:
            return "C"
        return "D"

    def __str__(self) -> str:
        return (f"[{self.grade}] {self.mode}: {self.node_id} "
                f"similarity={self.similarity_score:.3f} "
                f"({'PASS' if self.passed else 'FAIL'})")


def cross_node_consistency(
    nodes: list[dict[str, Any]],
    threshold: float = 0.75,
) -> list[ConsistencyReport]:
    """跨节点一致性审查。

    对每个节点：
    1. 从 reference_image 提取参考嵌入
    2. 从 generated_image 提取生成嵌入
    3. 计算余弦相似度
    4. 标记是否通过阈值

    Args:
        nodes: [{node_id, reference_image, generated_image, mode}, ...]
        threshold: 通过阈值（默认 0.75）
    """
    reports: list[ConsistencyReport] = []
    for n in nodes:
        ref_emb = extract_cached(n.get("reference_image", ""))
        gen_emb = extract_cached(n.get("generated_image", ""))
        sim = cosine_similarity(ref_emb, gen_emb) if (ref_emb is not None and gen_emb is not None) else 0.0

        mode = n.get("mode", "face")
        report = ConsistencyReport(
            node_id=str(n.get("node_id", "")),
            reference_image=str(n.get("reference_image", "")),
            generated_image=str(n.get("generated_image", "")),
            similarity_score=sim,
            passed=sim >= threshold,
            mode=mode,
            threshold=threshold,
        )
        if not report.passed:
            report.issues.append(
                f"节点 {report.node_id}: {mode} 一致性 {sim:.2f} < {threshold}（阈值）"
            )
        reports.append(report)
    return reports


def batch_consistency_summary(reports: list[ConsistencyReport]) -> dict[str, Any]:
    """批量审查汇总。"""
    total = len(reports)
    passed = sum(1 for r in reports if r.passed)
    avg_sim = float(np.mean([r.similarity_score for r in reports])) if reports else 0.0
    by_mode: dict[str, dict[str, Any]] = {}
    for r in reports:
        if r.mode not in by_mode:
            by_mode[r.mode] = {"total": 0, "passed": 0, "avg_sim": 0.0}
        by_mode[r.mode]["total"] += 1
        by_mode[r.mode]["passed"] += 1 if r.passed else 0

    for mode, stats in by_mode.items():
        mode_reports = [r for r in reports if r.mode == mode]
        stats["avg_sim"] = round(float(np.mean([r.similarity_score for r in mode_reports])), 3)

    all_issues = [i for r in reports for i in r.issues]
    return {
        "total_nodes": total,
        "passed_nodes": passed,
        "failed_nodes": total - passed,
        "pass_rate": round(passed / total, 3) if total > 0 else 1.0,
        "avg_similarity": round(avg_sim, 3),
        "by_mode": by_mode,
        "issues": all_issues,
        "grade_distribution": {
            g: sum(1 for r in reports if r.grade == g)
            for g in ["A", "B", "C", "D"]
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# #18 IP 相似度预警
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class IPSimilarityResult:
    """IP 相似度检查结果。"""
    entity_id: str
    entity_name: str
    reference_embedding_available: bool
    generated_similarity: float  # 生成图与参考库的相似度
    passed: bool                  # ≥ 0.65
    warning: str = ""
    suggested_action: str = ""

    THRESHOLD = 0.65
    DANGER_THRESHOLD = 0.45  # 严重偏离


def store_entity_embedding(entity_id: str, reference_image_path: str) -> bool:
    """存储实体的参考嵌入到索引库。"""
    emb = extract_embedding(reference_image_path)
    if emb is None:
        return False
    index = _load_index()
    index[entity_id] = emb.tolist()
    _save_index(index)
    return True


def get_entity_embedding(entity_id: str) -> np.ndarray | None:
    """从索引库加载实体嵌入。"""
    index = _load_index()
    raw = index.get(entity_id)
    if raw is None:
        return None
    return np.array(raw, dtype=np.float32)


def check_ip_similarity(
    entity_id: str,
    generated_image_path: str,
    entity_name: str = "",
) -> IPSimilarityResult:
    """检查生成图与角色 IP 参考库的相似度。

    流程：
    1. 从索引库加载实体 embedding
    2. 提取生成图 embedding
    3. 计算余弦相似度
    4. 低于阈值给出预警
    """
    ref_emb = get_entity_embedding(entity_id)
    if ref_emb is None:
        return IPSimilarityResult(
            entity_id=entity_id,
            entity_name=entity_name or entity_id,
            reference_embedding_available=False,
            generated_similarity=0.0,
            passed=True,  # 无参考库时不报错
            warning=f"实体 {entity_id} 尚无参考嵌入，请先通过 POST /api/guard/ip-register 注册",
            suggested_action="register_reference",
        )

    gen_emb = extract_embedding(generated_image_path)
    sim = cosine_similarity(ref_emb, gen_emb) if gen_emb is not None else 0.0

    warning = ""
    action = ""
    if sim < IPSimilarityResult.DANGER_THRESHOLD:
        warning = (
            f"⚠️ 严重偏离：生成图与 {entity_name or entity_id} 参考库相似度仅 "
            f"{sim:.2f}（阈值 {IPSimilarityResult.DANGER_THRESHOLD}），"
            f"角色外观可能已严重失真"
        )
        action = "re_generate"
    elif sim < IPSimilarityResult.THRESHOLD:
        warning = (
            f"⚠️ 轻度偏离：生成图与 {entity_name or entity_id} 参考库相似度 "
            f"{sim:.2f}（阈值 {IPSimilarityResult.THRESHOLD}），"
            f"建议微调 IPAdapter 权重"
        )
        action = "tune_ipadapter"

    return IPSimilarityResult(
        entity_id=entity_id,
        entity_name=entity_name or entity_id,
        reference_embedding_available=True,
        generated_similarity=round(sim, 4),
        passed=sim >= IPSimilarityResult.THRESHOLD,
        warning=warning,
        suggested_action=action,
    )


def rebuild_all_embeddings(
    entity_dir: str = "",
) -> dict[str, bool]:
    """批量重建所有实体参考嵌入。

    遍历已知实体列表，提取各自主图嵌入并存入索引。
    """
    from entity_registry import list_entities
    entities = list_entities()
    results: dict[str, bool] = {}
    for e in entities:
        ref_img = ""
        if e.anchor and e.anchor.reference_image:
            ref_img = e.anchor.reference_image
        if entity_dir and ref_img:
            ref_img = os.path.join(entity_dir, ref_img)
        if ref_img and os.path.isfile(ref_img):
            results[e.id] = store_entity_embedding(e.id, ref_img)
        else:
            results[e.id] = False
    return results


def ip_library_status() -> dict[str, Any]:
    """IP 嵌入库状态查询。"""
    index = _load_index()
    total = len(index)
    dim = EMBED_DIM
    entities = list(index.keys())
    return {
        "total_entities": total,
        "embedding_dim": dim,
        "entity_ids": entities,
        "index_file": str(EMBEDDING_INDEX_FILE),
    }
