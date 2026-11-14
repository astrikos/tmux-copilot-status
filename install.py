#!/usr/bin/env python3
"""Install the status bar and user-level Copilot hooks without extra packages."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
EVENTS = (
    "sessionStart", "userPromptSubmitted", "preToolUse", "postToolUse",
    "postToolUseFailure", "notification", "agentStop", "sessionEnd",
)
START = "# BEGIN tmux-copilot-status"
END = "# END tmux-copilot-status"


def tmux_quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


def backup(path):
    destination = path.with_name(path.name + ".copilot-status.bak")
    if path.exists() and not destination.exists():
        shutil.copyfile(path, destination)


def write_changed(path, content):
    if path.exists() and path.read_text() == content:
        return
    backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def default_tmux_conf(home, config_home):
    legacy = home / ".tmux.conf"
    xdg = config_home / "tmux/tmux.conf"
    return legacy if legacy.exists() or not xdg.exists() else xdg


def add_include(content, status_conf):
    source = "source-file " + tmux_quote(str(status_conf))
    block = f"{START}\n{source}\n{END}"
    if START in content:
        pattern = re.compile(re.escape(START) + r"\n.*?\n" + re.escape(END), re.S)
        if len(pattern.findall(content)) != 1:
            raise ValueError("Malformed or duplicate tmux-copilot-status block")
        return pattern.sub(lambda _: block, content)
    for line in content.splitlines():
        try:
            fields = shlex.split(line, comments=True)
        except ValueError:
            continue
        if (
            len(fields) == 2 and fields[0] == "source-file"
            and Path(os.path.expandvars(fields[1])).expanduser() == status_conf
        ):
            return content
    return content.rstrip("\n") + ("\n\n" if content else "") + block + "\n"


def install(tmux_conf=None):
    if sys.version_info < (3, 9):
        raise ValueError("Python 3.9 or newer is required")
    if sys.platform not in ("darwin", "linux"):
        raise ValueError("Only macOS and Linux are supported")
    if not shutil.which("tmux") or not shutil.which("ps"):
        raise ValueError("tmux and ps must be on PATH")
    version = subprocess.check_output(["tmux", "-V"], text=True).strip()
    match = re.search(r"(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (3, 3):
        raise ValueError("tmux 3.3 or newer is required")

    home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")).expanduser().absolute()
    copilot_home = Path(os.environ.get("COPILOT_HOME", home / ".copilot")).expanduser().absolute()
    destination = config_home / "tmux/copilot-status"
    config = Path(tmux_conf).expanduser().absolute() if tmux_conf else default_tmux_conf(home, config_home)
    status_conf = destination / "status.conf"
    existing = config.read_text() if config.exists() else ""
    updated = add_include(existing, status_conf)
    python = shlex.quote(sys.executable)
    script = shlex.quote(str(destination / "status.py"))
    command = f"{python} {script}"
    settings = "source-file " + tmux_quote(str(destination / "theme.conf")) + "\n"
    for row in (0, 1):
        # Literal hashes in paths must survive tmux's format expansion.
        job = command.replace("#", "##") + f" render {row} #{{client_width}} #{{window_id}}"
        settings += f"set -g 'status-format[{row}]' " + tmux_quote(f"#({job})") + "\n"

    hooks = {}
    for event in EVENTS:
        entry = {
            "type": "command",
            "bash": f"{command} hook {event} >/dev/null 2>&1 || true",
            "timeoutSec": 5,
        }
        if event == "notification":
            entry["matcher"] = "permission_prompt|elicitation_dialog"
        hooks[event] = [entry]
    hook_path = copilot_home / "hooks/tmux-status.json"
    write_changed(destination / "status.py", (ROOT / "status.py").read_text())
    write_changed(destination / "theme.conf", (ROOT / "theme.conf").read_text())
    write_changed(destination / "font.py", (ROOT / "font.py").read_text())
    write_changed(status_conf, settings)
    write_changed(hook_path, json.dumps({"version": 1, "hooks": hooks}, indent=2) + "\n")
    write_changed(config, updated)
    return config, status_conf, hook_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tmux-conf", help="tmux configuration file to update")
    args = parser.parse_args()
    try:
        config, status_conf, hooks = install(args.tmux_conf)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Installation failed: {error}\n")
    print(f"Installed status bar: {status_conf}")
    print(f"Installed Copilot hooks: {hooks}")
    print(f"Updated tmux config: {config}")
    print("Reload your tmux config:")
    print("  tmux source-file " + shlex.quote(str(config)))
    print("Restart existing Copilot sessions to load the hooks.")


if __name__ == "__main__":
    main()
