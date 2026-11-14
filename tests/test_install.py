import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installer", ROOT / "install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class Installation(unittest.TestCase):
    def test_install_is_idempotent_preserves_config_and_uses_local_paths(self):
        with tempfile.TemporaryDirectory(prefix="tmux-copilot-install-") as directory:
            home = Path(directory) / "home with spaces and 'quotes'"
            home.mkdir()
            config = home / ".tmux.conf"
            original = "set -g prefix C-a\n"
            config.write_text(original)
            copilot = home / "my copilot"
            (copilot / "hooks").mkdir(parents=True)
            unrelated = copilot / "hooks/other.json"
            unrelated.write_text('{"version":1,"hooks":{}}\n')
            env = dict(
                os.environ, HOME=str(home), COPILOT_HOME=str(copilot),
                XDG_CONFIG_HOME=str(home / "my config"),
            )
            command = [sys.executable, "-B", str(ROOT / "install.py")]
            for _ in range(2):
                subprocess.run(command, env=env, text=True, capture_output=True, check=True)
            content = config.read_text()
            self.assertEqual(content.count(installer.START), 1)
            self.assertTrue(content.startswith(original))
            self.assertEqual(
                config.with_name(".tmux.conf.copilot-status.bak").read_text(),
                original,
            )
            self.assertEqual(unrelated.read_text(), '{"version":1,"hooks":{}}\n')
            hooks = json.loads((copilot / "hooks/tmux-status.json").read_text())
            self.assertEqual(set(hooks["hooks"]), set(installer.EVENTS))
            self.assertEqual(
                hooks["hooks"]["notification"][0]["matcher"],
                "permission_prompt|elicitation_dialog",
            )
            entry = hooks["hooks"]["preToolUse"][0]
            result = subprocess.run(
                ["bash", "-c", entry["bash"]], input="invalid", env=env,
                text=True, capture_output=True,
            )
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

            socket = str(Path(directory) / "test.sock")
            try:
                subprocess.run(
                    ["tmux", "-S", socket, "-f", str(config), "new-session", "-d"],
                    env=env, text=True, capture_output=True, check=True,
                )
                result = subprocess.check_output(
                    ["tmux", "-S", socket, "show-options", "-gv", "status-format[1]"],
                    env=env, text=True,
                )
                self.assertIn(
                    shlex.quote(str(home / "my config/tmux/copilot-status/status.py")),
                    result,
                )
            finally:
                subprocess.run(["tmux", "-S", socket, "kill-server"], capture_output=True)

    def test_xdg_config_and_custom_tmux_conf_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config_home = home / "xdg"
            xdg_conf = config_home / "tmux/tmux.conf"
            xdg_conf.parent.mkdir(parents=True)
            xdg_conf.touch()
            self.assertEqual(installer.default_tmux_conf(home, config_home), xdg_conf)
            legacy = home / ".tmux.conf"
            legacy.touch()
            self.assertEqual(installer.default_tmux_conf(home, config_home), legacy)

    def test_explicit_config_path_does_not_create_legacy_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / "custom tmux.conf"
            original = "set -g mouse on\n"
            config.write_text(original)
            env = dict(
                os.environ, HOME=str(home), COPILOT_HOME=str(home / ".copilot"),
                XDG_CONFIG_HOME=str(home / ".config"),
            )
            subprocess.run(
                [sys.executable, "-B", str(ROOT / "install.py"), "--tmux-conf", str(config)],
                env=env, text=True, capture_output=True, check=True,
            )
            self.assertTrue(config.read_text().startswith(original))
            self.assertIn(installer.START, config.read_text())
            self.assertFalse((home / ".tmux.conf").exists())

    def test_existing_unmanaged_include_is_not_duplicated(self):
        destination = Path.home() / ".config/tmux/copilot-status/status.conf"
        content = "source-file ~/.config/tmux/copilot-status/status.conf\n"
        self.assertEqual(installer.add_include(content, destination), content)

    def test_managed_include_updates_without_duplicate_blocks(self):
        original = installer.add_include("", Path("/old/status.conf"))
        changed = installer.add_include(original, Path("/new/status.conf"))
        self.assertEqual(changed.count(installer.START), 1)
        self.assertNotIn("/old/", changed)
        self.assertIn("/new/", changed)
        with self.assertRaises(ValueError):
            installer.add_include(installer.START, Path("/new/status.conf"))


if __name__ == "__main__":
    unittest.main()
