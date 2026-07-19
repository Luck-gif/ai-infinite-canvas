"""workflow_to_graph 单元测试：验证 ComfyUI 工作流 JSON → 前端可视化节点图转换。

运行：cd infinite-canvas/agent && .venv\\Scripts\\python.exe -m pytest test_workflow_graph.py -q
"""
from __future__ import annotations

import pytest
import comfy_client as cc


# ── 基础工作流构造函数 ──────────────────────────────────────────────

def build_minimal_txt2img() -> dict:
    """最小 txt2img 工作流：CLIP → KSampler → VAE Decode → SaveImage"""
    wf = {}
    # Load Checkpoint
    wf["1"] = {
        "inputs": {"ckpt_name": "NoobAI.safetensors"},
        "class_type": "CheckpointLoaderSimple",
    }
    # CLIP Text Encode (positive)
    wf["2"] = {
        "inputs": {"text": "a cat", "clip": ["1", 1]},
        "class_type": "CLIPTextEncode",
    }
    # CLIP Text Encode (negative)
    wf["3"] = {
        "inputs": {"text": "blurry", "clip": ["1", 1]},
        "class_type": "CLIPTextEncode",
    }
    # Empty Latent Image
    wf["4"] = {
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
        "class_type": "EmptyLatentImage",
    }
    # KSampler
    wf["5"] = {
        "inputs": {
            "seed": 42, "steps": 20, "cfg": 7.0,
            "sampler_name": "euler", "scheduler": "normal",
            "denoise": 1.0,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["4", 0],
        },
        "class_type": "KSampler",
    }
    # VAE Decode
    wf["6"] = {
        "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        "class_type": "VAEDecode",
    }
    # Save Image
    wf["7"] = {
        "inputs": {"images": ["6", 0], "filename_prefix": "test_"},
        "class_type": "SaveImage",
    }
    return wf


def build_img_to_img() -> dict:
    """图生图工作流：含 LoadImage → VAE Encode → KSampler"""
    wf = {}
    wf["1"] = {
        "inputs": {"ckpt_name": "NoobAI.safetensors"},
        "class_type": "CheckpointLoaderSimple",
    }
    wf["2"] = {
        "inputs": {"text": "anime style", "clip": ["1", 1]},
        "class_type": "CLIPTextEncode",
    }
    wf["3"] = {
        "inputs": {"text": "", "clip": ["1", 1]},
        "class_type": "CLIPTextEncode",
    }
    wf["4"] = {
        "inputs": {"image": "input.png", "upload": "image"},
        "class_type": "LoadImage",
    }
    wf["5"] = {
        "inputs": {"pixels": ["4", 0], "vae": ["1", 2]},
        "class_type": "VAEEncode",
    }
    wf["6"] = {
        "inputs": {
            "seed": 42, "steps": 20, "cfg": 7.0,
            "sampler_name": "euler", "scheduler": "normal",
            "denoise": 0.6,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["5", 0],
        },
        "class_type": "KSampler",
    }
    wf["7"] = {
        "inputs": {"samples": ["6", 0], "vae": ["1", 2]},
        "class_type": "VAEDecode",
    }
    wf["8"] = {
        "inputs": {"images": ["7", 0], "filename_prefix": "img2img_"},
        "class_type": "SaveImage",
    }
    return wf


# ── 测试 ───────────────────────────────────────────────────────────

class TestWorkflowToGraph:
    """核心转换函数 workflow_to_graph"""

    def test_minimal_txt2img_node_count(self):
        """最小文生图应返回 7 个节点 + 对应边"""
        wf = build_minimal_txt2img()
        g = cc.workflow_to_graph(wf)
        assert len(g["nodes"]) == 7
        assert len(g["edges"]) > 0
        assert g["layout"] == "dag"

    def test_img2img_node_count(self):
        """图生图含 LoadImage + VAEEncode 应返回 8 个节点"""
        wf = build_img_to_img()
        g = cc.workflow_to_graph(wf)
        assert len(g["nodes"]) == 8

    def test_node_fields(self):
        """每个节点应包含 id / type / title / category / pos / input_links / values / num_outputs"""
        g = cc.workflow_to_graph(build_minimal_txt2img())
        for n in g["nodes"]:
            assert "id" in n
            assert "type" in n
            assert "title" in n
            assert "category" in n
            assert isinstance(n["pos"], dict) and "x" in n["pos"] and "y" in n["pos"]
            assert isinstance(n["input_links"], list)
            assert isinstance(n["values"], dict)
            assert isinstance(n["num_outputs"], int)

    def test_checkpoint_loader_has_zero_input_links(self):
        """Load Checkpoint 没有输入连线（输入全是字面参数）"""
        g = cc.workflow_to_graph(build_minimal_txt2img())
        cl = next(n for n in g["nodes"] if n["type"] == "CheckpointLoaderSimple")
        assert len(cl["input_links"]) == 0

    def test_ksampler_has_many_input_links(self):
        """KSampler 应有 model / positive / negative / latent_image 4 条输入连线"""
        g = cc.workflow_to_graph(build_minimal_txt2img())
        ks = next(n for n in g["nodes"] if n["type"] == "KSampler")
        assert len(ks["input_links"]) == 4

    def test_edge_structure(self):
        """每条边应包含 from / from_slot / to / to_slot"""
        g = cc.workflow_to_graph(build_minimal_txt2img())
        for e in g["edges"]:
            assert "from" in e
            assert "from_slot" in e
            assert "to" in e
            assert "to_slot" in e

    def test_layout_is_topological(self):
        """拓扑布局：同一层节点 x 坐标相近"""
        g = cc.workflow_to_graph(build_minimal_txt2img())
        # CheckpointLoaderSimple (源) 应在最左列
        cl = next(n for n in g["nodes"] if n["type"] == "CheckpointLoaderSimple")
        # SaveImage (终点) 应在最右列
        si = next(n for n in g["nodes"] if n["type"] == "SaveImage")
        assert cl["pos"]["x"] < si["pos"]["x"], "源节点应在终点左侧"

    def test_empty_workflow(self):
        """空工作流返回空节点空边"""
        g = cc.workflow_to_graph({})
        assert g["nodes"] == []
        assert g["edges"] == []
        assert g["layout"] == "dag"


