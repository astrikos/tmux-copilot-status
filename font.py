#!/usr/bin/env python3
"""Opt-in Alacritty Nerd Font setup, with exact configuration rollback."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


CASK = "font-meslo-lg-nerd-font"
FAMILY = "MesloLGS Nerd Font Mono"
FONT_FILE = "MesloLGSNerdFontMono-Regular.ttf"


def default_config():
    home = Path.home()
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    candidates = (
        xdg / "alacritty/alacritty.toml", xdg / "alacritty.toml",
        home / ".config/alacritty/alacritty.toml", home / ".alacritty.toml",
    )
    return next((path for path in candidates if path.exists()), candidates[0])


def paths(config):
    config = Path(config).expanduser().absolute()
    if config.is_symlink():
        raise ValueError("Symlinked configs need manual font setup; no changes made")
    backup = config.with_name(config.stem + ".copilot-font-backup.toml")
    state = config.with_name(config.stem + ".copilot-font-state.json")
    return config, backup, state


def digest(content):
    return hashlib.sha256(content).hexdigest()


def snapshot(path):
    return path.exists(), digest(path.read_bytes() if path.exists() else b"")


def wrapper(backup):
    text = (
        "# Managed by tmux-copilot-status/font.py; restore instead of deleting the backup.\n"
        "[general]\nimport = [" + json.dumps(str(backup)) + "]\n"
    )
    for face, style in (
        ("normal", "Regular"), ("bold", "Bold"),
        ("italic", "Italic"), ("bold_italic", "Bold Italic"),
    ):
        text += f"\n[font.{face}]\nfamily = " + json.dumps(FAMILY) + "\n"
        text += "style = " + json.dumps(style) + "\n"
    return text.encode("utf-8")


def load_state(backup, state_path):
    state = json.loads(state_path.read_text())
    if state.get("version") != 1 or digest(backup.read_bytes()) != state["original_sha256"]:
        raise ValueError("Font backup is missing, changed, or has an unsupported version")
    return state


def ensure_font():
    if sys.platform != "darwin":
        raise ValueError("Automatic font installation supports macOS only")
    font = Path.home() / "Library/Fonts" / FONT_FILE
    if font.is_file():
        return
    brew = shutil.which("brew")
    if not brew:
        raise ValueError("Homebrew is required; the Alacritty config was not changed")
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1")
    present = subprocess.run(
        [brew, "list", "--cask", CASK], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if present.returncode == 0:
        raise ValueError("Font cask is installed but its regular font file is missing")
    subprocess.run([brew, "install", "--cask", CASK], env=env, check=True)
    if not font.is_file():
        raise ValueError("Installed cask did not create the expected font file")


def install(config):
    if sys.platform != "darwin":
        raise ValueError("Automatic font installation supports macOS only")
    config, backup, state_path = paths(config)
    installed = wrapper(backup)
    if state_path.exists():
        state = load_state(backup, state_path)
        current = snapshot(config)
        if current not in (
            (state["original_existed"], state["original_sha256"]),
            (True, state["installed_sha256"]),
        ):
            raise ValueError("Config changed since the saved backup; refusing to overwrite it")
    else:
        if backup.exists():
            raise ValueError("A backup already exists without its state file; refusing to replace it")
        original = config.read_bytes() if config.exists() else b""
        state = {
            "version": 1,
            "original_existed": config.exists(),
            "original_sha256": digest(original),
            "original_mode": config.stat().st_mode & 0o777 if config.exists() else 0o600,
            "installed_sha256": digest(installed),
            "font_was_present": (Path.home() / "Library/Fonts" / FONT_FILE).is_file(),
            "cask": CASK,
        }
        config.parent.mkdir(parents=True, exist_ok=True)
        with backup.open("xb") as handle:
            handle.write(original)
        backup.chmod(0o600)
        with state_path.open("x") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
        state_path.chmod(0o600)
    # Do not change the live config until the font is successfully installed.
    ensure_font()
    home = Path.home()
    root = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    helper = root / "tmux/copilot-status/font.py"
    helper.parent.mkdir(parents=True, exist_ok=True)
    if helper.absolute() != Path(__file__).absolute():
        helper.write_bytes(Path(__file__).read_bytes())
    config.write_bytes(installed)
    config.chmod(state["original_mode"])
    if state["installed_sha256"] != digest(installed):
        state["installed_sha256"] = digest(installed)
        state_path.write_text(json.dumps(state, indent=2) + "\n")
    return backup, helper


def restore(config, force=False):
    config, backup, state_path = paths(config)
    state = load_state(backup, state_path)
    current = snapshot(config)
    if current == (state["original_existed"], state["original_sha256"]):
        return False
    if current != (True, state["installed_sha256"]) and not force:
        raise ValueError(
            "Config changed after font setup. Save those edits, then use restore --force "
            "to replace it with the original backup"
        )
    if state["original_existed"]:
        config.write_bytes(backup.read_bytes())
        config.chmod(state["original_mode"])
    elif config.exists():
        config.unlink()
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "restore"))
    parser.add_argument("--config", type=Path, help="Alacritty TOML configuration")
    parser.add_argument("--force", action="store_true", help="Discard later config edits on restore")
    args = parser.parse_args()
    if args.force and args.action != "restore":
        parser.error("--force is only supported with restore")
    config = args.config or default_config()
    try:
        if args.action == "install":
            backup, helper = install(config)
            print(f"Configured {FAMILY} in {config}")
            print(f"Exact original configuration: {backup}")
            print("Undo: " + shlex.join([sys.executable, str(helper), "restore", "--config", str(config)]))
            print("If Alacritty reports a font fallback, detach from tmux and fully quit/reopen Alacritty.")
        else:
            changed = restore(config, args.force)
            print("Original configuration restored." if changed else "Configuration is already restored.")
            print("The font remains installed but is no longer selected by this setup.")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Font setup failed: {error}\n")


if __name__ == "__main__":
    main()
