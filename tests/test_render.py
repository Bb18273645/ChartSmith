# Copyright (c) 2026 Bb18273645. 保留所有权利。
# 非商业用途免费；商业用途需作者书面同意；二改须注明上游并开源，详见 LICENSE。
"""渲染冒烟测试：有 Pillow 才跑。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import layout  # noqa: E402

try:
    from PIL import Image

    import render  # noqa: E402
except ImportError:  # pragma: no cover - 没装 Pillow 的环境直接跳过
    Image = None
    render = None

SAMPLE = {
    "title": "冒烟测试",
    "subtitle": "两行两列",
    "nodes": [
        {"id": "a", "label": "入口", "tone": "brand"},
        {"id": "b", "label": "处理", "sub": "worker", "tone": "success"},
        {"id": "c", "label": "分支", "tone": "warn"},
        {"id": "d", "label": "出口", "tone": "error"},
    ],
    "edges": [
        {"from": "a", "to": "b", "label": "调用"},
        {"from": "a", "to": "c", "label": "重试", "style": "dashed"},
        {"from": "b", "to": "d"},
        {"from": "c", "to": "d"},
        {"from": "d", "to": "a", "label": "回环", "style": "dashed"},
    ],
}


@unittest.skipIf(render is None, "需要 Pillow")
class RenderSmokeTest(unittest.TestCase):
    def test_output_is_two_times_logical_size(self):
        metrics = render.TextMetrics(scale=2)
        drawing = layout.build_layout(SAMPLE, measure=metrics.measure)
        with tempfile.TemporaryDirectory() as tmp:
            png = render.render_layout(drawing, Path(tmp) / "x.png", scale=2)
            self.assertTrue(png.exists())
            self.assertGreater(png.stat().st_size, 1000)
            self.assertEqual(render.image_size(png), (drawing["width"] * 2, drawing["height"] * 2))
            with Image.open(png) as image:
                self.assertEqual(image.mode, "RGB")

    def test_scale_sets_output_pixels(self):
        metrics = render.TextMetrics(scale=2)
        drawing = layout.build_layout(SAMPLE, measure=metrics.measure)
        logical = (drawing["width"], drawing["height"])
        with tempfile.TemporaryDirectory() as tmp:
            for scale in (1, 2, 3):
                png = render.render_layout(drawing, Path(tmp) / f"s{scale}.png", scale=scale)
                self.assertEqual(
                    render.image_size(png),
                    (logical[0] * scale, logical[1] * scale),
                    scale,
                )

    def test_max_width_caps_output_and_keeps_aspect(self):
        metrics = render.TextMetrics(scale=2)
        drawing = layout.build_layout(SAMPLE, measure=metrics.measure)
        with tempfile.TemporaryDirectory() as tmp:
            png = render.render_layout(drawing, Path(tmp) / "c.png", scale=2, max_width=400)
            width, height = render.image_size(png)
            self.assertEqual(width, 400)
            expected_h = round(drawing["height"] * 2 * 400 / (drawing["width"] * 2))
            self.assertEqual(height, expected_h)

    def test_max_height_caps_output_and_keeps_aspect(self):
        metrics = render.TextMetrics(scale=2)
        drawing = layout.build_layout(SAMPLE, measure=metrics.measure)
        with tempfile.TemporaryDirectory() as tmp:
            png = render.render_layout(drawing, Path(tmp) / "d.png", scale=2, max_height=300)
            width, height = render.image_size(png)
            self.assertEqual(height, 300)
            expected_w = round(drawing["width"] * 2 * 300 / (drawing["height"] * 2))
            self.assertEqual(width, expected_w)

    def test_measure_is_monotonic(self):
        metrics = render.TextMetrics(scale=2)
        self.assertLess(metrics.measure("ab", 15), metrics.measure("abcd", 15))
        self.assertGreater(metrics.measure("中文", 15), metrics.measure("ab", 15))

    def test_render_rejects_empty_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                render.render_layout(
                    {"width": 100, "height": 100, "nodes": [], "edges": []},
                    Path(tmp) / "empty.png",
                )


if __name__ == "__main__":
    unittest.main()
