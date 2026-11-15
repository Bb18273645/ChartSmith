# Copyright (c) 2026 Bb18273645. 保留所有权利。
# 非商业用途免费；商业用途需作者书面同意；二改须注明上游并开源，详见 LICENSE。
"""图匠的分层布局引擎。

职责很窄：吃一份「节点 + 连线」的结构 JSON，吐出每个节点的像素坐标和每条连线的折线点。
坐标全是逻辑像素，渲染器负责按 scale 放大；文本宽度通过 ``measure`` 注入，
所以本模块只依赖标准库，可以在没有 Pillow 的环境里单独测试。

布局思路（详见 README 的「为什么不会乱」）：
1. 拓扑排序求最长路径分层；
2. 层内两轮重心（barycenter）排序，先正向再反向，压掉大部分交叉；
3. 坐标：节点等宽，层内居中，层间固定间距；
4. 走线：默认正交折线；同层边走上方（TB）或左侧（LR）的绕行线，回边走外侧。
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable

# ---------------------------------------------------------------------------
# 尺寸常量（逻辑像素）
# ---------------------------------------------------------------------------

NODE_H = 64
NODE_MIN_W = 156
NODE_MAX_W = 280

PAD = 32
HEADER_PLAIN = 72
HEADER_WITH_SUB = 90
FOOTER_H = 26

LABEL_SIZE = 15
SUB_SIZE = 12
TITLE_SIZE = 22
TITLE_MAX_CHARS = 32
LABEL_MAX_CHARS = 14
SUB_MAX_CHARS = 18
EDGE_LABEL_MAX_CHARS = 12

# 方向 -> (层间间距, 层内间距)
_GAPS = {
    "TB": (78, 48),
    "LR": (88, 34),
}
DIRECTIONS = ("TB", "LR")
TONES = ("neutral", "brand", "info", "success", "warn", "error")

Measure = Callable[[str, float], float]
Point = tuple[float, float]

# 聊天里高频、但微软雅黑/Noto CJK 里没有字形的 emoji，换成字体里有的同义符号，
# 否则渲染出来是一排"豆腐块"。⚠️✅❌ 这一批是最常被模型用坏的。
_EMOJI_MAP = {
    "✅": "√",
    "✔": "√",
    "☑": "√",
    "✓": "√",
    "❌": "×",
    "✖": "×",
    "✕": "×",
    "✗": "×",
    "❎": "×",
    "⚠": "!",
    "❗": "!",
    "❕": "!",
    "❓": "?",
    "❔": "?",
    "⭐": "★",
    "✨": "★",
    "▶": "→",
    "►": "→",
    "▸": "→",
    "◀": "←",
    "◄": "←",
}

# 剩下的 emoji 直接去掉：它们的区块在常见中文字体里都没有字形
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x1F1E6, 0x1F1FF),
    (0x1F3FB, 0x1F3FF),
    (0xFE00, 0xFE0F),
    (0x20E3, 0x20E3),
    (0x200D, 0x200D),
)


def _plain(text: object) -> str:
    """把文本压成单行，并把字体里没有字形的 emoji 换成等价符号或删掉。

    Args:
        text: 原始文本，可能带换行、emoji、零宽连接符。

    Returns:
        适合画进图里的单行文本。
    """
    raw = " ".join(str(text or "").split())
    for emoji, replacement in _EMOJI_MAP.items():
        raw = raw.replace(emoji, replacement)
    cleaned = "".join(
        ch for ch in raw if not any(start <= ord(ch) <= end for start, end in _EMOJI_RANGES)
    )
    return " ".join(cleaned.split())


def _clip(text: object, limit: int) -> str:
    """压缩空白、清理 emoji 并截断，超长时补省略号。"""
    plain = _plain(text)
    return plain if len(plain) <= limit else plain[: limit - 1] + "…"


def _estimate_width(text: str, size: float) -> float:
    """没有字体时的兜底估宽：中文按 1 字宽，ASCII 按 0.55 字宽。"""
    units = sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in text)
    return units * size


def normalize(
    spec: dict,
    max_nodes: int = 16,
    max_edges: int = 24,
) -> dict:
    """校验并裁剪模型给的结构，返回干净的节点/连线。

    Args:
        spec: 模型传入的结构字典。
        max_nodes: 节点上限，超出部分丢弃。
        max_edges: 连线上限，超出部分丢弃。

    Returns:
        含 title / subtitle / direction / nodes / edges / dropped 的字典，
        其中 ``dropped`` 是被丢弃的节点与连线数量之和。
    """
    raw_nodes = spec.get("nodes") or []
    raw_edges = spec.get("edges") or []

    nodes: list[dict] = []
    seen: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get("id") or "").strip()
        if not nid or nid in seen:
            continue
        seen.add(nid)
        tone = raw.get("tone")
        nodes.append(
            {
                "id": nid,
                "label": _clip(raw.get("label") or nid, LABEL_MAX_CHARS),
                "sub": _clip(raw.get("sub") or raw.get("sublabel") or "", SUB_MAX_CHARS),
                "tone": tone if tone in TONES else "neutral",
            }
        )
        if len(nodes) >= max(1, max_nodes):
            break

    edges: list[dict] = []
    kept: set[tuple[str, str]] = set()
    for raw in raw_edges:
        if not isinstance(raw, dict):
            continue
        src = str(raw.get("from") or "")
        dst = str(raw.get("to") or "")
        if src not in seen or dst not in seen or src == dst or (src, dst) in kept:
            continue
        kept.add((src, dst))
        edges.append(
            {
                "from": src,
                "to": dst,
                "label": _clip(raw.get("label") or "", EDGE_LABEL_MAX_CHARS),
                "dashed": str(raw.get("style") or "") == "dashed",
            }
        )
        if len(edges) >= max(1, max_edges):
            break

    direction = str(spec.get("direction") or "TB").strip().upper()
    if direction not in DIRECTIONS:
        direction = "TB"

    return {
        "title": _clip(spec.get("title") or "结构图", TITLE_MAX_CHARS),
        "subtitle": _clip(spec.get("subtitle") or "", TITLE_MAX_CHARS + 8),
        "direction": direction,
        "nodes": nodes,
        "edges": edges,
        "dropped": len(raw_nodes) - len(nodes) + len(raw_edges) - len(edges),
    }


def _kahn(node_ids: list[str], edges: list[dict]) -> tuple[dict[str, int], set[str]]:
    """跑一遍 Kahn 拓扑排序，返回最长路径分层与已分层节点。

    Args:
        node_ids: 全部节点 id，保持输入顺序。
        edges: 参与分层的连线；环上的边会被调用方先摘掉。

    Returns:
        ``(分层字典, 已分层节点集合)``；有环时集合会缺掉环上的节点。
    """
    succ: dict[str, list[str]] = defaultdict(list)
    indeg = {i: 0 for i in node_ids}
    for edge in edges:
        succ[edge["from"]].append(edge["to"])
        indeg[edge["to"]] += 1

    layer = {i: 0 for i in node_ids}
    queue = deque(i for i in node_ids if indeg[i] == 0)
    settled: set[str] = set()
    while queue:
        node_id = queue.popleft()
        settled.add(node_id)
        for nxt in succ[node_id]:
            layer[nxt] = max(layer[nxt], layer[node_id] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return layer, settled


def _assign_layers(node_ids: list[str], edges: list[dict]) -> dict[str, int]:
    """拓扑排序求最长路径分层；有环时先摘掉一条环内边再分层。

    摘掉的边不会被丢掉，绘制时会因为「终点层号 ≤ 起点层号」自动走外侧回边，
    所以环在图上就是一个绕回来的箭头，而不是把整张图压成一层。

    Args:
        node_ids: 全部节点 id，保持输入顺序。
        edges: 已校验的连线。

    Returns:
        ``{节点 id: 层号}``，层号从 0 开始。
    """
    working = list(edges)
    layer: dict[str, int] = {i: 0 for i in node_ids}
    for _ in range(len(working) + 1):
        layer, settled = _kahn(node_ids, working)
        if len(settled) == len(node_ids):
            return layer
        unsettled = {n for n in node_ids if n not in settled}
        candidates = [
            index
            for index, edge in enumerate(working)
            if edge["from"] in unsettled and edge["to"] in unsettled
        ]
        if not candidates:
            # 理论上到不了：环上每条边都至少有一端已分层
            break
        # 优先摘掉指向「入度最大」节点的那条边，先解开最紧的环
        indeg: dict[str, int] = defaultdict(int)
        for edge in working:
            indeg[edge["to"]] += 1
        victim = max(candidates, key=lambda index: (indeg[working[index]["to"]], -index))
        working.pop(victim)
    return layer


def _order_layers(
    node_ids: list[str],
    edges: list[dict],
    layer: dict[str, int],
) -> list[list[str]]:
    """层内按重心排序：先正向（父节点位置），再反向（子节点位置）。

    Args:
        node_ids: 全部节点 id，保持输入顺序。
        edges: 已校验的连线。
        layer: ``_assign_layers`` 的结果。

    Returns:
        逐层的节点 id 列表，层内顺序即绘制顺序。
    """
    grouped: dict[int, list[str]] = defaultdict(list)
    for node_id in node_ids:
        grouped[layer[node_id]].append(node_id)
    rows = [grouped[i] for i in sorted(grouped)]

    preds: dict[str, list[str]] = defaultdict(list)
    succs: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        preds[edge["to"]].append(edge["from"])
        succs[edge["from"]].append(edge["to"])

    def rehearse(index: int, neighbors: dict[str, list[str]], anchor: dict[str, int]) -> None:
        """按邻居层的位置重排第 index 层；没有邻居的节点保持原位。"""
        current = {nid: float(slot) for slot, nid in enumerate(rows[index])}

        def key(nid: str) -> float:
            known = [float(anchor[p]) for p in neighbors[nid] if p in anchor]
            return sum(known) / len(known) if known else current[nid]

        rows[index].sort(key=key)

    for _ in range(2):
        for index in range(1, len(rows)):
            rehearse(index, preds, {nid: k for k, nid in enumerate(rows[index - 1])})
        for index in range(len(rows) - 2, -1, -1):
            rehearse(index, succs, {nid: k for k, nid in enumerate(rows[index + 1])})
    return rows


def _spread_offsets(edge_ids_by_node: dict[str, list[int]], total: int) -> list[float]:
    """把同一节点的多条出/入边沿边均匀分开。

    Args:
        edge_ids_by_node: ``{节点 id: 该节点相关边在 edges 里的下标}``。
        total: 边总数。

    Returns:
        长度等于边数的列表，元素为该边在节点边上的 0~1 位置比例。
    """
    ratios = [0.5] * total
    for edge_ids in edge_ids_by_node.values():
        span = len(edge_ids) + 1
        for slot, edge_id in enumerate(edge_ids):
            ratios[edge_id] = (slot + 1) / span
    return ratios


def _route_forward(
    src: dict,
    dst: dict,
    direction: str,
    out_ratio: float,
    in_ratio: float,
    long_span: bool = False,
    gap: float = 0.0,
) -> tuple[list[Point], Point | None]:
    """正向边：层号递增，走「出口 → 层间中线 → 入口」的 S 形正交折线。

    Args:
        src: 起点方框。
        dst: 终点方框。
        direction: TB 或 LR。
        out_ratio: 出点在底边/右边上的位置比例。
        in_ratio: 入点在顶边/左边上的位置比例。
        long_span: 是否跨了不止一层。跨层边的中线会从中间层节点背后穿过，
            标签要挪到靠近起点的那段缝里才看得见。
        gap: 层间间距，配合 ``long_span`` 使用。

    Returns:
        ``(折线点列表, 标签中心点)``。
    """
    sx, sy, sw, sh = src["x"], src["y"], src["w"], src["h"]
    tx, ty, tw, th = dst["x"], dst["y"], dst["w"], dst["h"]

    if direction == "TB":
        exit_x = sx + sw * out_ratio
        entry_x = tx + tw * in_ratio
        y0, y1 = sy + sh, ty
        mid = (y0 + y1) / 2
        label = (exit_x, y0 + gap / 2) if long_span else ((exit_x + entry_x) / 2, mid - 9)
        return [(exit_x, y0), (exit_x, mid), (entry_x, mid), (entry_x, y1)], label

    exit_y = sy + sh * out_ratio
    entry_y = ty + th * in_ratio
    x0, x1 = sx + sw, tx
    mid = (x0 + x1) / 2
    label = (x0 + gap / 2, exit_y - 9) if long_span else (mid + 2, (exit_y + entry_y) / 2 - 9)
    return [(x0, exit_y), (mid, exit_y), (mid, entry_y), (x1, entry_y)], label


def _route_back(
    src: dict,
    dst: dict,
    direction: str,
    gap: float,
    from_layer: int,
    to_layer: int,
    last_layer: int,
    outer: float,
    stagger: float = 0.0,
    label_width: float = 0.0,
) -> tuple[list[Point], Point | None]:
    """回边：先走进层间通道，再从图外侧的轨道绕回目标。

    直接「贴着节点外沿横穿」会从同层其它节点背后穿过去（线被方框挡住），
    所以这里一律先进入层间通道（TB 是行间缝，LR 是列间缝），再借外侧轨道折回，
    最后从目标的上方/下方（TB）或左侧/右侧（LR）进入。

    Args:
        src: 起点方框。
        dst: 终点方框。
        direction: TB 或 LR。
        gap: 层间间距。
        from_layer: 起点层号。
        to_layer: 终点层号。
        last_layer: 最后一层的层号。
        outer: 外侧轨道坐标（TB 是 x，LR 是 y）。
        stagger: 同一轨道上的多条回边之间的错位偏移。
        label_width: 标签宽度，用来把标签放进画布内。

    Returns:
        ``(折线点列表, 标签中心点)``。
    """
    sx, sy, sw, sh = src["x"], src["y"], src["w"], src["h"]
    tx, ty, tw, th = dst["x"], dst["y"], dst["w"], dst["h"]

    if direction == "TB":
        center_x = sx + sw / 2
        entry_x = tx + tw / 2
        if from_layer < last_layer:  # 从源节点下方进入行间缝
            exit_pt = (center_x, sy + sh)
            band_src = sy + sh + gap / 2 + stagger
        else:  # 最后一层没有下方缝隙，改走上方
            exit_pt = (center_x, sy)
            band_src = sy - gap / 2 - stagger
        if to_layer > 0:  # 从目标节点上方进入
            band_tgt = ty - gap / 2 - stagger
            entry_pt = (entry_x, ty)
        else:  # 第一层没有上方缝隙，改从下方进入
            band_tgt = ty + th + gap / 2 + stagger
            entry_pt = (entry_x, ty + th)
        points = [
            exit_pt,
            (center_x, band_src),
            (outer, band_src),
            (outer, band_tgt),
            (entry_x, band_tgt),
            entry_pt,
        ]
        return points, (outer - label_width / 2 - 8, (band_src + band_tgt) / 2)

    center_y = sy + sh / 2
    entry_y = ty + th / 2
    if from_layer < last_layer:  # 从源节点右侧进入列间缝
        exit_pt = (sx + sw, center_y)
        band_src = sx + sw + gap / 2 + stagger
    else:  # 最右一列没有右侧缝隙，改走左侧
        exit_pt = (sx, center_y)
        band_src = sx - gap / 2 - stagger
    if to_layer > 0:  # 从目标节点左侧进入
        band_tgt = tx - gap / 2 - stagger
        entry_pt = (tx, entry_y)
    else:  # 第一列没有左侧缝隙，改从右侧进入
        band_tgt = tx + tw + gap / 2 + stagger
        entry_pt = (tx + tw, entry_y)
    points = [
        exit_pt,
        (band_src, center_y),
        (band_src, outer),
        (band_tgt, outer),
        (band_tgt, entry_y),
        entry_pt,
    ]
    return points, ((band_src + band_tgt) / 2, outer - 11)


def _route_same(
    src: dict,
    dst: dict,
    direction: str,
    header: float,
    out_ratio: float,
    in_ratio: float,
) -> tuple[list[Point], Point | None]:
    """同层边：贴着本行上方/下方（TB）或本列左侧（LR）绕一小段再进入。

    最长路径分层一般不会产生同层边，但回边被规则改道时仍可能落到同一层，
    所以这里保留一条不会退化成零长度箭头的走法。

    Args:
        src: 起点方框。
        dst: 终点方框。
        direction: TB 或 LR。
        header: 内容区起点 y。
        out_ratio: 出点在底边/右边上的位置比例。
        in_ratio: 入点在顶边/左边上的位置比例。

    Returns:
        ``(折线点列表, 标签中心点)``。
    """
    sx, sy, sw, sh = src["x"], src["y"], src["w"], src["h"]
    tx, ty, tw, th = dst["x"], dst["y"], dst["w"], dst["h"]

    if direction == "TB":
        exit_x = sx + sw * out_ratio
        entry_x = tx + tw * in_ratio
        if sy - 24 > header + 30:
            rail_y = sy - 24
            return [(exit_x, sy), (exit_x, rail_y), (entry_x, rail_y), (entry_x, ty)], (
                (exit_x + entry_x) / 2,
                rail_y - 9,
            )
        rail_y = sy + sh + 24
        return [
            (exit_x, sy + sh),
            (exit_x, rail_y),
            (entry_x, rail_y),
            (entry_x, ty + th),
        ], ((exit_x + entry_x) / 2, rail_y + 9)

    y0, y1 = sy + sh / 2, ty + th / 2
    if sx - 22 > 12:
        rail_x = sx - 22
        return [(sx, y0), (rail_x, y0), (rail_x, y1), (tx, y1)], (
            rail_x - 2,
            (y0 + y1) / 2,
        )
    rail_x = sx + sw + 22
    return [(sx + sw, y0), (rail_x, y0), (rail_x, y1), (tx + tw, y1)], (
        rail_x + 2,
        (y0 + y1) / 2,
    )


def build_layout(
    spec: dict,
    measure: Measure | None = None,
    max_nodes: int = 16,
    max_edges: int = 24,
    direction: str | None = None,
) -> dict:
    """把结构 JSON 变成可渲染的布局。

    Args:
        spec: 模型给的结构字典。
        measure: ``(text, size) -> 宽度`` 的测量函数，缺省用字符估算。
        max_nodes: 节点上限。
        max_edges: 连线上限。
        direction: 覆盖 spec 里的方向，取值 TB / LR。

    Returns:
        含 width / height / title / subtitle / note / nodes / edges 的布局字典。

    Raises:
        ValueError: 结构里没有可用节点。
    """
    measure = measure or _estimate_width
    data = normalize(spec, max_nodes, max_edges)
    if direction in DIRECTIONS:
        data["direction"] = direction

    nodes, edges = data["nodes"], data["edges"]
    if not nodes:
        raise ValueError("没有可画的节点")

    graph_direction = data["direction"]
    gap_along, gap_cross = _GAPS[graph_direction]
    layer = _assign_layers([n["id"] for n in nodes], edges)
    rows = _order_layers([n["id"] for n in nodes], edges, layer)

    # 等宽节点：一张图里所有方框同宽，视觉上更整齐
    need = NODE_MIN_W - 44
    for node in nodes:
        need = max(need, measure(node["label"], LABEL_SIZE))
        if node["sub"]:
            need = max(need, measure(node["sub"], SUB_SIZE))
    node_w = int(min(NODE_MAX_W, max(NODE_MIN_W, need + 44)))

    back_edges = [
        index for index, edge in enumerate(edges) if layer[edge["to"]] < layer[edge["from"]]
    ]
    has_same_layer_edge = any(layer[e["from"]] == layer[e["to"]] for e in edges)
    last_layer = max(layer.values())

    # 回边走图外侧的独立轨道：每条回边一条轨道，线条永远不被节点挡住
    rail_span = 52 + 10 * max(0, len(back_edges) - 1) if back_edges else 0
    extra_right = rail_span if graph_direction == "TB" else 0
    extra_bottom = rail_span if graph_direction == "LR" else 0
    if (
        graph_direction == "TB"
        and has_same_layer_edge
        and any(layer[e["from"]] == layer[e["to"]] == last_layer for e in edges)
    ):
        extra_bottom = 28

    row_spans = [len(row) * node_w + max(0, len(row) - 1) * gap_cross for row in rows]
    crowded = max(len(row) for row in rows) > 6

    if graph_direction == "TB":
        content_w = max(row_spans)
        content_h = len(rows) * NODE_H + max(0, len(rows) - 1) * gap_along
    else:
        content_w = len(rows) * node_w + max(0, len(rows) - 1) * gap_along
        content_h = max(row_spans)

    header = HEADER_WITH_SUB if data["subtitle"] else HEADER_PLAIN
    width = max(560, content_w) + PAD * 2 + extra_right
    height = header + content_h + extra_bottom + (FOOTER_H if crowded else 10)

    # 坐标：TB 按行、LR 按列，都需要在内容区居中
    boxes: dict[str, dict] = {}
    inner_w = width - PAD * 2 - extra_right
    for index, row in enumerate(rows):
        if graph_direction == "TB":
            start_x = PAD + max(0.0, (inner_w - row_spans[index]) / 2)
            for slot, node_id in enumerate(row):
                boxes[node_id] = {
                    "x": start_x + slot * (node_w + gap_cross),
                    "y": header + index * (NODE_H + gap_along),
                }
        else:
            start_y = header + max(0.0, (content_h - row_spans[index]) / 2)
            for slot, node_id in enumerate(row):
                boxes[node_id] = {
                    "x": PAD + index * (node_w + gap_along),
                    "y": start_y + slot * (NODE_H + gap_cross),
                }

    for node in nodes:
        boxes[node["id"]].update(
            {
                "id": node["id"],
                "label": node["label"],
                "sub": node["sub"],
                "tone": node["tone"],
                "w": node_w,
                "h": NODE_H,
                "layer": layer[node["id"]],
            }
        )

    # 每条边在源/目标节点上的接入位置（0~1）
    out_slots: dict[str, list[int]] = defaultdict(list)
    in_slots: dict[str, list[int]] = defaultdict(list)
    for index, edge in enumerate(edges):
        out_slots[edge["from"]].append(index)
        in_slots[edge["to"]].append(index)
    out_ratio = _spread_offsets(out_slots, len(edges))
    in_ratio = _spread_offsets(in_slots, len(edges))

    # 回边轨道坐标：TB 在右侧留白里竖着排，LR 在底部留白里横着排
    rails: dict[int, float] = {}
    rail_slots: dict[int, int] = {}
    for slot, edge_index in enumerate(back_edges):
        rail_slots[edge_index] = slot
        if graph_direction == "TB":
            rails[edge_index] = width - 26 - 10 * slot
        else:
            rails[edge_index] = header + content_h + 24 + 10 * slot

    routed: list[dict] = []
    for index, edge in enumerate(edges):
        src_box, dst_box = boxes[edge["from"]], boxes[edge["to"]]
        from_layer, to_layer = layer[edge["from"]], layer[edge["to"]]
        if from_layer < to_layer:
            points, label_pos = _route_forward(
                src_box,
                dst_box,
                graph_direction,
                out_ratio[index],
                in_ratio[index],
                long_span=to_layer - from_layer > 1,
                gap=gap_along,
            )
        elif from_layer > to_layer:
            points, label_pos = _route_back(
                src_box,
                dst_box,
                graph_direction,
                gap_along,
                from_layer,
                to_layer,
                last_layer,
                rails[index],
                stagger=5.0 * rail_slots[index],
                label_width=measure(edge["label"], 12) if edge["label"] else 0.0,
            )
        else:
            points, label_pos = _route_same(
                src_box,
                dst_box,
                graph_direction,
                header,
                out_ratio[index],
                in_ratio[index],
            )
        routed.append(
            {
                "from": edge["from"],
                "to": edge["to"],
                "label": edge["label"],
                "dashed": edge["dashed"],
                "points": points,
                "label_pos": label_pos,
            }
        )

    # 外侧走线可能顶出画布，按实际折线撑开，避免线被裁掉
    max_x = max((p[0] for e in routed for p in e["points"]), default=0.0)
    max_y = max((p[1] for e in routed for p in e["points"]), default=0.0)
    width = int(max(width, max_x + 12))
    height = int(max(height, max_y + 12))

    if data["dropped"] > 0:
        note = f"已省略 {data['dropped']} 个超出上限的节点/连线"
    elif crowded:
        note = "同一层节点较多，建议拆成两张图"
    else:
        note = ""

    return {
        "width": width,
        "height": height,
        "title": data["title"],
        "subtitle": data["subtitle"],
        "direction": graph_direction,
        "note": note,
        "nodes": list(boxes.values()),
        "edges": routed,
    }


def _phone_score(drawing: dict) -> float:
    """手机竖屏的可读性打分：图越窄，适配屏宽后字越大，所以宽度为主、高度为辅。"""
    return drawing["width"] + 0.2 * drawing["height"]


def build_layout_auto(
    spec: dict,
    measure: Measure | None = None,
    max_nodes: int = 16,
    max_edges: int = 24,
    direction: str | None = None,
    auto_direction: bool = True,
) -> dict:
    """按手机可读性自动挑方向：默认 TB，横排太宽时改画 LR。

    QQ / Telegram 的手机端都是「按屏幕宽度缩放」，宽图的字会被压得很小；
    所以这里优先选更窄的那一版，高度靠上下滑动解决。

    Args:
        spec: 模型给的结构字典。
        measure: 文本测量函数，缺省用字符估算。
        max_nodes: 节点上限。
        max_edges: 连线上限。
        direction: 外部强制方向（调试/测试用），传入后不再自动挑选。
        auto_direction: 是否允许自动换方向；关闭后完全按 spec/默认 TB。

    Returns:
        ``build_layout`` 的返回值，``direction`` 是实际采用的方向。
    """
    if direction in DIRECTIONS:
        return build_layout(spec, measure, max_nodes, max_edges, direction=direction)

    raw_direction = str(spec.get("direction") or "").strip().upper()
    explicit = raw_direction if raw_direction in DIRECTIONS else ""

    if explicit == "LR":
        return build_layout(spec, measure, max_nodes, max_edges, direction="LR")

    upright = build_layout(spec, measure, max_nodes, max_edges, direction="TB")
    # 明确要 TB、且不算太宽时，尊重模型的选择
    if not auto_direction or (explicit == "TB" and upright["width"] <= 1100):
        return upright

    sideways = build_layout(spec, measure, max_nodes, max_edges, direction="LR")
    return upright if _phone_score(upright) <= _phone_score(sideways) else sideways


__all__ = [
    "DIRECTIONS",
    "LABEL_SIZE",
    "NODE_H",
    "SUB_SIZE",
    "TITLE_SIZE",
    "TONES",
    "build_layout",
    "build_layout_auto",
    "normalize",
]
