import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("status", ROOT / "status.py")
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)


def plain(text):
    return re.sub(r"#\[[^]]*\]", "", text)


def pane(index=0, window=1, state="working", session="project"):
    return {
        "session": session, "window": window, "window_id": f"@{window}",
        "title": f"code{window}", "index": index, "id": f"%{window}{index}",
        "active": index == 0, "app": "copilot" if state else "zsh", "state": state,
    }


class Transitions(unittest.TestCase):
    def setUp(self):
        self.owner = {"pid": 42, "started": "test"}
        self.now = int(time.time() * 1000)
        self.data = {"sessionId": "session", "timestamp": self.now}

    def event(self, previous, event, offset=0, **extra):
        return status.transition(
            previous, event, dict(self.data, timestamp=self.now + offset, **extra),
            self.owner,
        )

    def test_normal_lifecycle_and_both_wait_types(self):
        record = self.event({}, "sessionStart")
        self.assertEqual(record["state"], "idle")
        record = self.event(record, "userPromptSubmitted", 1)
        self.assertEqual(record["state"], "working")
        for offset, notification in enumerate(
            ("permission_prompt", "elicitation_dialog"), 2
        ):
            record = self.event(
                record, "notification", offset * 2,
                notification_type=notification,
            )
            self.assertEqual(record["state"], "waiting")
            record = self.event(record, "postToolUse", offset * 2 + 1)
            self.assertEqual(record["state"], "working")
        record = self.event(record, "agentStop", 20)
        self.assertEqual(record["state"], "idle")
        self.assertEqual(self.event(record, "sessionEnd", 21)["state"], "ended")

    def test_background_notifications_do_not_change_foreground(self):
        record = self.event({}, "notification", notification_type="permission_prompt")
        for kind in ("shell_completed", "agent_completed", "agent_idle"):
            self.assertIsNone(self.event(record, "notification", 1, notification_type=kind))

    def test_delayed_events_and_end_tombstone(self):
        record = self.event({}, "agentStop", 10)
        self.assertIsNone(self.event(
            record, "notification", 5, notification_type="permission_prompt",
        ))
        record = self.event(record, "sessionEnd", 11)
        self.assertIsNone(self.event(record, "postToolUse", 12))
        self.assertEqual(self.event(record, "sessionStart", 13)["state"], "idle")

    def test_old_session_cannot_clear_current_session(self):
        record = self.event({}, "userPromptSubmitted")
        self.assertIsNone(status.transition(
            record, "sessionEnd",
            {"sessionId": "older-session", "timestamp": self.now + 1}, self.owner,
        ))

    def test_invalid_payloads_and_subagents_are_ignored(self):
        for data in ({}, {"sessionId": "x", "timestamp": True},
                     dict(self.data, agentId="child"),
                     dict(self.data, timestamp=float("nan"))):
            self.assertIsNone(status.transition({}, "preToolUse", data, self.owner))

    def test_hooks_are_safe_outside_tmux_and_on_malformed_input(self):
        for payload in ("not json", "[]", json.dumps(self.data)):
            result = subprocess.run(
                [os.sys.executable, str(ROOT / "status.py"), "hook", "preToolUse"],
                input=payload, text=True, capture_output=True,
                env=dict(os.environ, TMUX="", TMUX_PANE=""),
            )
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))


class Rendering(unittest.TestCase):
    def test_window_and_pane_cells_align_and_do_not_hide_fitting_panes(self):
        items = [pane(state="unknown"), pane(index=1, state=None), pane(window=2)]
        top = plain(status.render(items, 0, 100, "@1"))
        bottom = plain(status.render(items, 1, 100, "@1"))
        self.assertEqual(top.index("\ue0b6"), 34)
        self.assertEqual(bottom.index("\ue0b6"), 34)
        self.assertEqual(bottom.count("copilot"), 1)
        self.assertEqual(bottom.count("zsh"), 1)
        self.assertNotIn("+1", bottom)
        for word in ("UNKNOWN", "WORK", "WAIT", "IDLE", "p0", "p1"):
            self.assertNotIn(word, bottom)
        styled = status.render(items, 1, 100, "@1")
        self.assertIn(status.COLORS["unknown"], styled)
        self.assertIn(status.COLORS["working"], status.render(items, 0, 100, "@1"))

    def test_single_pane_has_only_a_colored_clickable_header(self):
        item = pane(state="waiting")
        item["app"] = "long-process-name"
        item["title"] = "one"
        top = status.render([item], 0, 20, "@1")
        bottom = status.render([item], 1, 20, "@1")
        self.assertIn("1 one", plain(top))
        self.assertIn("bg=" + status.COLORS["waiting"], top)
        self.assertIn("#[range=user|%10,", top)
        self.assertEqual(plain(bottom).strip(), "")
        self.assertNotIn("#[range=user|", bottom)
        item["app"] = "sh"
        self.assertEqual(status.render([item], 0, 20, "@1"), top)

    def test_header_color_prioritizes_waiting_and_marks_active_window(self):
        items = [pane(), pane(index=1, state="waiting")]
        styled = status.render(items, 0, 100, "@1")
        self.assertIn("bg=" + status.COLORS["waiting"], styled)
        self.assertIn("bold,underscore", styled)

    def test_width_budget_and_active_window_survives_overflow(self):
        items = [pane(window=i, state="waiting" if i == 2 else "working")
                 for i in range(1, 15)]
        for width in range(0, 350):
            for row in (0, 1):
                result = plain(status.render(items, row, width, "@14"))
                self.assertLessEqual(len(result), width, (width, row, result))
        self.assertIn("14 code14", plain(status.render(items, 0, 80, "@14")))
        self.assertIn("windows", plain(status.render(items, 1, 80, "@14")))
        self.assertIn(status.COLORS["waiting"], status.render(items, 0, 80, "@14"))

    def test_different_sessions_are_labeled(self):
        items = [pane(), pane(window=2, session="backend")]
        self.assertIn("project / 1", plain(status.render(items, 0, 150, "@1")))
        self.assertIn("backend / 2", plain(status.render(items, 0, 150, "@1")))

    def test_last_pane_with_empty_state_is_not_dropped(self):
        output = "project\t5\t@5\tcopilot\t0\t%5\t42\t0\tcopilot\t1\t\n"
        table = {42: {"parent": 1, "started": "now", "name": "copilot"}}
        result = subprocess.CompletedProcess([], 0, output, "")
        with patch.object(status, "processes", return_value=table):
            with patch.object(status.subprocess, "run", return_value=result):
                items = status.panes()
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["window"], items[0]["state"]), (5, "unknown"))

    def test_process_exit_and_pid_reuse_discard_stale_state(self):
        record = {"state": "working", "owner": {"pid": 42, "started": "old"}}
        self.assertIsNone(status.pane_state(42, record, {}))
        table = {42: {"parent": 1, "started": "new", "name": "copilot"}}
        self.assertEqual(status.pane_state(42, record, table), "unknown")
        table[42]["name"] = "zsh"
        self.assertIsNone(status.pane_state(42, record, table))

    def test_existing_process_identity_survives_locale_normalization(self):
        record = {
            "state": "idle",
            "owner": {"pid": 42, "started": "Sat 14 Nov 15:48:59 2026"},
        }
        table = {
            42: {"parent": 1, "started": "Sat Nov 14 15:48:59 2026", "name": "copilot"},
        }
        self.assertEqual(status.pane_state(42, record, table), "idle")

    def test_names_cannot_inject_tmux_formats(self):
        self.assertNotIn("#", status.safe_text("#{window_name}#[bg=red]\n"))


if __name__ == "__main__":
    unittest.main()
