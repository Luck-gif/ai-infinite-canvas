"""无限画布 v5.0 · 工作流执行引擎（LibTV 风格：连线即执行）。

核心理念：
  - 用户拖线连接"文本节点→图片节点→视频节点"后，
    点击"执行此链路"即可全链路自动生成。
  - 引擎沿端口连线进行拓扑排序，依次执行每个节点的生成任务，
    上游输出自动成为下游输入。

用法：
  executor = WorkflowExecutor(comfy_client, intent_map)
  results = executor.execute_chain(root_node_id, nodes, port_edges)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

# 延迟导入，避免循环依赖
_comfy: Any = None
_im: Any = None


def _get_comfy():
    global _comfy
    if _comfy is None:
        import comfy_client as cc
        _comfy = cc
    return _comfy


def _get_intent_map():
    global _im
    if _im is None:
        import intent_map as im
        _im = im
    return _im


@dataclass
class PortSpec:
    """前端传来的端口定义（轻量版，不依赖前端 types.ts）。"""
    id: str
    label: str
    direction: str      # "input" | "output"
    type: str           # "image" | "text" | "video" | "audio" | "prompt" | "control"
    connectedTo: list[str] = field(default_factory=list)


@dataclass
class PortEdgeSpec:
    """前端传来的端口连线定义。"""
    id: str
    fromPortId: str
    toPortId: str
    label: str = ""


@dataclass
class NodeSpec:
    """前端传来的画布节点定义（精简版）。"""
    id: str
    kind: str           # "image" | "video" | "text" | "audio" | "control"
    prompt: str
    filename: str       # 已有输出文件名（已生成过的节点）
    mode: str           # GenMode: "txt2img" / "img2img" / "img2vid" 等
    width: int
    height: int
    steps: int
    cfg: float
    seed: int
    negative: str
    ports: list[PortSpec] = field(default_factory=list)
    # 视频专用
    frames: int = 33
    fps: int = 16
    endFrameImage: str = ""  # 尾帧文件名


@dataclass
class ExecutionResult:
    node_id: str
    status: str        # "skipped" | "queued" | "generated" | "failed"
    output_file: str   # 输出文件名（图片/视频）
    prompt_id: str     # ComfyUI prompt_id
    error: str


class WorkflowExecutor:
    """沿端口连线的拓扑执行器。"""

    def __init__(self, comfy_client=None, intent_map=None):
        self._cc = comfy_client or _get_comfy()
        self._im = intent_map or _get_intent_map()

    # ── 主入口 ───────────────────────────────────────────────────

    def execute_chain(
        self,
        root_node_id: str,
        nodes: list[dict[str, Any]],
        port_edges: list[dict[str, Any]],
        wait: bool = True,
        timeout: int = 900,
    ) -> list[ExecutionResult]:
        """从根节点出发，沿端口连线依次执行。

        Args:
            root_node_id: 链路起点节点 ID（通常是文本节点或已生成的图片节点）
            nodes: 画布节点列表（包含 kind/prompt/ports 等字段）
            port_edges: 端口间连线列表
            wait: 是否等待每个节点生成完成
            timeout: 单节点等待超时（秒）

        Returns:
            每个生成节点的执行结果（文本节点为 skipped）
        """
        # 1) 解析
        node_map: dict[str, NodeSpec] = {}
        for n in nodes:
            ns = self._parse_node(n)
            node_map[ns.id] = ns

        # 2) 沿端口连线 BFS 收集可达节点
        ordered_ids = self._topo_sort(root_node_id, node_map, port_edges)

        # 3) 逐个执行
        results: list[ExecutionResult] = []
        outputs: dict[str, str] = {}  # node_id → 输出文件名

        for nid in ordered_ids:
            node = node_map[nid]
            result = self._execute_one(node, port_edges, outputs, node_map, wait, timeout)
            results.append(result)
            if result.output_file:
                outputs[nid] = result.output_file

        return results

    # ── 内部 ─────────────────────────────────────────────────────

    def _parse_node(self, raw: dict[str, Any]) -> NodeSpec:
        return NodeSpec(
            id=raw.get("id", ""),
            kind=raw.get("kind", "image"),
            prompt=raw.get("prompt", ""),
            filename=raw.get("filename", ""),
            mode=raw.get("mode", "txt2img"),
            width=raw.get("width", 1024),
            height=raw.get("height", 1024),
            steps=raw.get("steps", 4),
            cfg=raw.get("cfg", 1.0),
            seed=raw.get("seed", 0),
            negative=raw.get("negative", ""),
            ports=[PortSpec(**p) for p in raw.get("ports", [])],
            frames=raw.get("frames", 33),
            fps=raw.get("fps", 16),
            endFrameImage=raw.get("endFrameImage", ""),
        )

    def _topo_sort(
        self,
        root_id: str,
        node_map: dict[str, NodeSpec],
        edges_raw: list[dict[str, Any]],
    ) -> list[str]:
        """沿端口连线进行 BFS 拓扑排序。"""
        edges: list[PortEdgeSpec] = [PortEdgeSpec(**e) for e in edges_raw]

        # 构建邻接表：from_port → [(to_port, to_node_id)]
        adj: dict[str, list[str]] = {nid: [] for nid in node_map}
        for e in edges:
            # 找到 from/to 端口所属的节点
            from_nid = self._find_node_for_port(e.fromPortId, node_map)
            to_nid = self._find_node_for_port(e.toPortId, node_map)
            if from_nid and to_nid:
                if to_nid not in adj[from_nid]:
                    adj[from_nid].append(to_nid)

        # BFS
        visited: set[str] = set()
        queue: deque[str] = deque([root_id])
        order: list[str] = []
        while queue:
            nid = queue.popleft()
            if nid in visited or nid not in node_map:
                continue
            visited.add(nid)
            order.append(nid)
            for next_nid in adj.get(nid, []):
                if next_nid not in visited:
                    queue.append(next_nid)
        return order

    def _find_node_for_port(self, port_id: str, node_map: dict[str, NodeSpec]) -> str | None:
        for nid, node in node_map.items():
            for p in node.ports:
                if p.id == port_id:
                    return nid
        return None

    def _resolve_inputs(
        self,
        node: NodeSpec,
        port_edges: list[dict[str, Any]],
        outputs: dict[str, str],
        node_map: dict[str, NodeSpec],
    ) -> dict[str, Any]:
        """收集上游节点输出，映射到当前节点的输入端口。"""
        inputs: dict[str, Any] = {"prompt": node.prompt, "image": None, "end_image": None}

        for e_raw in port_edges:
            e = PortEdgeSpec(**e_raw)
            to_nid = self._find_node_for_port(e.toPortId, node_map)
            if to_nid != node.id:
                continue

            from_nid = self._find_node_for_port(e.fromPortId, node_map)
            if not from_nid or from_nid not in outputs:
                continue

            # 看目标端口类型
            to_port_type = self._get_port_type(e.toPortId, node)
            upstream_file = outputs[from_nid]

            if to_port_type == "image" and e.toPortId.startswith("end"):
                inputs["end_image"] = upstream_file
            elif to_port_type == "image":
                inputs["image"] = upstream_file
            elif to_port_type == "prompt" or to_port_type == "text":
                # 文本节点输出 → 获取其 prompt 内容
                upstream_node = node_map.get(from_nid)
                if upstream_node:
                    inputs["prompt"] = upstream_node.prompt

        return inputs

    def _get_port_type(self, port_id: str, node: NodeSpec) -> str:
        for p in node.ports:
            if p.id == port_id:
                return p.type
        return "image"

    def _execute_one(
        self,
        node: NodeSpec,
        port_edges: list[dict[str, Any]],
        outputs: dict[str, str],
        node_map: dict[str, NodeSpec],
        wait: bool,
        timeout: int,
    ) -> ExecutionResult:
        """执行单个节点的生成任务。"""
        # 文本节点：跳过（纯数据节点）
        if node.kind == "text":
            return ExecutionResult(node.id, "skipped", node.prompt, "", "")

        # 已有输出：跳过（不再重复生成）
        if node.filename and node.filename not in ("", "pending"):
            # 但仍记录到 outputs 以便下游使用
            return ExecutionResult(node.id, "skipped", node.filename, "", "")

        # 解析上游输入
        resolved = self._resolve_inputs(node, port_edges, outputs, node_map)

        try:
            wf = self._build_workflow(node, resolved)
            if not wf:
                return ExecutionResult(node.id, "failed", "", "", "无法构建工作流：模型不可用")

            # 校验
            ok, issues = self._cc.validate_workflow(wf)
            if not ok:
                return ExecutionResult(node.id, "failed", "", "", f"校验失败: {issues}")

            # 提交
            prompt_id = self._cc.submit_workflow(wf)

            if wait:
                try:
                    result = self._cc.wait_for_result(prompt_id, timeout=timeout)
                    outs = result.get("outputs", {})
                    filenames: list[str] = []
                    for node_out in outs.values():
                        for img in node_out.get("images", []):
                            filenames.append(img.get("filename", ""))
                        for g in node_out.get("gifs", []):
                            filenames.append(g.get("filename", ""))
                    output_file = filenames[0] if filenames else ""
                    return ExecutionResult(node.id, "generated", output_file, prompt_id, "")
                except Exception as e:
                    return ExecutionResult(node.id, "failed", "", prompt_id, str(e)[:200])

            return ExecutionResult(node.id, "queued", "", prompt_id, "")

        except Exception as e:
            return ExecutionResult(node.id, "failed", "", "", str(e)[:200])

    def _build_workflow(self, node: NodeSpec, inputs: dict[str, Any]) -> dict[str, Any] | None:
        """根据节点 kind 和 mode 构建 ComfyUI 工作流。"""
        cc = self._cc

        if node.kind == "image":
            checkpoints = cc.list_checkpoints()
            if not checkpoints:
                return None
            ckpt = checkpoints[0]  # Qwen-Image 为首选
            prompt = str(inputs.get("prompt", node.prompt))
            image_ref = inputs.get("image")
            if image_ref and node.mode in ("img2img", "redraw", "expand"):
                return cc.build_img2img(
                    checkpoint=ckpt,
                    image_name=str(image_ref),
                    prompt=prompt,
                    negative=node.negative,
                    width=node.width, height=node.height,
                    steps=node.steps, cfg=node.cfg or 1.0,
                    seed=node.seed or 0, batch_size=1,
                )
            return cc.build_txt2img(
                checkpoint=ckpt,
                prompt=prompt,
                negative=node.negative,
                width=node.width, height=node.height,
                steps=node.steps, cfg=node.cfg or 1.0,
                seed=node.seed or 0, batch_size=1,
            )

        if node.kind == "video":
            image_ref = inputs.get("image")
            end_ref = inputs.get("end_image") or node.endFrameImage or ""
            prompt = str(inputs.get("prompt", node.prompt))

            if image_ref:
                return cc.build_img2vid(
                    image_name=str(image_ref),
                    prompt=prompt,
                    negative=node.negative,
                    width=node.width, height=node.height,
                    length=node.frames, fps=node.fps,
                    seed=node.seed or 0,
                    end_image_name=str(end_ref) if end_ref else "",
                )
            return cc.build_txt2vid(
                prompt=prompt,
                negative=node.negative,
                width=node.width, height=node.height,
                length=node.frames, fps=node.fps,
                seed=node.seed or 0,
            )

        if node.kind == "audio":
            # v5.2: 对接音频蓝图（CosyVoice2 / MusicGen / Stable Audio）
            from audio_blueprints import build_audio_workflow
            prompt = str(inputs.get("prompt", node.prompt))
            text = node.prompt or prompt
            # 从 mode 推导音频子类型（txt2audio / music / sfx）
            audio_mode = "tts"
            if node.mode in ("music", "musicgen"):
                audio_mode = "musicgen"
            elif node.mode in ("sfx", "stable_audio"):
                audio_mode = "stable_audio"
            result = build_audio_workflow(mode=audio_mode, text=text, prompt=prompt)
            if result and "workflow" in result:
                return result["workflow"]
            # 回退：音频节点无自定义节点时透传为文本输出
            return None

        if node.kind == "control":
            # 控制节点无独立生成，由下游图片/视频节点消费
            return None

        return None


# ── 模块级便捷函数 ──────────────────────────────────────────────

_executor: WorkflowExecutor | None = None


def get_executor() -> WorkflowExecutor:
    global _executor
    if _executor is None:
        _executor = WorkflowExecutor()
    return _executor


def execute_chain(
    root_node_id: str,
    nodes: list[dict[str, Any]],
    port_edges: list[dict[str, Any]],
    wait: bool = True,
    timeout: int = 900,
) -> list[ExecutionResult]:
    return get_executor().execute_chain(root_node_id, nodes, port_edges, wait, timeout)
