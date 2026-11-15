# Copyright (c) 2026 Bb18273645. 保留所有权利。
# 非商业用途免费；商业用途需作者书面同意；二改须注明上游并开源，详见 LICENSE。
"""图匠（ChartSmith）——让 AstrBot 把结构化内容画成一张排版好的图片。

数据流：
    LLM --(render_diagram 工具, JSON 结构)--> 本插件
        --> layout.build_layout()  计算分层/坐标/走线
        --> render.render_layout() 用 Pillow 直接画成 PNG（2 倍超采样）
        --> yield event.image_result(本地文件)  图片直接发到聊天里

设计取舍见 README；提示词见 提示词.md。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

try:  # AstrBot 以 data.plugins.<插件名>.main 的方式导入，走包内相对导入
    from . import layout as _layout
    from . import render as _render
except ImportError:  # 直接 python main.py / 测试脚本里导入时的兜底
    import layout as _layout
    import render as _render

DEFAULTS = {
    "max_nodes": 16,
    "max_edges": 24,
    "per_minute": 6,
    "max_parallel": 2,
    "scale": 2,
    "max_width": 2048,
    "max_height": 3200,
    "auto_direction": True,
    "font_path": "",
}

CACHE_TTL_SECONDS = 7 * 24 * 3600
CACHE_MAX_FILES = 200

_USAGE = (
    "用法：/diagram {JSON}\n"
    '例：/diagram {"title":"登录流程","nodes":[{"id":"a","label":"用户"},'
    '{"id":"b","label":"网关"}],"edges":[{"from":"a","to":"b","label":"HTTPS"}]}'
)


def _strip_command(message: str) -> str:
    """从消息原文里剥掉指令名和代码块围栏，留下 JSON 正文。

    Args:
        message: 消息原文，形如 ``/diagram {"title": ...}``。

    Returns:
        去掉指令名与 ``` 围栏后的 JSON 文本；只有指令名没有正文时返回空串。
    """
    text = (message or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) == 1 and not text.startswith(("{", "[")):
        return ""
    if len(parts) == 2 and not parts[0].startswith(("{", "[")):
        text = parts[1].strip()
    if text.startswith("```"):
        text = text[3:]
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.lstrip()
    if text.endswith("```"):
        text = text[:-3].rstrip()
    return text


