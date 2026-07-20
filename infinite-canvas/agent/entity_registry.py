"""实体注册表（§10.1 画布实体系统）

角色 / 场景 / 道具 / 风格的结构化注册与序列化存储。
每个实体由"概念"衍生自用户自然语言，并附带视觉锚定信息
（种子/首帧/参考图），用于跨 StoryDiffusion 分镜保持一致性。

存储格式：JSON 文件，位于 agent/outputs/entities/。
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ── 存储根目录 ──────────────────────────────────────────────────────
_STORE_ROOT = os.path.join(os.path.dirname(__file__), "outputs", "entities")

# ── 枚举 ────────────────────────────────────────────────────────────

class EntityKind(str, Enum):
    CHARACTER = "character"   # 角色
    SCENE = "scene"           # 场景
    PROP = "prop"             # 道具
    STYLE = "style"           # 风格


# ── 数据类 ──────────────────────────────────────────────────────────

@dataclass
class VisualAnchor:
    """视觉锚点：用于跨分镜保持角色/场景外观一致性。"""
    seed: int = 0
    first_frame_path: Optional[str] = None   # 相对 outputs/ 路径
    reference_image_path: Optional[str] = None
    lora_name: Optional[str] = None           # 绑定的 LoRA 文件名
    controlnet_type: Optional[str] = None     # 如 "openpose"


@dataclass
class Entity:
    """画布实体。"""
    entity_id: str                          # UUID4
    kind: EntityKind
    name: str                               # 用户可见名称（中文）
    alias: str                              # 英文别名（用于 prompt）
    description: str                        # 自然语言描述
    prompt_override: Optional[str] = None   # 覆盖默认 prompt 前缀
    tags: List[str] = field(default_factory=list)
    anchor: VisualAnchor = field(default_factory=VisualAnchor)
    parent_entity_id: Optional[str] = None  # 层级关系
    children_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""                    # ISO 8601
    updated_at: str = ""


# ── 工具函数 ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sanitize_filename(name: str) -> str:
    """将实体名转换为安全文件名。"""
    # 保留中文、英文、数字、连字符、下划线
    safe = re.sub(r"[^\w\u4e00-\u9fff-]", "_", name).strip("_")
    return safe or "unnamed"


def _entity_path(entity_id: str) -> str:
    return os.path.join(_STORE_ROOT, f"{entity_id}.json")


# ── CRUD 操作 ───────────────────────────────────────────────────────

def _ensure_store() -> None:
    os.makedirs(_STORE_ROOT, exist_ok=True)


def create_entity(
    kind: EntityKind,
    name: str,
    alias: str = "",
    description: str = "",
    prompt_override: Optional[str] = None,
    tags: Optional[List[str]] = None,
    anchor: Optional[VisualAnchor] = None,
    parent_entity_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Entity:
    """创建新实体并持久化。"""
    _ensure_store()
    now = _now_iso()
    eid = uuid.uuid4().hex
    ent = Entity(
        entity_id=eid,
        kind=kind,
        name=name,
        alias=alias or _sanitize_filename(name),
        description=description,
        prompt_override=prompt_override,
        tags=tags or [],
        anchor=anchor or VisualAnchor(),
        parent_entity_id=parent_entity_id,
        metadata=metadata or {},
        created_at=now,
        updated_at=now,
    )
    _save_entity(ent)
    return ent


def _save_entity(ent: Entity) -> None:
    _ensure_store()
    path = _entity_path(ent.entity_id)
    d = asdict(ent)
    d["kind"] = ent.kind.value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def get_entity(entity_id: str) -> Optional[Entity]:
    """按 ID 读取实体。"""
    path = _entity_path(entity_id)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return _dict_to_entity(d)


def update_entity(
    entity_id: str,
    *,
    name: Optional[str] = None,
    alias: Optional[str] = None,
    description: Optional[str] = None,
    prompt_override: Optional[str] = None,
    tags: Optional[List[str]] = None,
    anchor: Optional[VisualAnchor] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Entity]:
    """部分更新实体字段。"""
    ent = get_entity(entity_id)
    if ent is None:
        return None
    if name is not None:
        ent.name = name
    if alias is not None:
        ent.alias = alias
    if description is not None:
        ent.description = description
    if prompt_override is not None:
        ent.prompt_override = prompt_override
    if tags is not None:
        ent.tags = tags
    if anchor is not None:
        ent.anchor = anchor
    if metadata is not None:
        ent.metadata = metadata
    ent.updated_at = _now_iso()
    _save_entity(ent)
    return ent


def delete_entity(entity_id: str) -> bool:
    """删除实体及其 JSON 文件。"""
    path = _entity_path(entity_id)
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def list_entities(kind: Optional[EntityKind] = None) -> List[Entity]:
    """列出所有实体，可按 kind 过滤。"""
    _ensure_store()
    result: List[Entity] = []
    try:
        filenames = os.listdir(_STORE_ROOT)
    except FileNotFoundError:
        return result
    for fn in filenames:
        if not fn.endswith(".json"):
            continue
        path = os.path.join(_STORE_ROOT, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            ent = _dict_to_entity(d)
            if kind is None or ent.kind == kind:
                result.append(ent)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return result


def search_entities(query: str) -> List[Entity]:
    """按名称/别名/标签模糊搜索。"""
    q = query.lower()
    results: List[Entity] = []
    for ent in list_entities():
        if (q in ent.name.lower()
            or q in ent.alias.lower()
            or any(q in t.lower() for t in ent.tags)):
            results.append(ent)
    return results


def build_entity_prompt(entity_id: str) -> Optional[str]:
    """为指定实体生成可用于工作流的 prompt 前缀。

    返回类似 "A character named 孙悟空 (Sun Wukong), wearing golden armor, ..."
    """
    ent = get_entity(entity_id)
    if ent is None:
        return None
    if ent.prompt_override:
        return ent.prompt_override

    kind_label = {
        EntityKind.CHARACTER: "A character named",
        EntityKind.SCENE: "A scene of",
        EntityKind.PROP: "A prop named",
        EntityKind.STYLE: "In the style of",
    }.get(ent.kind, "A")

    parts = [f"{kind_label} {ent.name} ({ent.alias})"]
    if ent.description:
        parts.append(ent.description)
    if ent.tags:
        parts.append(", ".join(ent.tags))
    return ", ".join(parts)


# ── 内部工具 ────────────────────────────────────────────────────────

def _dict_to_entity(d: Dict[str, Any]) -> Entity:
    anchor_raw = d.get("anchor", {})
    return Entity(
        entity_id=d["entity_id"],
        kind=EntityKind(d["kind"]),
        name=d["name"],
        alias=d.get("alias", ""),
        description=d.get("description", ""),
        prompt_override=d.get("prompt_override"),
        tags=d.get("tags", []),
        anchor=VisualAnchor(
            seed=anchor_raw.get("seed", 0),
            first_frame_path=anchor_raw.get("first_frame_path"),
            reference_image_path=anchor_raw.get("reference_image_path"),
            lora_name=anchor_raw.get("lora_name"),
            controlnet_type=anchor_raw.get("controlnet_type"),
        ),
        parent_entity_id=d.get("parent_entity_id"),
        children_ids=d.get("children_ids", []),
        metadata=d.get("metadata", {}),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )


# ── v4.50 工作流组装器数据桥接 ─────────────────────────────────────

def load_all_entities() -> dict:
    """返回 workflow_assembler 期望的实体注册表格式。

    格式：{"entities": {entity_id: {name, type, description, ...}}}
    """
    result: dict[str, dict] = {}
    for ent in list_entities():
        result[ent.entity_id] = {
            "name": ent.name,
            "type": ent.kind.value if hasattr(ent.kind, 'value') else str(ent.kind),
            "description": ent.description or ent.name,
            "alias": ent.alias,
            "prompt_override": ent.prompt_override,
            "tags": ent.tags,
            "reference_image": ent.anchor.reference_image_path,
            "seed": ent.anchor.seed,
        }
    return {"entities": result}
