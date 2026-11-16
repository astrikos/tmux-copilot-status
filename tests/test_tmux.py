import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("cc"), "End-to-end fixture requires a C compiler")
class TmuxIntegration(unittest.TestCase):
    def test_hooks_live_refresh_mouse_navigation_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="copilot-tmux-test-") as directory:
            directory = Path(directory)
            home = directory / "home with 'quotes' and spaces"
            home.mkdir()
            config = home / ".tmux.conf"
            config.write_text("set -g base-index 1\nset -g mouse on\n")
            env = dict(os.environ, HOME=str(home), TMUX="", TMUX_PANE="")
            env.pop("XDG_CONFIG_HOME", None)
            env.pop("COPILOT_HOME", None)
            subprocess.run(
                [sys.executable, "-B", str(ROOT / "install.py")],
                env=env, capture_output=True, text=True, check=True,
            )
            shell = directory / "copilot"
            # Keep a foreground copilot without starting AI or using credentials.
            subprocess.run(
                ["cc", "-x", "c", "-o", str(shell), "-"],
                input=(
                    "#include <stdio.h>\n#include <stdlib.h>\n"
                    "int main(void) { char *line = NULL; size_t size = 0;"
                    "while (getline(&line, &size, stdin) != -1) { system(line); }"
                    "free(line); return 0; }\n"
                ),
                text=True, capture_output=True, check=True,
            )
            socket = str(directory / "test.sock")
            client = None
            master = None

            def tmux(*args):
                result = subprocess.run(
                    ["tmux", "-u", "-S", socket, *args], env=env,
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                if result.returncode and args[:2] != ("show-options", "-pqv"):
                    self.fail(f"tmux {args}: {result.stderr}")
                return result.stdout.rstrip("\n")

            try:
                first = tmux(
                    "-f", str(config), "new-session", "-d", "-s", "alpha",
                    "-n", "main", "-x", "180", "-y", "24",
                    "-P", "-F", "#{pane_id}", str(shell),
                )
                second = tmux(
                    "split-window", "-t", first, "-P", "-F", "#{pane_id}", str(shell),
                )
                third = tmux(
                    "new-session", "-d", "-s", "beta",
                    "-P", "-F", "#{pane_id}", str(shell),
                )
                server_pid = tmux("display-message", "-p", "-t", first, "#{pid}")
                env["TMUX"] = f"{socket},{server_pid},0"
                hooks = json.loads((home / ".copilot/hooks/tmux-status.json").read_text())
                counter = int(time.time() * 1000) - 1000

                def event(pane, name, **extra):
                    nonlocal counter
                    counter += 1
                    payload = dict(sessionId="test-" + pane, timestamp=counter, **extra)
                    command = (
                        f"printf '%s' {shlex.quote(json.dumps(payload))} | "
                        + hooks["hooks"][name][0]["bash"]
                    )
                    tmux("send-keys", "-t", pane, "-l", command)
                    tmux("send-keys", "-t", pane, "Enter")
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline:
                        raw = tmux("show-options", "-pqv", "-t", pane, "@copilot_status")
                        record = json.loads(raw) if raw else {}
                        if record.get("timestamp") == counter:
                            return record
                        time.sleep(0.05)
                    self.fail("Hook failed: " + tmux("capture-pane", "-p", "-t", pane))

                def render(row=1, styled=False):
                    script = home / ".config/tmux/copilot-status/status.py"
                    window = tmux("display-message", "-p", "-t", first, "#{window_id}")
                    output = subprocess.check_output(
                        [sys.executable, str(script), "render", str(row), "180", window],
                        env=env, text=True,
                    )
                    if styled:
                        return output
                    return re.sub(r"#\[[^]]*\]", "", output).rstrip("\n")

                tmux("select-pane", "-t", first)
                event(first, "userPromptSubmitted")
                event(second, "preToolUse", toolCalls=[
                    {"id": "approval"}, {"id": "sibling"},
                ])
                event(second, "notification", notificationType="permission_prompt")
                self.assertEqual(
                    event(second, "postToolUse", toolCallId="sibling")["state"], "waiting",
                )
                event(third, "agentStop")
                bottom = render()
                self.assertNotIn("p0", bottom)
                self.assertNotIn("p1", bottom)
                self.assertIn("copilot", bottom)
                self.assertIn("#e5b567", render(styled=True))
                self.assertIn("#[fg=#9ece6a]\u25cf", render(0, styled=True))
                self.assertIn("beta /", render(0))

                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 180, 0, 0))
                client = subprocess.Popen(
                    ["tmux", "-u", "-S", socket, "attach-session", "-t", "alpha"],
                    stdin=slave, stdout=slave, stderr=slave,
                    env=dict(env, TMUX="", TERM="xterm-256color"),
                )
                os.close(slave)

                def wait_for(needle):
                    output = b""
                    deadline = time.monotonic() + 6
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], 0.1)[0]:
                            output += os.read(master, 65536)
                        elif needle in output:
                            return
                    self.fail(f"Status output missing {needle!r}")

                wait_for(b"\x1b[24;")
                def click_x(target, row=1):
                    prefix = render(row, styled=True).split(
                        f"#[range=user|{target},", 1,
                    )[0]
                    return len(re.sub(r"#\[[^]]*\]", "", prefix)) + 3

                x = click_x(second)
                os.write(master, f"\033[<0;{x};24M\033[<0;{x};24m".encode())
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if tmux("display-message", "-p", "-t", "alpha:", "#{pane_id}") == second:
                        break
                    time.sleep(0.05)
                self.assertEqual(
                    tmux("display-message", "-p", "-t", "alpha:", "#{pane_id}"), second,
                    tmux("show-messages") + "\n"
                    + tmux("list-keys", "-T", "root", "MouseDown1Status"),
                )
                selected_style = render(styled=True).split(
                    f"#[range=user|{second},", 1,
                )[1].split("#[norange,default]", 1)[0]
                self.assertIn("bg=#414454", selected_style)
                self.assertIn("#[bold]#[fg=#ffffff]", selected_style)
                self.assertIn("#[fg=#858795]\u25cf", selected_style)
                # Exercise a separate click, not tmux's double-click event.
                time.sleep(0.6)
                x = click_x(third, row=0)
                os.write(master, f"\033[<0;{x};23M\033[<0;{x};23m".encode())
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if tmux("list-clients", "-F", "#{session_name}") == "beta":
                        break
                    time.sleep(0.05)
                self.assertEqual(
                    tmux("list-clients", "-F", "#{session_name}"), "beta",
                    "\n".join(line for line in tmux("show-messages").splitlines()
                              if "key " in line or "message:" in line),
                )

                self.assertEqual(
                    event(second, "postToolUse", toolCallId="approval")["state"], "working",
                )
                self.assertNotIn("#e5b567", render(styled=True))
                self.assertEqual(event(first, "sessionEnd")["state"], "ended")
                tmux(
                    "switch-client", "-c",
                    tmux("list-clients", "-F", "#{client_name}"), "-t", "alpha",
                )
                tmux("kill-pane", "-t", third)
                self.assertNotIn("beta /", render(0))

                for index in range(2, 6):
                    tmux("new-window", "-d", "-t", "alpha:", "-n", f"fresh{index}", str(shell))
                self.assertIn("5 fresh5", render(0))
                # The attached bar must discover new windows without re-sourcing.
                wait_for(b"5 fresh5")

                tmux("select-window", "-t", first)
                tmux("select-pane", "-t", first)
                next_window = tmux(
                    "list-windows", "-t", "alpha", "-F", "#{window_id}",
                ).splitlines()[1]
                started = directory / "slow-render-started"
                slow = f"touch {shlex.quote(str(started))}; sleep 2; printf ready"
                tmux("set-option", "-g", "status-format[0]", f"#({slow})")
                tmux("set-option", "-g", "status-format[1]", "")
                tmux("refresh-client", "-S")
                deadline = time.monotonic() + 3
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(started.exists(), "Slow status fixture did not start")
                for key, fmt, expected in (
                    (b"\x02o", "#{pane_id}", second),
                    (b"\x02n", "#{window_id}", next_window),
                ):
                    os.write(master, key)
                    deadline = time.monotonic() + 1
                    while time.monotonic() < deadline:
                        selected = tmux("display-message", "-p", "-t", "alpha:", fmt)
                        if selected == expected:
                            break
                        time.sleep(0.01)
                    self.assertEqual(selected, expected, "Slow status job blocked keyboard navigation")
            finally:
                try:
                    subprocess.run(
                        ["tmux", "-S", socket, "kill-server"], capture_output=True,
                        timeout=3,
                    )
                finally:
                    if master is not None:
                        os.close(master)
                    if client is not None and client.poll() is None:
                        client.terminate()
                        try:
                            client.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            client.kill()
                            client.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