class TestAuxiliaryFunctions:
    """辅助函数测试"""

    def test_is_link_positive(self):
        """标准 ComfyUI 连线引用格式 ['nodeId', slot]"""
        assert cc._is_link(["5", 0]) is True
        assert cc._is_link(["12", 2]) is True

    def test_is_link_negative(self):
        """非连线值不应被误判"""
        assert cc._is_link("a cat") is False
        assert cc._is_link(42) is False
        assert cc._is_link(None) is False
        assert cc._is_link(7.0) is False
        assert cc._is_link([42, "str"]) is False   # 第一个元素不是 str
        assert cc._is_link([1, 2, 3]) is False   # 长度不是 2

    def test_short_val_truncates(self):
        """长值应截断"""
        assert len(cc._short_val("x" * 50)) <= 33  # 30 字符 + "…"

    def test_short_val_preserves_short(self):
        """短值应原样保留"""
        assert cc._short_val("cat") == "cat"

    def test_nid_from_kv(self):
        """非连线 int 值返回 None（不是节点 ID）"""
        assert cc._is_link(42) is False


class TestAssignLayout:
    """DAG 布局函数 _assign_layout"""

    def test_simple_chain(self):
        """简单链 A→B→C：应在递增的 x 列上"""
        nodes = [
            {"id": "A", "input_links": [], "num_outputs": 1},
            {"id": "B", "input_links": [{"from": "A", "from_slot": 0, "name": "in"}], "num_outputs": 1},
            {"id": "C", "input_links": [{"from": "B", "from_slot": 0, "name": "in"}], "num_outputs": 1},
        ]
        edges = [
            {"from": "A", "from_slot": 0, "to": "B", "to_slot": "in"},
            {"from": "B", "from_slot": 0, "to": "C", "to_slot": "in"},
        ]
        cc._assign_layout(nodes, edges)
        assert nodes[0]["pos"]["x"] < nodes[1]["pos"]["x"] < nodes[2]["pos"]["x"]

    def test_branch_nodes_same_column(self):
        """平行分支节点应在同一列"""
        nodes = [
            {"id": "Root", "input_links": [], "num_outputs": 2},
            {"id": "BranchL", "input_links": [{"from": "Root", "from_slot": 0, "name": "in"}], "num_outputs": 1},
            {"id": "BranchR", "input_links": [{"from": "Root", "from_slot": 0, "name": "in"}], "num_outputs": 1},
        ]
        edges = [
            {"from": "Root", "from_slot": 0, "to": "BranchL", "to_slot": "in"},
            {"from": "Root", "from_slot": 0, "to": "BranchR", "to_slot": "in"},
        ]
        cc._assign_layout(nodes, edges)
        assert nodes[1]["pos"]["x"] == nodes[2]["pos"]["x"], "分支节点应在同一列"


class TestNodeMeta:
    """节点元数据映射"""

    def test_common_node_types_have_meta(self):
        """核心节点类型都应有中文标题和分类"""
        for ct in ["CheckpointLoaderSimple", "CLIPTextEncode", "KSampler",
                    "VAEDecode", "VAEEncode", "SaveImage", "EmptyLatentImage",
                    "LoadImage"]:
            meta = cc._NODE_META.get(ct)
            assert meta is not None, f"{ct} 缺少元数据"
            assert len(meta) == 2
            assert isinstance(meta[0], str)  # title
            assert isinstance(meta[1], str)  # category
