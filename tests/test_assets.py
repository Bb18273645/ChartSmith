# Copyright (c) 2026 Bb18273645. 保留所有权利。
# 非商业用途免费；商业用途需作者书面同意；二改须注明上游并开源，详见 LICENSE。
"""插件资产校验：metadata / 配置 schema / 工具 docstring。

这些文件 AstrBot 都直接解析，写错不会报错、只会「静默失效」，
所以放在测试里逐条钉住。缺 PyYAML / docstring_parser 时（AstrBot 自带这两个依赖）
对应用例自动跳过。
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    from docstring_parser import parse as parse_docstring
except ImportError:  # pragma: no cover
    parse_docstring = None


def module_defaults() -> dict:
    """从 main.py 里静态取出 DEFAULTS 字典，避免 import 整个 AstrBot。"""
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DEFAULTS":
                    return ast.literal_eval(node.value)
    raise AssertionError("main.py 里没有找到 DEFAULTS")


def load_pure_function(name: str):
    """把 main.py 里的纯函数单独编译出来执行，绕开 astrbot 依赖。"""
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            namespace: dict = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<main>", "exec"), namespace)
            return namespace[name]
    raise AssertionError(f"main.py 里没有找到 {name}")


class StripCommandTest(unittest.TestCase):
    def setUp(self):
        self.strip = load_pure_function("_strip_command")

    def test_keeps_json_after_command(self):
        self.assertEqual(self.strip('/diagram {"title":"x"}'), '{"title":"x"}')
        self.assertEqual(self.strip('/图匠 {"nodes":[]}'), '{"nodes":[]}')

    def test_bare_command_returns_empty(self):
        self.assertEqual(self.strip("/diagram"), "")
        self.assertEqual(self.strip(""), "")

    def test_bare_json_is_untouched(self):
        self.assertEqual(self.strip('{"nodes":[]}'), '{"nodes":[]}')

    def test_strips_code_fence(self):
        self.assertEqual(self.strip('/diagram ```json\n{"nodes":[]}\n```'), '{"nodes":[]}')


class ConfigSchemaTest(unittest.TestCase):
    def test_schema_is_valid_json(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertIsInstance(schema, dict)
        for key, entry in schema.items():
            self.assertIn("type", entry, key)
            self.assertIn("description", entry, key)
            self.assertIn("default", entry, key)

    def test_schema_matches_code_defaults(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema), set(module_defaults()))
        for key, value in module_defaults().items():
            self.assertEqual(schema[key]["default"], value, key)

    def test_schema_types_are_supported(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        allowed = {"int", "float", "string", "bool", "list", "dict", "text", "file"}
        for key, entry in schema.items():
            self.assertIn(entry["type"], allowed, key)


@unittest.skipIf(yaml is None, "需要 PyYAML")
class MetadataTest(unittest.TestCase):
    def setUp(self):
        self.meta = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))

    def test_required_fields(self):
        for field in ("name", "display_name", "desc", "version", "author"):
            self.assertTrue(str(self.meta.get(field) or "").strip(), field)

    def test_name_is_python_identifier(self):
        self.assertTrue(self.meta["name"].isidentifier())

    def test_version_is_quoted_string(self):
        self.assertIsInstance(self.meta["version"], str)

    def test_astrbot_version_range(self):
        self.assertIn("4.", self.meta["astrbot_version"])


@unittest.skipIf(parse_docstring is None, "需要 docstring_parser（AstrBot 自带依赖）")
class ToolDocstringTest(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        funcs = {
            node.name: node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
        }
        self.funcs = funcs
        self.doc = parse_docstring(ast.get_docstring(funcs["render_diagram"]) or "")

    def test_has_description(self):
        self.assertTrue(self.doc.description.strip())

    def test_declares_single_string_param(self):
        self.assertEqual([p.arg_name for p in self.doc.params], ["spec"])
        self.assertEqual(self.doc.params[0].type_name, "string")
        self.assertTrue(self.doc.params[0].description.strip())

    def test_spec_mentions_tone_and_style(self):
        text = self.doc.params[0].description
        for word in ("tone", "neutral", "dashed", "不要提供坐标"):
            self.assertIn(word, text)

    def test_command_handlers_take_only_event(self):
        for name in ("diagram_cmd", "tujiang_cmd"):
            args = [a.arg for a in self.funcs[name].args.args]
            self.assertEqual(args, ["self", "event"], name)


if __name__ == "__main__":
    unittest.main()
