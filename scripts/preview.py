#!/usr/bin/env python
# Copyright (c) 2026 Bb18273645.
# SPDX-License-Identifier: AGPL-3.0-or-later
# 本作品以 AGPL-3.0-or-later 授权；闭源商业使用需另行取得商业许可，详见 COMMERCIAL-LICENSE.md。
"""生成示例图片，用眼睛验收版式。

用法：python scripts/preview.py [输出目录]
没有安装 Pillow 时只输出 SVG 风格的坐标摘要（这里不生成预览）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import layout  # noqa: E402
import render  # noqa: E402
from examples import SAMPLES  # noqa: E402


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = render.TextMetrics(scale=2)
    font = render.resolve_font_path()
    print(f"字体：{font}")

    for name, spec in SAMPLES.items():
        drawing = layout.build_layout_auto(spec, measure=metrics.measure)
        png = render.render_layout(
            drawing,
            out_dir / f"{name}.png",
            scale=2,
            max_width=2048,
            max_height=3200,
        )
        width, height = render.image_size(png)
        print(
            f"{name}.png  {width}x{height}（{drawing['direction']} 排版）  "
            f"{len(drawing['nodes'])} 节点 / {len(drawing['edges'])} 连线  "
            f"{png.stat().st_size // 1024} KB"
            + (f"  note={drawing['note']}" if drawing["note"] else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
