#!/usr/bin/env python3
"""magisk-Next 工具箱单元测试。

运行：python3 -m unittest discover -s tests -v
或：  python3 tests/test_next_tools.py
"""
from __future__ import annotations

import py_compile
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "next"))

import health_report  # noqa: E402
import integrity  # noqa: E402
import module_lint  # noqa: E402
import next_common as common  # noqa: E402
import preflight  # noqa: E402


class TestCommon(unittest.TestCase):
    def test_parse_props(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.prop"
            p.write_text("# c\n!also\nversion = 1.0 \nbad key=x\nnoequals\n",
                         encoding="utf-8")
            d = common.parse_props(p)
            self.assertEqual(d["version"], "1.0")
            self.assertNotIn("bad key", d)
            self.assertNotIn("noequals", d)

    def test_next_config_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            r = Path(td)
            (r / "config.prop").write_text(
                "version=1\nnext.channel=https://example.com/u.json\n"
                "next.moduleSnapshot=1\n", encoding="utf-8")
            # 直接验证前缀剥离逻辑
            props = common.parse_props(r / "config.prop")
            cfg = {k[5:]: v for k, v in props.items() if k.startswith("next.")}
            self.assertEqual(cfg["channel"], "https://example.com/u.json")
            self.assertEqual(cfg["moduleSnapshot"], "1")

    def test_regexes(self):
        self.assertTrue(common.MODULE_ID_RE.match("com.example.demo"))
        self.assertFalse(common.MODULE_ID_RE.match("../evil"))
        self.assertTrue(common.MIN_MAGISK_RE.match("31100"))
        self.assertTrue(common.MIN_MAGISK_RE.match("v31.1"))
        self.assertFalse(common.MIN_MAGISK_RE.match("latest"))

    def test_sha256_and_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a"
            p.write_bytes(b"abc")
            self.assertEqual(
                common.sha256_file(p),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(common.exit_code([{"status": common.PASS}]), 0)
        self.assertEqual(common.exit_code([{"status": common.FAIL}]), 1)
        self.assertEqual(common.exit_code([{"status": common.WARN}], True), 2)


class TestSelfTests(unittest.TestCase):
    def test_all_self_tests_pass(self):
        self.assertEqual(preflight.self_test(), 0)
        self.assertEqual(module_lint.self_test(), 0)
        self.assertEqual(integrity.self_test(), 0)
        self.assertEqual(health_report.self_test(), 0)


class TestPreflight(unittest.TestCase):
    def test_checks_shape(self):
        checks = preflight.run_checks(ROOT)
        self.assertGreaterEqual(len(checks), 8)
        for c in checks:
            self.assertIn(c["status"], (common.PASS, common.WARN, common.FAIL))
            self.assertIn("name", c)
            self.assertIn("detail", c)
        self.assertIn("git submodules", [c["name"] for c in checks])


class TestModuleLint(unittest.TestCase):
    def test_valid_module(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "META-INF/com/google/android").mkdir(parents=True)
            (d / "module.prop").write_text(
                "id=com.example.ok\nname=OK\nversion=v1\nversionCode=1\n"
                "author=next\ndescription=ok\nminMagisk=31100\n",
                encoding="utf-8")
            (d / module_lint.UPDATE_BINARY).write_text("#!/system/bin/sh\n",
                                                       encoding="utf-8")
            (d / "system").mkdir()
            (d / "system" / "f").write_text("x", encoding="utf-8")
            self.assertFalse([i for i in module_lint.lint_module(d)
                              if i["level"] == common.FAIL])


class TestIntegrity(unittest.TestCase):
    def test_generate_verify_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.apk").write_bytes(b"aaa")
            (d / "b.zip").write_bytes(b"bbb")
            meta = integrity.generate(d)
            self.assertEqual(meta["file_count"], 2)
            self.assertFalse(integrity.verify(d))
            (d / "a.apk").write_bytes(b"evil")
            self.assertIn("HASH_MISMATCH",
                          {i["code"] for i in integrity.verify(d)})


class TestHealthReport(unittest.TestCase):
    def test_demo_render(self):
        d = health_report.demo_data()
        self.assertFalse(health_report.validate(d))
        md = health_report.render_report(d)
        self.assertIn("| 检查项 |", md)
        self.assertIn("magisk.active", md)
        self.assertIn("结论", md)


class TestRepoLayout(unittest.TestCase):
    def test_required_files(self):
        for rel in ("build.py", "app/settings.gradle.kts", ".gitmodules",
                    "config.prop.sample", "docs/build.md"):
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_python_files_compile(self):
        files = sorted((ROOT / "next").glob("*.py")) + \
            sorted((ROOT / "tests").glob("*.py"))
        self.assertGreaterEqual(len(files), 6)
        for f in files:
            with self.subTest(f=f.name):
                py_compile.compile(str(f), doraise=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
