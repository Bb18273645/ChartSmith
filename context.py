# Copyright (c) 2026 Bb18273645.
# SPDX-License-Identifier: AGPL-3.0-or-later
# 本作品以 AGPL-3.0-or-later 授权；闭源商业使用需另行取得商业许可，详见 COMMERCIAL-LICENSE.md。
"""从最近对话里提取图表需要的上下文（标题 / 标签）。

只做纯文本启发式，不调用模型、不联网：拿最近几条消息，抽出里面像「专有名词」的片段
（反引号内容、CamelCase 标识符、全大写缩写、中文名词短语），在模型没给标题或标签时兜底。

目标定位是「别把上下文丢了」，而不是替代模型命名——模型给了标题/标签就一律不动。
"""

from __future__ import annotations

import re

# 模型偷懒时会写的通名标题：遇到这些才用上下文自动命名
GENERIC_TITLES = frozenset(
    {
        "结构图",
        "流程图",
        "示意图",
        "架构图",
        "拓扑图",
        "关系图",
        "图",
        "结构",
        "流程",
        "diagram",
        "chart",
        "flowchart",
    }
)

_CODE_SPAN = re.compile(r"`([^`\n]{1,32})`")
_QUOTED = re.compile(r"[「『“\"]([^」』”\"\n]{1,24})[」』”\"]")
_ASCII_TERM = re.compile(r"[A-Za-z][A-Za-z0-9_.+#-]{1,23}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,16}")
# 中文片段内部的连接词：切开后才不会把「从设备环境到判定结果」当成一个词
_CJK_SPLIT = re.compile(r"[到和与跟及或而]")
_URL = re.compile(r"https?://\S+")
_FENCE = re.compile(r"```.*?```", re.S)
# 「画一下 / 帮我画 / 来张图」这类请求前缀，做标题时要剥掉
_REQUEST_PREFIX = re.compile(
    r"^[\s/／,，:：]*(?:帮我|请|麻烦|可以|能不能|能)?\s*"
    r"(?:画一下|画个|画一张|画一幅|画|来一张图|来张图|来个图|来张|出个图|生成一张图|生成图|可视化一下|做个图|做张图)"
    r"[\s,，:：]*"
)
# 指代不明的开头：留作标题会变成「这条链路」这种没信息量的短语
_DEICTIC = re.compile(r"^(?:这条|这个|该|它|刚才|上面|前面|这张|这些|那些|这样|那边|这里|那样)")
_TRAILING = re.compile(r"[\s。！？!?，,、；;：:]+$")
_ACK = re.compile(r"(?:谢谢|多谢|感谢|烦请|辛苦)[啦了哈呀！!。]*$")
# 纯指令/指代短语不能当术语（否则图里会出现「画一下这条链路」这种标签）
_REQUEST_ONLY = re.compile(
    r"^(?:画一下|画个|画一张|画一幅|画|来一张图|来张图|来个图|出个图|生成一张图|生成图|"
    r"可视化一下|做个图|做张图|如图|下图|上图|这张图|这个图|那个图)$"
)
# 问句碎片（「这一串是什么顺序」）当标签毫无信息量，直接丢
_QUESTION_HINTS = ("什么", "怎么", "如何", "为什么", "哪", "多少", "是不是", "有没有", "吗", "呢", "吧")
# 以这些词开头的中文片段基本是动词短语（「先看」「采集的信号」），不适合当标签
_VERB_PREFIXES = ("先", "再", "然后", "所以", "但是", "而且", "如果", "因为", "可以", "需要", "应该", "不要", "接着", "最后", "以及", "还是", "可能", "至少")

# 句首句尾常见的虚词/连接词，中文片段两端剥掉
_CJK_EDGE_FILLER = set("从到和与跟了的着是在把被让就都也再又还并而或及等这那么一个种些我们你们他们您我你它")
_ASCII_STOP = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "http",
    "https",
    "com",
    "www",
    "png",
    "jpg",
}


def _clean(text: object) -> str:
    """压成单行、去掉 URL 和代码块围栏内容。"""
    plain = " ".join(str(text or "").split())
    plain = _FENCE.sub(" ", plain)
    plain = _URL.sub(" ", plain)
    return plain.strip()


def _trim_cjk(run: str) -> str:
    """剥掉中文片段两端的虚词，剩下的才算候选术语。"""
    start, end = 0, len(run)
    while start < end and run[start] in _CJK_EDGE_FILLER:
        start += 1
    while end > start and run[end - 1] in _CJK_EDGE_FILLER:
        end -= 1
    return run[start:end]


def _looks_like_term(word: str) -> bool:
    """ASCII 词：只要大写缩写、驼峰、带数字或符号的，普通小写英文单词不要。"""
    if len(word) < 2 or word.lower() in _ASCII_STOP:
        return False
    return any(ch.isupper() for ch in word) or any(ch.isdigit() for ch in word) or any(
        ch in "._+#-" for ch in word
    )


