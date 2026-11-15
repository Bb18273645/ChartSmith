# Copyright (c) 2026 Bb18273645.
# SPDX-License-Identifier: AGPL-3.0-or-later
# 本作品以 AGPL-3.0-or-later 授权；闭源商业使用需另行取得商业许可，详见 COMMERCIAL-LICENSE.md。
"""上下文补全的单元测试（纯标准库，不需要 AstrBot / Pillow）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import context  # noqa: E402


class ExtractTermsTest(unittest.TestCase):
    def test_prefers_code_spans_and_identifiers(self):
        texts = ["帮我看下 `Play Integrity` 里 DroidGuard 和 SUFS 的关系，还有设备环境"]
        terms = context.extract_terms(texts)
        self.assertIn("Play Integrity", terms)
        self.assertIn("DroidGuard", terms)
        self.assertIn("SUFS", terms)

    def test_skips_plain_lowercase_words(self):
        terms = context.extract_terms(["hello world fastapi JWT"])
        self.assertNotIn("hello", terms)
        self.assertNotIn("world", terms)
        self.assertIn("JWT", terms)

    def test_trims_chinese_function_words(self):
        terms = context.extract_terms(["从设备环境到判定结果"])
        self.assertIn("设备环境", terms)
        self.assertIn("判定结果", terms)

    def test_dedupes_and_limits(self):
        texts = ["`A1` `A1` `A2` `A3`"]
        terms = context.extract_terms(texts, limit=2)
        self.assertEqual(len(terms), 2)
        self.assertEqual(terms[0], "A1")

    def test_skips_request_and_deictic_phrases(self):
        terms = context.extract_terms(["画一下这条链路，设备环境到判定结果"])
        self.assertNotIn("画一下这条链路", terms)
        self.assertNotIn("这条链路", terms)
        self.assertNotIn("条链路", terms)
        self.assertIn("设备环境", terms)

    def test_zero_limit_and_empty_text(self):
        self.assertEqual(context.extract_terms(["`A1`"], limit=0), [])
        self.assertEqual(context.extract_terms(["   "]), [])


class TopicTest(unittest.TestCase):
    def test_takes_first_sentence_and_strips_request_prefix(self):
        topic = context.topic_from(["帮我画一下登录流程，要包含网关。谢谢"])
        self.assertEqual(topic, "登录流程，要包含网关")

    def test_limits_length(self):
        topic = context.topic_from(["一" * 40], limit=10)
        self.assertEqual(len(topic), 10)
        self.assertTrue(topic.endswith("…"))

    def test_deictic_message_falls_back_to_terms(self):
        topic = context.topic_from(
            ["画一下这条链路"], terms=["设备环境", "判定结果", "DroidGuard"]
        )
        self.assertEqual(topic, "设备环境 · 判定结果 · DroidGuard")

    def test_deictic_without_terms_returns_empty(self):
        self.assertEqual(context.topic_from(["画一下这条链路"]), "")

    def test_only_uses_current_message(self):
        topic = context.topic_from(["画一下", "历史里的 Play Integrity 是什么"] , terms=["DroidGuard"])
        self.assertEqual(topic, "DroidGuard")


class ParseHistoryTest(unittest.TestCase):
    HISTORY = [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": [{"type": "text", "text": "第二句"}]},
        {"role": "system", "content": "系统提示"},
        {"role": "tool", "content": "工具输出"},
        {"role": "user", "content": "   "},
        {"role": "assistant", "content": "最新一句"},
    ]

    def test_reversed_and_filtered(self):
        texts = context.parse_history(self.HISTORY, limit=10)
        self.assertEqual(texts, ["最新一句", "第二句", "第一句"])

    def test_limit(self):
        self.assertEqual(context.parse_history(self.HISTORY, limit=2), ["最新一句", "第二句"])

    def test_bad_input(self):
        self.assertEqual(context.parse_history(None), [])
        self.assertEqual(context.parse_history("not a list"), [])
        self.assertEqual(context.parse_history(self.HISTORY, limit=0), [])


class FillSpecTest(unittest.TestCase):
    def test_generic_title_replaced(self):
        spec = {"title": "结构图", "nodes": [{"id": "a", "label": "A"}]}
        filled_spec, filled = context.fill_spec(spec, ["DroidGuard"], "Play Integrity 检测链")
        self.assertEqual(filled_spec["title"], "Play Integrity 检测链")
        self.assertIn("title", filled)

    def test_explicit_title_kept(self):
        spec = {"title": "登录流程", "nodes": [{"id": "a", "label": "A"}]}
        filled_spec, filled = context.fill_spec(spec, ["DroidGuard"], "别的主题")
        self.assertEqual(filled_spec["title"], "登录流程")
        self.assertEqual(filled, [])

    def test_empty_labels_filled_in_order(self):
        spec = {
            "nodes": [
                {"id": "env", "label": ""},
                {"id": "scan", "label": "scan"},
                {"id": "res"},
            ]
        }
        filled_spec, filled = context.fill_spec(spec, ["设备环境", "判定"], "标题")
        labels = [node.get("label") for node in filled_spec["nodes"]]
        # 空 label 与 label==id 会被依次补上；术语用完就不再硬塞
        self.assertEqual(labels, ["设备环境", "判定", None])
        self.assertEqual(len([f for f in filled if f.startswith("label:")]), 2)

    def test_original_spec_not_mutated(self):
        spec = {"title": "结构图", "nodes": [{"id": "a", "label": ""}]}
        context.fill_spec(spec, ["T1"], "主题")
        self.assertEqual(spec["title"], "结构图")
        self.assertEqual(spec["nodes"][0]["label"], "")

    def test_no_terms_leaves_labels(self):
        spec = {"nodes": [{"id": "a", "label": ""}]}
        filled_spec, filled = context.fill_spec(spec, [], "")
        self.assertEqual(filled_spec["nodes"][0].get("label"), "")
        self.assertEqual(filled, [])


if __name__ == "__main__":
    unittest.main()
