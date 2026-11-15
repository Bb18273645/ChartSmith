# Copyright (c) 2026 Bb18273645.
# SPDX-License-Identifier: AGPL-3.0-or-later
# 本作品以 AGPL-3.0-or-later 授权；闭源商业使用需另行取得商业许可，详见 COMMERCIAL-LICENSE.md。
"""图匠的图片渲染器：把 ``layout.build_layout`` 的坐标画成 PNG。

用 Pillow 而不是浏览器截图：聊天平台只需要一张图，本地直接画既省掉一次网络往返，
也不依赖 AstrBot 的远程文转图服务。Pillow 是 AstrBot 自带的依赖，不用额外安装。

所有几何量都按逻辑像素给出，内部按 ``scale`` 倍超采样后缩小，保证文字和箭头不糊。
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# tone -> (边框/强调色, 底色, 文字色)
TONES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "neutral": ((148, 163, 184), (248, 250, 252), (15, 23, 42)),
    "brand": ((37, 99, 235), (239, 246, 255), (15, 23, 42)),
    "info": ((8, 145, 178), (236, 254, 255), (15, 23, 42)),
    "success": ((5, 150, 105), (236, 253, 245), (15, 23, 42)),
    "warn": ((217, 119, 6), (255, 251, 235), (15, 23, 42)),
    "error": ((220, 38, 38), (254, 242, 242), (15, 23, 42)),
}

WHITE = (255, 255, 255)
INK = (15, 23, 42)
MUTED = (100, 116, 139)
FAINT = (148, 163, 184)
EDGE = (100, 116, 139)
EDGE_DASHED = (148, 163, 184)

# 优先级从高到低：Windows / macOS / Linux 的常见中文字体，最后才退回拉丁字体
_REGULAR_FONTS = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "NotoSansCJK-Regular.ttc",
    "DejaVuSans.ttf",
)
_BOLD_FONTS = (
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyhbd.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf",
    "NotoSansCJK-Bold.ttc",
    "DejaVuSans-Bold.ttf",
)

_FONT_HINT: list[str] = []


def _astrbot_font_candidates() -> list[str]:
    """AstrBot 自带的字体文件（用户在 WebUI 装过的字体）优先使用。

    注意：``import astrbot`` 会顺带初始化 AstrBot 的配置文件，
    在插件目录里跑单元测试时会凭空多出一个 ``data/`` 目录。
    所以这里先看当前工作目录下有没有 ``data/``，没有就不去 import。
    """
    roots = [Path.cwd()]
    if env_root := os.environ.get("ASTRBOT_ROOT"):
        roots.insert(0, Path(env_root))
    for root in roots:
        if not (root / "data").is_dir():
            continue
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            data_dir = Path(get_astrbot_data_path())
        except Exception:  # 插件被单独测试时没有 AstrBot 环境
            data_dir = root / "data"
        return [str(data_dir / "font.ttf"), str(data_dir / "font-bold.ttf")]
    return []


def _load_font(
    px: int, bold: bool, font_path: str | None
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """按优先级找一个能显示中文的字体。

    Args:
        px: 字号（已按超采样放大后的像素值）。
        bold: 是否优先使用粗体。
        font_path: 用户显式配置的字体文件路径，优先于内置候选。

    Returns:
        Pillow 字体对象；全部候选都不可用时退回 Pillow 默认字体。
    """
    candidates: list[str] = []
    if font_path:
        candidates.append(font_path)
    astrbot_fonts = _astrbot_font_candidates()
    if bold and len(astrbot_fonts) > 1:
        candidates.append(astrbot_fonts[1])
    candidates.extend(astrbot_fonts)
    candidates.extend(_BOLD_FONTS if bold else _REGULAR_FONTS)
    for candidate in candidates:
        try:
            font = ImageFont.truetype(candidate, px)
        except (OSError, TypeError, ValueError):
            continue
        if not _FONT_HINT:
            _FONT_HINT.append(candidate)
        return font
    return ImageFont.load_default(size=px)


class TextMetrics:
    """按逻辑像素测量文本宽度，并缓存对应字号/字重的字体。"""

    def __init__(self, scale: int = 2, font_path: str | None = None) -> None:
        self.scale = max(1, int(scale))
        self.font_path = font_path
        self._fonts: dict[tuple[int, bool], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    def font(self, size: float, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """取得逻辑字号 ``size`` 对应的字体对象。"""
        key = (max(1, int(round(size))), bold)
        cached = self._fonts.get(key)
        if cached is None:
            cached = _load_font(max(1, int(round(key[0] * self.scale))), bold, self.font_path)
            self._fonts[key] = cached
        return cached

    def measure(self, text: str, size: float) -> float:
        """返回文本在逻辑像素下的宽度。"""
        if not text:
            return 0.0
        return float(self.font(size).getlength(text)) / self.scale


def resolve_font_path(font_path: str | None = None) -> str | None:
    """探测实际会使用的字体文件，供启动日志提示中文是否可显示。"""
    metrics = TextMetrics(scale=1, font_path=font_path)
    metrics.font(15)
    return _FONT_HINT[0] if _FONT_HINT else None


def render_layout(
    layout: dict,
    out_path: str | Path,
    font_path: str | None = None,
    scale: int = 2,
    max_width: int | None = None,
    max_height: int | None = None,
) -> Path:
    """把布局画成 PNG 并保存。

    Args:
        layout: ``layout.build_layout`` 的返回值。
        out_path: 输出 PNG 路径。
        font_path: 可选的字体文件路径。
        scale: 输出像素倍率。1 = 逻辑尺寸，2 = 两倍像素（手机上看更锐利），3 = 三倍。
        max_width: 输出宽度上限，超了就等比缩小（QQ 群图太大容易被压缩发糊）。
        max_height: 输出高度上限，超长竖图同样会等比缩小。

    Returns:
        实际写入的路径。

    Raises:
        ValueError: 布局里没有节点。
    """
    nodes = layout.get("nodes") or []
    if not nodes:
        raise ValueError("布局里没有节点")

    scale = max(1, min(3, int(scale)))
    # 内部至少 2 倍绘制，再缩到目标倍率：形状边缘平滑，文字也不糊
    oversample = max(2, scale)
    width, height = int(layout["width"]), int(layout["height"])
    canvas = Image.new("RGB", (width * oversample, height * oversample), WHITE)
    draw = ImageDraw.Draw(canvas)
    metrics = TextMetrics(oversample, font_path)

    def px(value: float) -> float:
        return value * oversample

    # 标题区
    has_subtitle = bool(layout.get("subtitle"))
    draw.text(
        (px(32), px(34)),
        layout.get("title") or "",
        font=metrics.font(22, bold=True),
        fill=INK,
        anchor="lm",
    )
    if has_subtitle:
        draw.text(
            (px(32), px(62)),
            layout["subtitle"],
            font=metrics.font(12),
            fill=MUTED,
            anchor="lm",
        )

    # 连线先画，压在节点下面
    for edge in layout.get("edges") or []:
        color = EDGE_DASHED if edge.get("dashed") else EDGE
        points = [(px(x), px(y)) for x, y in edge["points"]]
        if edge.get("dashed"):
            _dashed_polyline(
                draw, points, color, width=max(1, int(round(1.6 * scale))), scale=scale
            )
        elif len(points) >= 2:
            draw.line(points, fill=color, width=max(1, int(round(1.6 * scale))), joint="curve")
        _arrow_head(draw, points, color, scale)

    # 连线标签：白底小胶囊，压住线但不压节点
    for edge in layout.get("edges") or []:
        label = edge.get("label") or ""
        pos = edge.get("label_pos")
        if not label or not pos:
            continue
        text_w = metrics.measure(label, 12)
        cx, cy = px(pos[0]), px(pos[1])
        half_w, half_h = px(text_w / 2 + 5), px(10)
        draw.rounded_rectangle(
            [cx - half_w, cy - half_h, cx + half_w, cy + half_h],
            radius=px(4),
            fill=WHITE,
        )
        draw.text((cx, cy), label, font=metrics.font(12), fill=(71, 85, 105), anchor="mm")

    # 节点
    for node in nodes:
        x, y = px(node["x"]), px(node["y"])
        w, h = px(node["w"]), px(node["h"])
        border, fill, ink = TONES.get(node.get("tone"), TONES["neutral"])
        draw.rounded_rectangle(
            [x, y, x + w, y + h],
            radius=px(12),
            fill=fill,
            outline=border,
            width=max(1, int(round(1.4 * scale))),
        )
        # 左侧强调条
        draw.rounded_rectangle(
            [x + px(4), y + px(16), x + px(7), y + h - px(16)],
            radius=px(2),
            fill=border,
        )
        cx = x + w / 2
        if node.get("sub"):
            draw.text(
                (cx, y + h * 0.36),
                node["label"],
                font=metrics.font(15, bold=True),
                fill=ink,
                anchor="mm",
            )
            draw.text(
                (cx, y + h * 0.72),
                node["sub"],
                font=metrics.font(12),
                fill=MUTED,
                anchor="mm",
            )
        else:
            draw.text(
                (cx, y + h / 2),
                node["label"],
                font=metrics.font(15, bold=True),
                fill=ink,
                anchor="mm",
            )

    note = layout.get("note") or ""
    if note:
        draw.text(
            (px(32), px(height - 12)),
            note,
            font=metrics.font(11),
            fill=FAINT,
            anchor="lm",
        )

    final_size = (width * scale, height * scale)
    if oversample != scale:
        canvas = canvas.resize(final_size, Image.LANCZOS)
    canvas = _fit_canvas(canvas, max_width, max_height)

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="PNG", optimize=True)
    return target


def _fit_canvas(
    canvas: Image.Image,
    max_width: int | None,
    max_height: int | None,
) -> Image.Image:
    """把画布等比缩进给定上限；两个上限都不设或没超时原样返回。"""
    limit_w = int(max_width) if max_width else 0
    limit_h = int(max_height) if max_height else 0
    width, height = canvas.size
    ratios = [
        limit / size
        for limit, size in ((limit_w, width), (limit_h, height))
        if limit and size > limit
    ]
    if not ratios:
        return canvas
    factor = min(ratios)
    new_size = (max(1, round(width * factor)), max(1, round(height * factor)))
    return canvas.resize(new_size, Image.LANCZOS)


def image_size(path: str | Path) -> tuple[int, int]:
    """读 PNG 头拿到实际像素尺寸，供图片消息说明用。"""
    with Image.open(path) as image:
        return image.size


def _dashed_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    color: tuple[int, int, int],
    width: int,
    scale: int,
) -> None:
    """按段画虚线；折线拐角处重新起步，避免长短不一。"""
    dash, gap = 6.0 * scale, 5.0 * scale
    for start, end in zip(points, points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 0.5:
            continue
        ux, uy = dx / length, dy / length
        offset = 0.0
        while offset < length:
            stop = min(offset + dash, length)
            draw.line(
                [
                    (start[0] + ux * offset, start[1] + uy * offset),
                    (start[0] + ux * stop, start[1] + uy * stop),
                ],
                fill=color,
                width=width,
            )
            offset = stop + gap


def _arrow_head(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    color: tuple[int, int, int],
    scale: int,
) -> None:
    """在折线终点画一个实心箭头，方向取最后一段。"""
    if len(points) < 2:
        return
    tip_x, tip_y = points[-1]
    prev_x, prev_y = points[-2]
    dx, dy = tip_x - prev_x, tip_y - prev_y
    length = math.hypot(dx, dy)
    if length < 0.5:
        return
    ux, uy = dx / length, dy / length
    size = 9.0 * scale
    half = 4.5 * scale
    base_x, base_y = tip_x - ux * size, tip_y - uy * size
    draw.polygon(
        [
            (tip_x, tip_y),
            (base_x - uy * half, base_y + ux * half),
            (base_x + uy * half, base_y - ux * half),
        ],
        fill=color,
    )


__all__ = ["TONES", "TextMetrics", "image_size", "render_layout", "resolve_font_path"]