class Main(Star):
    """图匠插件入口。

    AstrBot 会以 ``Main(context=..., config=...)`` 实例化本类；``config`` 是
    ``_conf_schema.json`` 生成的配置字典，缺省值由 ``DEFAULTS`` 兜底。
    """

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.context: Context = context
        self.config: dict = config or {}

        cfg = dict(DEFAULTS)
        cfg.update({k: v for k, v in self.config.items() if k in DEFAULTS})
        self.cfg = cfg
        self.scale = max(1, min(3, int(cfg["scale"])))
        self.font_path = str(cfg["font_path"] or "").strip() or None

        # 渲染并发上限：Pillow 走线程池，但 CPU 核数有限，串几张更稳
        self._sem = asyncio.Semaphore(max(1, int(cfg["max_parallel"])))
        # 会话 -> 最近渲染时间戳，做每分钟限流
        self._hits: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=64))
        # 文本测量器：布局阶段拿它算节点宽度
        self._metrics = _render.TextMetrics(scale=self.scale, font_path=self.font_path)

        self.data_dir: Path = StarTools.get_data_dir()
        self.cache_dir: Path = self.data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        font = _render.resolve_font_path(self.font_path)
        logger.info(
            f"[chartsmith] 插件已加载，缓存目录：{self.cache_dir}；"
            f"中文字体：{font or '未找到（中文可能显示为方块，请配置 font_path）'}"
        )

    # ── LLM 工具 ──────────────────────────────────────────────────────
    @filter.llm_tool(name="render_diagram")
    async def render_diagram(self, event: AstrMessageEvent, spec: str = ""):
        """把结构化流程或架构画成一张排版好的图片，直接发到聊天里。

        适合：流程图、架构图、调用链、状态机、模块关系（3~16 个节点）。

        Args:
            spec(string): 图的 JSON 字符串，形如 {"title": "标题", "subtitle": "可选", "direction": "TB", "nodes": [{"id": "a", "label": "客户端", "sub": "浏览器", "tone": "neutral"}], "edges": [{"from": "a", "to": "b", "label": "HTTPS", "style": "solid"}]}。tone 取 neutral/brand/info/success/warn/error，style 取 solid/dashed；direction 取 TB/LR 可省略（省略时自动挑更好读的方向）。label 里不要用 emoji。不要提供坐标。
        """
        if not self._allow(event):
            yield event.plain_result("画图太频繁了，休息一下再画 🐢")
            return

        result = await self._produce(spec)
        if result.get("error"):
            yield event.plain_result(result["error"])
            return

        error = await self._deliver(event, result)
        if error:
            yield event.plain_result(error)
            return
        # 交给模型的工具结果：只说"已发出"，避免模型重复图里的名词
        yield (
            f"图已发出（{result['nodes']} 个节点，{result['width']}x{result['height']}px，"
            f"{result['direction']} 排版）。"
            "接下来用不超过两句话说明结论或读图要点，不要复述图中已有的名词。"
        )

    # ── 调试指令 ──────────────────────────────────────────────────────
    @filter.command("diagram")
    async def diagram_cmd(self, event: AstrMessageEvent):
        """手动渲染一张图，方便排查链路：/diagram {JSON}"""
        spec_text = _strip_command(event.get_message_str())
        if not spec_text:
            yield event.plain_result(_USAGE)
            return
        result = await self._produce(spec_text)
        if result.get("error"):
            yield event.plain_result(result["error"])
            return
        error = await self._deliver(event, result)
        if error:
            yield event.plain_result(error)

    @filter.command("图匠")
    async def tujiang_cmd(self, event: AstrMessageEvent):
        """/diagram 的中文别名。"""
        async for item in self.diagram_cmd(event):
            yield item

    # ── 内部 ─────────────────────────────────────────────────────────
    async def _produce(self, spec_text: str | dict) -> dict:
        """把 JSON 文本变成缓存里的 PNG。

        Args:
            spec_text: 模型或用户给出的结构 JSON。

        Returns:
            成功时含 ``png`` / ``note`` / ``nodes`` / ``width`` / ``height``，
            失败时含 ``error``。
        """
        try:
            spec = spec_text if isinstance(spec_text, dict) else json.loads(spec_text)
            if not isinstance(spec, dict):
                raise ValueError("最外层必须是 JSON 对象")
        except Exception as exc:  # noqa: BLE001 - 模型给的 JSON 什么都可能
            logger.warning(f"[chartsmith] 结构解析失败：{exc}；原文={str(spec_text)[:200]}")
            return {
                "error": "图没画出来：结构 JSON 不合法。请只输出一个 JSON 对象，"
                "包含 nodes 和 edges 两个数组。",
            }

        try:
            drawing = _layout.build_layout_auto(
                spec,
                measure=self._metrics.measure,
                max_nodes=int(self.cfg["max_nodes"]),
                max_edges=int(self.cfg["max_edges"]),
                auto_direction=bool(self.cfg["auto_direction"]),
            )
        except ValueError as exc:
            logger.warning(f"[chartsmith] 布局失败：{exc}")
            return {"error": f"图没画出来：{exc}"}

        cache_key = hashlib.sha256(
            json.dumps(
                [
                    spec,
                    self.scale,
                    int(self.cfg["max_width"]),
                    int(self.cfg["max_height"]),
                    bool(self.cfg["auto_direction"]),
                    int(self.cfg["max_nodes"]),
                    int(self.cfg["max_edges"]),
                ],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        png = self.cache_dir / f"{cache_key}.png"

        if not self._is_fresh(png):
            # 先画到临时文件再原子替换，避免并发或崩溃留下半张图
            staging = png.with_name(f"{png.stem}.tmp.png")
            try:
                async with self._sem:
                    await asyncio.to_thread(
                        _render.render_layout,
                        drawing,
                        staging,
                        self.font_path,
                        self.scale,
                        int(self.cfg["max_width"]),
                        int(self.cfg["max_height"]),
                    )
                os.replace(staging, png)
            except Exception as exc:  # noqa: BLE001 - 渲染失败要优雅降级
                logger.error(f"[chartsmith] 渲染失败：{exc}", exc_info=True)
                self._unlink(staging)
                return {"error": "图渲染失败了，先用文字回答你。"}
            self._evict_cache()

        width, height = _render.image_size(png)
        return {
            "png": png,
            "note": drawing["note"],
            "nodes": len(drawing["nodes"]),
            "direction": drawing["direction"],
            "width": width,
            "height": height,
        }

    async def _deliver(self, event: AstrMessageEvent, result: dict) -> str | None:
        """把图片和说明作为一条消息发出去。

        QQ（aiocqhttp）会把「文字 + 图片」合成一条消息，Telegram 会先发图再跟一行说明，
        两种情况都比「先发图、再单独发一条文字」干净。发送失败（NapCat 上传失败、
        TG 超时等）时不让异常冒到工具层，返回一句兜底文案。

        Args:
            event: 消息事件。
            result: ``_produce`` 的返回值。

        Returns:
            成功返回 None，失败返回要发给用户的文字。
        """
        png = Path(result["png"])
        try:
            if not png.is_file() or png.stat().st_size <= 0:
                raise FileNotFoundError(str(png))
        except OSError as exc:
            logger.error(f"[chartsmith] 图片文件不可用：{exc}")
            return "图渲染出来了但文件不见了，先用文字回答你。"

        message = event.make_result().file_image(str(png))
        if result.get("note"):
            message.message(result["note"])
        try:
            await event.send(message)
        except Exception as exc:  # noqa: BLE001 - 平台侧上传图片随时可能失败
            logger.error(f"[chartsmith] 图片发送失败：{exc}", exc_info=True)
            return "图片发送失败了（平台侧没接住这张图），先用文字回答你。"
        return None

    def _allow(self, event: AstrMessageEvent) -> bool:
        """按会话做每分钟限流，避免群里被刷图。"""
        limit = int(self.cfg["per_minute"])
        if limit <= 0:
            return True
        now = time.time()
        hits = self._hits[event.unified_msg_origin]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        # 会话很多时清一次空队列，避免长期运行时字典只增不减
        if len(self._hits) > 1000:
            for key in [k for k, v in self._hits.items() if not v]:
                self._hits.pop(key, None)
        return True

    @staticmethod
    def _is_fresh(path: Path) -> bool:
        """缓存文件是否存在且没过期。"""
        try:
            return time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS
        except OSError:
            return False

    def _evict_cache(self) -> None:
        """清掉过期缓存，并保证缓存文件数不超过上限（按最近使用淘汰）。"""
        try:
            files = [p for p in self.cache_dir.glob("*.png") if p.is_file()]
        except OSError:
            return
        now = time.time()
        alive: list[tuple[float, Path]] = []
        for path in files:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if now - mtime > CACHE_TTL_SECONDS:
                self._unlink(path)
                continue
            alive.append((mtime, path))
        if len(alive) <= CACHE_MAX_FILES:
            return
        alive.sort()
        for _, path in alive[: len(alive) - CACHE_MAX_FILES]:
            self._unlink(path)

    @staticmethod
    def _unlink(path: Path) -> None:
        """删除缓存文件，失败只记一条 debug 日志。"""
        try:
            os.unlink(path)
        except OSError:
            logger.debug(f"[chartsmith] 清理缓存失败：{path}")

    async def terminate(self) -> None:
        """插件被禁用或重载时清理内存状态。"""
        self._hits.clear()
