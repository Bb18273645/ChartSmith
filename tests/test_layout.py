# Copyright (c) 2026 Bb18273645.
# SPDX-License-Identifier: AGPL-3.0-or-later
# 本作品以 AGPL-3.0-or-later 授权；闭源商业使用需另行取得商业许可，详见 COMMERCIAL-LICENSE.md。
"""布局引擎的单元测试（纯标准库，不需要 Pillow 和 AstrBot）。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import layout  # noqa: E402


def chain_spec(count: int, direction: str = "TB") -> dict:
    """生成一条 a0 -> a1 -> ... 的直链。"""
    nodes = [{"id": f"a{i}", "label": f"节点{i}"} for i in range(count)]
    edges = [{"from": f"a{i}", "to": f"a{i + 1}", "label": f"步骤{i}"} for i in range(count - 1)]
    return {"title": "直链", "direction": direction, "nodes": nodes, "edges": edges}


class NormalizeTest(unittest.TestCase):
    def test_drops_duplicates_self_loops_and_unknown_edges(self):
        spec = {
            "nodes": [
                {"id": "a", "label": "A"},
                {"id": "a", "label": "重复"},
                {"id": "b", "label": "B"},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "a", "to": "b"},
                {"from": "a", "to": "a"},
                {"from": "a", "to": "ghost"},
            ],
        }
        data = layout.normalize(spec)
        self.assertEqual([n["id"] for n in data["nodes"]], ["a", "b"])
        self.assertEqual(len(data["edges"]), 1)
        self.assertEqual(data["dropped"], 1 + 3)

    def test_clips_long_text_and_unknown_tone(self):
        spec = {
            "nodes": [
                {
                    "id": "a",
                    "label": "这是一个非常非常非常非常长的节点标题",
                    "sub": "x" * 40,
                    "tone": "rainbow",
                }
            ]
        }
        data = layout.normalize(spec)
        node = data["nodes"][0]
        self.assertLessEqual(len(node["label"]), layout.LABEL_MAX_CHARS)
        self.assertLessEqual(len(node["sub"]), layout.SUB_MAX_CHARS)
        self.assertEqual(node["tone"], "neutral")

    def test_direction_falls_back_to_tb(self):
        self.assertEqual(layout.normalize({"direction": "diagonal"})["direction"], "TB")
        self.assertEqual(layout.normalize({"direction": "lr"})["direction"], "LR")


class LayerTest(unittest.TestCase):
    def test_chain_is_one_node_per_row(self):
        drawing = layout.build_layout(chain_spec(5))
        self.assertEqual(len(drawing["nodes"]), 5)
        rows = sorted({n["layer"] for n in drawing["nodes"]})
        self.assertEqual(rows, [0, 1, 2, 3, 4])
        self.assertEqual(len({n["layer"] for n in drawing["nodes"]}), 5)
        # 每层只有一个节点时应当水平居中对齐
        self.assertEqual(len({round(n["x"]) for n in drawing["nodes"]}), 1)

    def test_fan_out_gives_multiple_columns(self):
        spec = {
            "nodes": [{"id": c, "label": c} for c in ("root", "a", "b", "c")],
            "edges": [
                {"from": "root", "to": "a"},
                {"from": "root", "to": "b"},
                {"from": "root", "to": "c"},
            ],
        }
        drawing = layout.build_layout(spec)
        layers = {n["id"]: n["layer"] for n in drawing["nodes"]}
        self.assertEqual(layers["root"], 0)
        self.assertEqual({layers["a"], layers["b"], layers["c"]}, {1})
        xs = sorted({round(n["x"]) for n in drawing["nodes"] if n["layer"] == 1})
        self.assertEqual(len(xs), 3)

    def test_cycle_is_laid_out_not_collapsed(self):
        spec = {
            "nodes": [{"id": c, "label": c} for c in "abc"],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
                {"from": "c", "to": "a"},
            ],
        }
        drawing = layout.build_layout(spec)
        self.assertEqual(len(drawing["nodes"]), 3)
        self.assertGreater(len({n["layer"] for n in drawing["nodes"]}), 1)
        self.assertEqual(len(drawing["edges"]), 3)

    def test_long_title_widens_canvas(self):
        short = layout.build_layout({"title": "短", "nodes": [{"id": "a", "label": "A"}]})
        long = layout.build_layout({"title": "一" * 30, "nodes": [{"id": "a", "label": "A"}]})
        self.assertGreater(long["width"], short["width"])
        # 估算宽度：中文按 1 字宽 × 字号，画布至少要能放下标题 + 两侧留白
        self.assertGreaterEqual(long["width"], 30 * layout.TITLE_SIZE + layout.PAD * 2)

    def test_no_nodes_raises(self):
        with self.assertRaises(ValueError):
            layout.build_layout({"nodes": [], "edges": []})


class GeometryTest(unittest.TestCase):
    def test_nodes_never_overlap(self):
        spec = {
            "nodes": [{"id": c, "label": c} for c in ("a", "b", "c", "d", "e")],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "a", "to": "c"},
                {"from": "b", "to": "d"},
                {"from": "c", "to": "d"},
                {"from": "d", "to": "e"},
            ],
        }
        nodes = layout.build_layout(spec)["nodes"]
        for i, left in enumerate(nodes):
            for right in nodes[i + 1 :]:
                overlap_x = (
                    left["x"] < right["x"] + right["w"] and right["x"] < left["x"] + left["w"]
                )
                overlap_y = (
                    left["y"] < right["y"] + right["h"] and right["y"] < left["y"] + left["h"]
                )
                self.assertFalse(overlap_x and overlap_y, f"{left['id']} 与 {right['id']} 重叠")

    def test_edge_points_stay_inside_canvas(self):
        spec = {
            "nodes": [{"id": c, "label": c} for c in ("a", "b", "c")],
            "edges": [
                {"from": "a", "to": "b", "style": "dashed"},
                {"from": "b", "to": "c"},
                {"from": "c", "to": "a"},
            ],
        }
        drawing = layout.build_layout(spec)
        for edge in drawing["edges"]:
            self.assertGreaterEqual(len(edge["points"]), 4)
            for x, y in edge["points"]:
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x, drawing["width"])
                self.assertLessEqual(y, drawing["height"])

    def test_trim_note_when_over_limit(self):
        drawing = layout.build_layout(chain_spec(20), max_nodes=8)
        self.assertEqual(len(drawing["nodes"]), 8)
        self.assertIn("已省略", drawing["note"])

    def test_lr_moves_along_x(self):
        drawing = layout.build_layout(chain_spec(4, direction="LR"))
        xs = [n["x"] for n in sorted(drawing["nodes"], key=lambda n: n["layer"])]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len({round(n["y"]) for n in drawing["nodes"]}), 1)
        self.assertEqual(drawing["direction"], "LR")

    def test_same_layer_edge_routes_around(self):
        # 最长路径分层不会产生同层边，这里直接单测走线函数：同层边必须绕行，
        # 不能画成一条零长度的箭头。
        src = {"x": 100.0, "y": 200.0, "w": 180, "h": 64}
        dst = {"x": 340.0, "y": 200.0, "w": 180, "h": 64}
        points, label_pos = layout._route_same(
            src, dst, "TB", header=90, out_ratio=0.5, in_ratio=0.5
        )
        self.assertEqual(len(points), 4)
        self.assertGreater(len({round(p[1]) for p in points}), 1)
        self.assertLess(min(p[1] for p in points), src["y"])
        self.assertIsNotNone(label_pos)

    def test_edge_slots_are_spread(self):
        spec = {
            "nodes": [{"id": c, "label": c} for c in ("root", "a", "b", "c")],
            "edges": [
                {"from": "root", "to": "a"},
                {"from": "root", "to": "b"},
                {"from": "root", "to": "c"},
            ],
        }
        drawing = layout.build_layout(spec)
        exits = [round(e["points"][0][0]) for e in drawing["edges"]]
        self.assertEqual(len(set(exits)), 3)


class TextCleanTest(unittest.TestCase):
    def test_emoji_replaced_or_removed(self):
        data = layout.normalize(
            {
                "title": "📊 状态",
                "nodes": [
                    {"id": "a", "label": "✅ 完成"},
                    {"id": "b", "label": "🚀 上线", "sub": "⚠ 注意"},
                    {"id": "c", "label": "❌ 失败"},
                ],
            }
        )
        self.assertEqual(data["title"], "状态")
        self.assertEqual([n["label"] for n in data["nodes"]], ["√ 完成", "上线", "× 失败"])
        self.assertEqual(data["nodes"][1]["sub"], "! 注意")

    def test_variation_selector_is_dropped(self):
        data = layout.normalize({"nodes": [{"id": "a", "label": "完成\ufe0f✅"}]})
        self.assertEqual(data["nodes"][0]["label"], "完成√")

    def test_plain_keeps_cjk_symbols(self):
        data = layout.normalize({"nodes": [{"id": "a", "label": "★→①②"}]})
        self.assertEqual(data["nodes"][0]["label"], "★→①②")


class AutoDirectionTest(unittest.TestCase):
    WIDE = {
        "nodes": [{"id": "root", "label": "入口"}]
        + [{"id": f"n{i}", "label": f"子{i}"} for i in range(8)],
        "edges": [{"from": "root", "to": f"n{i}"} for i in range(8)],
    }

    def test_wide_layer_switches_to_lr(self):
        self.assertEqual(layout.build_layout_auto(self.WIDE)["direction"], "LR")

    def test_long_chain_stays_tb(self):
        self.assertEqual(layout.build_layout_auto(chain_spec(12))["direction"], "TB")

    def test_auto_off_honours_tb(self):
        drawing = layout.build_layout_auto(self.WIDE, auto_direction=False)
        self.assertEqual(drawing["direction"], "TB")

    def test_explicit_lr_is_honoured(self):
        self.assertEqual(layout.build_layout_auto(chain_spec(3, "LR"))["direction"], "LR")

    def test_forced_direction_argument_wins(self):
        drawing = layout.build_layout_auto(self.WIDE, direction="TB")
        self.assertEqual(drawing["direction"], "TB")


if __name__ == "__main__":
    unittest.main()