def extract_terms(texts: list[str], limit: int = 8) -> list[str]:
    """从最近对话里按「信号强度」抽候选术语。

    优先级：反引号内容 > 引号内容 > 标识符（驼峰/缩写/带数字） > 中文名词片段。

    Args:
        texts: 最近的对话文本，越新越靠前。
        limit: 最多返回多少个术语。

    Returns:
        去重后的术语列表，按出现顺序排列。
    """
    if limit <= 0:
        return []
    bucket: list[str] = []
    for text in texts:
        plain = _REQUEST_PREFIX.sub("", _clean(text)).strip()
        if not plain:
            continue
        bucket.extend(span.strip() for span in _CODE_SPAN.findall(plain))
        bucket.extend(span.strip() for span in _QUOTED.findall(plain))
        bucket.extend(word for word in _ASCII_TERM.findall(plain) if _looks_like_term(word))
        for run in _CJK_RUN.findall(plain):
            for piece in _CJK_SPLIT.split(run):
                piece = piece.strip()
                # 指代/指令短语（「这条链路」）在剥虚词前就要丢掉，否则会剩下「条链路」
                if not piece or _DEICTIC.match(piece) or _REQUEST_ONLY.match(piece):
                    continue
                candidate = _trim_cjk(piece)
                if candidate and not _DEICTIC.match(candidate):
                    bucket.append(candidate)

    terms: list[str] = []
    seen: set[str] = set()
    for term in bucket:
        term = term.strip(" .,:;!?、。，：；！？")
        if len(term) < 2 or len(term) > 24:
            continue
        key = term.lower()
        if key in seen or term in GENERIC_TITLES:
            continue
        if _REQUEST_ONLY.match(term) or _DEICTIC.match(term):
            continue
        if any(hint in term for hint in _QUESTION_HINTS):
            continue
        if term.startswith(_VERB_PREFIXES):
            continue
        # 带「的」的片段大概率是短语（采集的信号），留给标签不合适
        if "的" in term and len(term) > 2:
            continue
        # 已经有更长的术语包含它（例如先收到 "Play Integrity" 再收到 "Play"）就跳过
        if any(key in existing.lower() for existing in terms):
            continue
        seen.add(key)
        terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def _topic_candidate(text: object) -> str:
    """把一条消息整理成可以当标题的短句（剥掉请求前缀、代码标记、客套尾巴）。"""
    plain = _clean(text).lstrip("/／")
    plain = _REQUEST_PREFIX.sub("", plain)
    for token in ("`", "「", "」", "『", "』", '"', "'", "“", "”"):
        plain = plain.replace(token, "")
    plain = " ".join(plain.split())
    plain = _ACK.sub("", plain)
    plain = re.split(r"[。！？!?]", plain, maxsplit=1)[0]
    return _TRAILING.sub("", plain).strip()


def topic_from(texts: list[str], limit: int = 24, terms: list[str] | None = None) -> str:
    """取一个能当标题的短句；当前消息不够具体时用术语拼一个。

    只从**当前这条消息**里找句子（历史消息容易是问句或闲聊，拼出来的标题很怪），
    历史消息只通过 ``terms`` 贡献专有名词。

    Args:
        texts: 最近的对话文本，越新越靠前；只使用第一个元素。
        limit: 标题最大字数。
        terms: 抽取出的术语，句子不够具体时用它拼标题。

    Returns:
        标题候选；实在没有内容时返回空串。
    """
    if texts:
        candidate = _topic_candidate(texts[0])
        if len(candidate) >= 4 and not _DEICTIC.match(candidate):
            return candidate if len(candidate) <= limit else candidate[: limit - 1] + "…"

    if terms:
        joined = " · ".join(term for term in terms[:3] if term)
        if joined:
            return joined if len(joined) <= limit else joined[: limit - 1] + "…"
    return ""


def parse_history(history: object, limit: int = 6) -> list[str]:
    """把 AstrBot 会话历史（OpenAI 格式）转成最近的文本列表。

    Args:
        history: ``Conversation.history`` 解析出来的列表，元素形如
            ``{"role": "user", "content": "..."}``，``content`` 也可能是分段列表。
        limit: 最多取多少条。

    Returns:
        文本列表，**越新越靠前**；跳过 system/tool 与空内容。
    """
    if not isinstance(history, list) or limit <= 0:
        return []
    texts: list[str] = []
    for item in reversed(history):
        if len(texts) >= limit:
            break
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            continue
        content = item.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if not isinstance(content, str):
            continue
        cleaned = _clean(content)
        if cleaned:
            texts.append(cleaned[:400])
    return texts


def fill_spec(
    spec: dict,
    terms: list[str],
    topic: str,
    max_labels: int = 8,
) -> tuple[dict, list[str]]:
    """用上下文补齐 spec 里缺失的标题与节点标签（只补不改）。

    Args:
        spec: 模型给的结构字典，不会被原地修改。
        terms: ``extract_terms`` 的结果。
        topic: ``topic_from`` 的结果，用作兜底标题。
        max_labels: 最多自动补多少个节点标签。

    Returns:
        ``(新的 spec, 补过的字段列表)``，字段名形如 ``title``、``label:gw``。
    """
    filled: list[str] = []
    result = dict(spec)

    title = str(result.get("title") or "").strip()
    if (not title or title.lower() in GENERIC_TITLES) and topic:
        result["title"] = topic
        filled.append("title")

    raw_nodes = result.get("nodes")
    if isinstance(raw_nodes, list) and terms:
        nodes: list = []
        pool = [term for term in terms if term]
        used = 0
        for raw in raw_nodes:
            if not isinstance(raw, dict):
                nodes.append(raw)
                continue
            node = dict(raw)
            label = str(node.get("label") or "").strip()
            node_id = str(node.get("id") or "").strip()
            if (not label or label == node_id) and used < max_labels and used < len(pool):
                node["label"] = pool[used]
                used += 1
                filled.append(f"label:{node_id or used}")
            nodes.append(node)
        result["nodes"] = nodes

    return result, filled


__all__ = [
    "GENERIC_TITLES",
    "extract_terms",
    "fill_spec",
    "parse_history",
    "topic_from",
]
