"""Tests for the atlas home, config loading and the init/--version commands."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from atlaslib import __version__  # noqa: E402
from atlaslib.cli import main  # noqa: E402
from atlaslib.core import HOME_ENV, SOURCE_DIR, ConfigError, default_home, load_config  # noqa: E402

MINIMAL = """
[sources]
claude_projects = "~/.claude/projects"
[sources.copilot]
chat_storage = "work/copilot_import/workspaceStorage"
[project]
name = "demo"
work_dir = "work/demo"
knowledge_dir = "projects/demo/knowledge"
roots = ["~/research/demo"]
cwd_also = []
exclude_cwd = []
exclude_ids = []
[paths]
roots = ["~/research", "/mnt/data"]
verify_timeout_s = 1
max_session_ids = 5
[limits]
user_text = 1
agent_final = 1
agent_commentary = 1
tool_input = 1
subagent_result = 1
[knowledge]
abbreviations = { D = "~/research/demo" }
"""


class ConfigCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.fake_home = self.tmp / "userhome"
        env = {k: v for k, v in os.environ.items() if k != HOME_ENV}
        env["HOME"] = str(self.fake_home)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()


class DefaultHomeTests(ConfigCase):
    def test_env_var_wins(self):
        os.environ[HOME_ENV] = str(self.tmp / "atlas")
        self.assertEqual(default_home(), self.tmp / "atlas")

    def test_source_checkout_is_home_when_env_unset(self):
        self.assertEqual(default_home(), SOURCE_DIR)

    def test_installed_package_falls_back_to_dot_dir(self):
        with mock.patch("atlaslib.core.SOURCE_DIR", self.tmp / "site-packages"):
            self.assertEqual(default_home(), self.fake_home / ".researchatlas")


class LoadConfigTests(ConfigCase):
    def write(self, text=MINIMAL):
        path = self.tmp / "atlas" / "config.toml"
        path.parent.mkdir(parents=True)
        path.write_text(text)
        return path

    def test_relative_paths_resolve_against_config_folder(self):
        path = self.write()
        cfg = load_config(path)
        home = path.parent
        self.assertEqual(cfg["home"], home)
        self.assertEqual(cfg["project"]["work_dir"], home / "work/demo")
        self.assertEqual(cfg["project"]["knowledge_dir"], home / "projects/demo/knowledge")
        self.assertEqual(cfg["project"]["review_ledger"], home / "projects/demo/reviewed_sessions.jsonl")
        self.assertEqual(cfg["sources"]["copilot"]["chat_storage"], str(home / "work/copilot_import/workspaceStorage"))

    def test_tilde_is_expanded(self):
        cfg = load_config(self.write())
        research = str(self.fake_home / "research")
        self.assertEqual(cfg["sources"]["claude_projects"], str(self.fake_home / ".claude/projects"))
        self.assertEqual(cfg["project"]["roots"], [research + "/demo"])
        self.assertEqual(cfg["paths"]["roots"], [research, "/mnt/data"])
        self.assertEqual(cfg["knowledge"]["abbreviations"], {"D": research + "/demo"})

    def test_missing_file_raises_config_error(self):
        with self.assertRaisesRegex(ConfigError, "researchatlas init"):
            load_config(self.tmp / "nope.toml")

    def test_missing_section_raises_config_error(self):
        with self.assertRaisesRegex(ConfigError, r"missing \[paths\]"):
            load_config(self.write(MINIMAL.replace("[paths]", "[other]")))

    def test_cli_reports_missing_config_without_traceback(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["--config", str(self.tmp / "nope.toml"), "find", "x"])
        self.assertEqual(code, 2)
        self.assertIn("no config file", err.getvalue())


class InitAndVersionTests(ConfigCase):
    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(argv)
        return code, out.getvalue()

    def test_init_writes_loadable_template(self):
        home = self.tmp / "atlas"
        code, out = self.run_main(["init", "--home", str(home)])
        self.assertEqual(code, 0)
        self.assertIn(HOME_ENV, out)
        cfg = load_config(home / "config.toml")
        self.assertEqual(cfg["project"]["work_dir"], home / "work/demo_project")
        self.assertTrue(cfg["sources"]["codex_sessions"].startswith(str(self.fake_home)))

    def test_init_uses_env_home_and_never_overwrites(self):
        home = self.tmp / "atlas"
        os.environ[HOME_ENV] = str(home)
        self.run_main(["init"])
        (home / "config.toml").write_text("# edited")
        code, out = self.run_main(["init"])
        self.assertEqual(code, 0)
        self.assertIn("already exists", out)
        self.assertEqual((home / "config.toml").read_text(), "# edited")

    def test_version_flag(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"researchatlas {__version__}")


if __name__ == "__main__":
    unittest.main()
