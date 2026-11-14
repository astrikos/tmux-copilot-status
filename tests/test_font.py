import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("font_setup", ROOT / "font.py")
font = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(font)


class FontSetup(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.config = self.home / "alacritty.toml"
        self.env = patch.dict(os.environ, {
            "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.platform = patch.object(font.sys, "platform", "darwin")
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.ensure = patch.object(font, "ensure_font")
        self.ensure.start()
        self.addCleanup(self.ensure.stop)

    def test_exact_restore_and_repeat_install_preserve_original(self):
        original = b'# Original\r\n[font.normal]\r\nfamily = "Menlo"\r\n'
        self.config.write_bytes(original)
        backup, helper = font.install(self.config)
        configured = self.config.read_bytes()
        font.install(self.config)
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(self.config.read_bytes(), configured)
        self.assertIn("MesloLGS Nerd Font Mono", configured.decode())
        self.assertIn(str(backup), configured.decode())
        self.assertTrue(helper.exists())
        self.assertTrue(font.restore(self.config))
        self.assertEqual(self.config.read_bytes(), original)
        self.assertFalse(font.restore(self.config))
        font.install(self.config)
        self.assertEqual(backup.read_bytes(), original)

    def test_later_edits_are_protected_unless_force_is_explicit(self):
        original = b"# original\n"
        self.config.write_bytes(original)
        font.install(self.config)
        edited = self.config.read_bytes() + b"# later change\n"
        self.config.write_bytes(edited)
        with self.assertRaisesRegex(ValueError, "changed"):
            font.restore(self.config)
        self.assertEqual(self.config.read_bytes(), edited)
        with self.assertRaisesRegex(ValueError, "changed"):
            font.install(self.config)
        font.restore(self.config, force=True)
        self.assertEqual(self.config.read_bytes(), original)

    def test_updated_wrapper_keeps_exact_restore_working(self):
        original = b"# original\n"
        self.config.write_bytes(original)
        with patch.object(font, "wrapper", return_value=b"# previous font setup\n"):
            backup, _ = font.install(self.config)
        font.install(self.config)
        self.assertEqual(backup.read_bytes(), original)
        self.assertTrue(font.restore(self.config))
        self.assertEqual(self.config.read_bytes(), original)

    def test_failed_font_install_leaves_live_config_untouched(self):
        original = b"# original\n"
        self.config.write_bytes(original)
        with patch.object(font, "ensure_font", side_effect=ValueError("brew failed")):
            with self.assertRaisesRegex(ValueError, "brew failed"):
                font.install(self.config)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(font.paths(self.config)[1].read_bytes(), original)
        font.install(self.config)
        self.assertTrue(font.restore(self.config))

    def test_missing_original_config_is_removed_on_restore(self):
        font.install(self.config)
        self.assertTrue(self.config.exists())
        font.restore(self.config)
        self.assertFalse(self.config.exists())

    def test_corrupted_backup_is_never_restored(self):
        self.config.write_text("# original\n")
        backup, _ = font.install(self.config)
        backup.write_text("# changed backup\n")
        configured = self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, "backup"):
            font.restore(self.config, force=True)
        self.assertEqual(self.config.read_bytes(), configured)

    def test_untracked_backup_and_symlink_are_not_overwritten(self):
        backup = font.paths(self.config)[1]
        backup.write_text("# keep me\n")
        with self.assertRaisesRegex(ValueError, "backup already exists"):
            font.install(self.config)
        self.assertEqual(backup.read_text(), "# keep me\n")
        target = self.home / "real.toml"
        target.touch()
        self.config.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "Symlinked"):
            font.install(self.config)


if __name__ == "__main__":
    unittest.main()
