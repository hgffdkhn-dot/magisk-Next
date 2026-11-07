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

import api_audit  # noqa: E402
import channel  # noqa: E402
import health_report  # noqa: E402
import integrity  # noqa: E402
import module_lint  # noqa: E402
import native_audit  # noqa: E402
import next_common as common  # noqa: E402
import preflight  # noqa: E402
import snapshot  # noqa: E402
import verify_repo  # noqa: E402


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
        for mod in (preflight, module_lint, integrity, health_report,
                    snapshot, channel, api_audit, verify_repo):
            with self.subTest(mod=mod.__name__):
                self.assertEqual(mod.self_test(), 0)


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

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "m"
            d.mkdir()
            (d / "module.prop").write_text(
                "id=m\nname=M\nversion=v1\nversionCode=1\nauthor=a\ndescription=d\n",
                encoding="utf-8")
            (d / "leak").symlink_to(Path(td) / "outside")
            codes = {i["code"] for i in module_lint.lint_module(d)}
            self.assertIn("SYMLINK_ESCAPE", codes)


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

    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a").write_bytes(b"aaa")
            (d / "link").symlink_to("a")
            self.assertNotIn("link", integrity.collect(d))
            integrity.generate(d)
            self.assertIn("SYMLINK_SKIPPED",
                          {i["code"] for i in integrity.verify(d)})


class TestHealthReport(unittest.TestCase):
    def test_demo_render(self):
        d = health_report.demo_data()
        self.assertFalse(health_report.validate(d))
        self.assertEqual(len(d["checks"]), 8)
        md = health_report.render_report(d)
        self.assertIn("| 检查项 |", md)
        self.assertIn("magisk.active", md)
        self.assertIn("结论", md)

    def test_output_creates_parent(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "nested" / "dir" / "report.md"
            import subprocess
            r = subprocess.run(
                [sys.executable, str(ROOT / "next" / "health_report.py"),
                 "--demo", "--output", str(out)],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.is_file())


class TestSnapshot(unittest.TestCase):
    def test_capture_diff_restore(self):
        with tempfile.TemporaryDirectory() as td:
            root, mods = Path(td) / "repo", Path(td) / "modules"
            (mods / "demo").mkdir(parents=True)
            (mods / "demo" / "module.prop").write_text("id=demo\n", encoding="utf-8")
            m = snapshot.capture(root, mods, name="ut")
            self.assertEqual(m["file_count"], 1)
            self.assertFalse(snapshot.verify(root, m["id"]))
            self.assertFalse(snapshot.restore(root, m["id"], mods)["applied"])
            (mods / "demo" / "module.prop").write_text("HACKED\n", encoding="utf-8")
            self.assertIn("demo/module.prop",
                          snapshot.diff(root, m["id"], mods)["changed"])
            plan = snapshot.restore(root, m["id"], mods, force=True)
            self.assertTrue(plan["applied"])
            self.assertEqual((mods / "demo" / "module.prop").read_text(),
                             "id=demo\n")

    def test_tampered_snapshot_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root, mods = Path(td) / "repo", Path(td) / "modules"
            mods.mkdir()
            (mods / "f").write_text("x", encoding="utf-8")
            m = snapshot.capture(root, mods)
            (snapshot.snap_root(root) / m["id"] / "files" / "f").write_text(
                "BAD", encoding="utf-8")
            with self.assertRaises(ValueError):
                snapshot.restore(root, m["id"], mods, force=True)


class TestChannel(unittest.TestCase):
    def test_validate_rejects_insecure(self):
        d = channel.template()
        self.assertFalse([i for i in channel.validate(d)
                          if i["level"] == common.FAIL])
        bad = dict(d, channel="http://x/y.json", versionCode="abc")
        codes = {i["code"] for i in channel.validate(bad)}
        self.assertIn("INSECURE_CHANNEL", codes)
        self.assertIn("BAD_VERSION_CODE", codes)

    def test_artifact_hash(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            apk = d / "app-release.apk"
            apk.write_bytes(b"apk")
            manifest = dict(channel.template(), artifacts=[{
                "name": "app-release.apk", "url": "https://e/apk",
                "sha256": common.sha256_file(apk), "size": apk.stat().st_size}])
            self.assertFalse(channel.verify_artifacts(manifest, d))
            apk.write_bytes(b"bad")
            self.assertIn("ARTIFACT_HASH_MISMATCH",
                          {i["code"] for i in channel.verify_artifacts(manifest, d)})


class TestApiAudit(unittest.TestCase):
    def test_all_refs_defined(self):
        self.assertFalse(api_audit.audit(ROOT))

    def test_extract_refs_catches_fake(self):
        refs = api_audit.extract_refs("val a = Config.noSuchField\n")
        self.assertIn("noSuchField", refs["Config"])
        self.assertNotIn("noSuchField", api_audit.definitions(ROOT)["Config"])


class TestNativeAudit(unittest.TestCase):
    def test_real_repo_passes(self):
        self.assertFalse(native_audit.audit(ROOT))

    def test_checks_shape(self):
        cs = native_audit.checks(ROOT)
        self.assertEqual(len(cs), 12)
        self.assertTrue(all(c["status"] == common.PASS for c in cs))
        s = native_audit.summary(ROOT)
        self.assertEqual(s["rules"], 12)
        self.assertGreaterEqual(s["assertions"], 50)
        self.assertEqual(s["failed_rules"], 0)

    def test_removed_snippet_is_caught(self):
        rule = next(r for r in native_audit.RULES if r["id"] == "N01")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dst = root / rule["file"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text((ROOT / rule["file"]).read_text(encoding="utf-8")
                           .replace("const MAX_POOL_SIZE: i32 = 16;", ""),
                           encoding="utf-8")
            # 其它规则的文件缺失也会报错，但 N01 必须因断言失败被点名
            self.assertIn("N01", {i["code"] for i in native_audit.audit(root)})

    def test_forbidden_antipattern_is_caught(self):
        rule = next(r for r in native_audit.RULES if r["id"] == "N02")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dst = root / rule["file"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text((ROOT / rule["file"]).read_text(encoding="utf-8")
                           + "\nerrno = pthread_create(&thread, &attr, entry, arg);\n",
                           encoding="utf-8")
            self.assertIn("N02", {i["code"] for i in native_audit.audit(root)})


class TestRepoLayout(unittest.TestCase):
    def test_required_files(self):
        for rel in ("build.py", "app/settings.gradle.kts", ".gitmodules",
                    "config.prop.sample", "docs/build.md"):
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_python_files_compile(self):
        files = sorted((ROOT / "next").glob("*.py")) + \
            sorted((ROOT / "tests").glob("*.py"))
        self.assertGreaterEqual(len(files), 9)
        for f in files:
            with self.subTest(f=f.name):
                py_compile.compile(str(f), doraise=True)

    def test_repo_checks_all_pass(self):
        checks = verify_repo.run_all(ROOT)
        self.assertTrue(all(c["status"] == common.PASS for c in checks), checks)


if __name__ == "__main__":
    unittest.main(verbosity=2)
