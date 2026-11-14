#!/usr/bin/env python3
"""Copilot lifecycle tracking and a window-grouped tmux status bar."""

import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


OPTION = "@copilot_status"
COPILOT_NAMES = ("copilot", "copilot-cli")
COLORS = {
    "waiting": "#e5b567",
    "working": "#7ca5ff",
    "idle": "#9ece6a",
    "unknown": "#858795",
}
BAR = "#1b1b20"
PILL = "#292c31"
ACTIVE = "#9ece6a"
TEXT = "#c5c8d3"
ACTIVE_DOTS = {
    COLORS["waiting"]: "#875700",
    COLORS["working"]: "#2155a3",
    COLORS["idle"]: "#245b26",
    COLORS["unknown"]: "#414454",
}


def tmux(*args):
    result = subprocess.run(
        ["tmux", *args], capture_output=True, text=True, timeout=2
    )
    return result.stdout.rstrip("\n") if result.returncode == 0 else ""


def processes():
    result = subprocess.run(
        ["ps", "-u", str(os.getuid()), "-o", "pid=,ppid=,lstart=,comm="],
        capture_output=True, text=True, timeout=2, check=True,
        env=dict(os.environ, LC_ALL="C"),
    )
    found = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 7)
        if len(fields) == 8:
            found[int(fields[0])] = {
                "parent": int(fields[1]),
                "started": " ".join(fields[2:7]),
                "name": Path(fields[7]).name,
            }
    return found


def ancestor(pid, table, predicate):
    seen = set()
    while pid in table and pid not in seen:
        seen.add(pid)
        if predicate(pid, table[pid]):
            return pid
        pid = table[pid]["parent"]
    return None


def is_copilot(process):
    return process["name"] in COPILOT_NAMES


def decode(value):
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def owner_key(owner):
    if not isinstance(owner, dict):
        return None
    fields = owner.get("started", "").split()
    # Accept both the original day-month locale and ps's fixed C locale.
    if len(fields) == 5 and fields[1].isdigit():
        fields[1], fields[2] = fields[2], fields[1]
    return owner.get("pid"), " ".join(fields)


def transition(previous, event, data, owner):
    session = data.get("sessionId")
    timestamp = data.get("timestamp")
    if (
        not isinstance(session, str) or not session
        or not isinstance(timestamp, (int, float))
        or isinstance(timestamp, bool)
        or not 0 < timestamp <= time.time() * 1000 + 60000
        or data.get("agentId")
    ):
        return None
    same_owner = owner_key(previous.get("owner")) == owner_key(owner)
    if same_owner and timestamp < previous.get("timestamp", 0):
        return None
    if (
        same_owner and previous.get("session") != session
        and event not in ("sessionStart", "userPromptSubmitted")
    ):
        return None
    if (
        same_owner and previous.get("session") == session
        and previous.get("state") == "ended" and event != "sessionStart"
    ):
        return None
    if event == "notification":
        if data.get("notification_type") not in (
            "permission_prompt", "elicitation_dialog"
        ):
            return None
        state = "waiting"
    elif event == "sessionStart":
        state = "working" if data.get("initialPrompt") else "idle"
    elif event == "agentStop":
        state = "idle"
    elif event == "sessionEnd":
        state = "ended"
    elif event in (
        "userPromptSubmitted", "preToolUse", "postToolUse", "postToolUseFailure"
    ):
        state = "working"
    else:
        return None
    return {
        "state": state, "session": session, "timestamp": timestamp, "owner": owner
    }


def hook(event):
    pane = os.environ.get("TMUX_PANE", "")
    if not os.environ.get("TMUX") or not re.fullmatch(r"%\d+", pane):
        return
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        return
    table = processes()
    pid = ancestor(os.getppid(), table, lambda _, proc: is_copilot(proc))
    if pid is None:
        return
    owner = {"pid": pid, "started": table[pid]["started"]}
    # Lock the script inode to serialize concurrent hooks without state files.
    with open(__file__) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = decode(tmux("show-options", "-pqv", "-t", pane, OPTION))
        updated = transition(previous, event, data, owner)
        if updated is not None:
            tmux("set-option", "-p", "-t", pane, OPTION, json.dumps(updated))
            tmux("refresh-client", "-S")


def pane_state(root, record, table):
    owner = record.get("owner", {})
    pid = owner.get("pid")
    live = (
        pid in table and is_copilot(table[pid])
        and owner_key(owner) == owner_key({"pid": pid, "started": table[pid]["started"]})
        and ancestor(pid, table, lambda candidate, _: candidate == root) is not None
    )
    if live and record.get("state") == "ended":
        return None
    if live and record.get("state") in COLORS:
        return record["state"]
    if any(
        is_copilot(proc)
        and ancestor(candidate, table, lambda p, _: p == root) is not None
        for candidate, proc in table.items()
    ):
        return "unknown"
    return None


def safe_text(text):
    # Prevent control characters and tmux style/format injection from names.
    return re.sub(r"[^A-Za-z0-9_. -]", "?", text)


def panes():
    table = processes()
    fmt = "\t".join((
        "#{session_name}", "#{window_index}", "#{window_id}", "#{window_name}",
        "#{pane_index}", "#{pane_id}", "#{pane_pid}", "#{pane_dead}",
        "#{pane_current_command}", "#{pane_active}", "#{@copilot_status}",
    ))
    found = []
    seen = set()
    for line in tmux("list-panes", "-a", "-F", fmt).splitlines():
        fields = line.split("\t", 10)
        if len(fields) != 11:
            continue
        session, window, wid, title, index, pid, root, dead, app, active, raw = fields
        if pid in seen:
            continue
        seen.add(pid)
        state = None if dead == "1" else pane_state(int(root), decode(raw), table)
        found.append({
            "session": safe_text(session), "window": int(window),
            "window_id": wid, "title": safe_text(title)[:30],
            "index": int(index), "id": pid, "active": active == "1",
            "app": "EXIT" if dead == "1" else safe_text(app)[:16], "state": state,
        })
    return sorted(found, key=lambda p: (p["session"], p["window"], p["index"]))


def copilot_color(pane):
    if pane["app"] not in COPILOT_NAMES:
        return None
    return COLORS.get(pane["state"], COLORS["unknown"])


def groups(items):
    windows = {}
    multiple_sessions = len({item["session"] for item in items}) > 1
    for item in items:
        wid = item["window_id"]
        if wid not in windows:
            title = f"{item['window']} {item['title']}"
            if multiple_sessions:
                title = f"{item['session']} / {title}"
            windows[wid] = {"id": wid, "title": title, "panes": []}
        windows[wid]["panes"].append(item)
    result = []
    for group in windows.values():
        parts = []
        if len(group["panes"]) > 1:
            for pane in group["panes"]:
                color = copilot_color(pane)
                text = ("\u25cf " if color else "") + pane["app"]
                parts.append((text, color, pane["id"]))
        dot_color = (
            copilot_color(group["panes"][0])
            if len(group["panes"]) == 1 else None
        )
        title = group["title"]
        if dot_color:
            pane = group["panes"][0]
            match = re.search(r"\bcopilot(?:-cli)?\b", pane["title"], re.I)
            if match:
                index = len(title) - len(pane["title"]) + match.start()
                title = title[:index] + "\u25cf " + title[index:]
            else:
                title += " \u25cf " + pane["app"]
        size = max(
            len(title) + 4,
            sum(len(p[0]) + 4 for p in parts) + max(0, len(parts) - 1),
        )
        result.append(dict(group, title=title, parts=parts, dot_color=dot_color, width=size))
    return result


def fitted_parts(parts, width):
    if sum(len(part[0]) + 4 for part in parts) + len(parts) - 1 <= width:
        return parts, ""
    selected = []
    used = 0
    for index, (text, color, target) in enumerate(parts):
        more = len(parts) - index - 1
        reserve = len(f" +{more}") if more else 0
        gap = int(bool(selected))
        if used + gap + len(text) + 4 + reserve > width:
            break
        selected.append((text, color, target))
        used += gap + len(text) + 4
    hidden = len(parts) - len(selected)
    suffix = f" +{hidden}" if hidden else ""
    if not selected:
        suffix = f"+{hidden}"[:width]
    return selected, suffix


def layout(items, width, active_window):
    windows = groups(items)
    available = width
    if sum(g["width"] + 1 for g in windows) - 1 <= available:
        return windows, ""
    suffix = f" +{len(windows)} windows"
    budget = max(0, available - len(suffix))
    ranked = sorted(windows, key=lambda g: (
        g["id"] != active_window,
        not any(p["state"] == "waiting" for p in g["panes"]),
        not any(p["state"] == "working" for p in g["panes"]),
    ))
    chosen = {}
    for group in ranked:
        size = min(group["width"], budget) if not chosen else group["width"]
        if size >= 5 and size <= budget:
            chosen[group["id"]] = dict(group, width=size)
            budget -= size + 1
    hidden = len(windows) - len(chosen)
    suffix = f" +{hidden} windows"
    return [chosen[g["id"]] for g in windows if g["id"] in chosen], suffix


def rounded(content, color, target):
    return (
        f"#[range=user|{target},fg={color},bg={BAR},nobold,nodim,nounderscore]\ue0b6"
        f"#[bg={color}]{content}"
        f"#[fg={color},bg={BAR},nobold,nounderscore]\ue0b4#[norange,default]"
    )


def styled_label(text, color, active):
    foreground = BAR if active else TEXT
    if color:
        color = ACTIVE_DOTS[color] if active else color
        text = text.replace(
            "\u25cf", f"#[fg={color}]\u25cf#[fg={foreground}]", 1,
        )
    return f"#[fg={foreground}]{text}"


def window_cell(group, row, active_window):
    target = next(
        (p["id"] for p in group["panes"] if p["active"]),
        group["panes"][0]["id"],
    )
    if row == 0:
        active = group["id"] == active_window
        background = ACTIVE if active else PILL
        dot_color = group["dot_color"]
        width = group["width"] - 2
        title = group["title"][:width].center(width)
        emphasis = "#[bold]" if active else ""
        return rounded(emphasis + styled_label(title, dot_color, active), background, target)
    parts, suffix = fitted_parts(group["parts"], group["width"])
    chunks = []
    for text, color, pid in parts:
        active = group["id"] == active_window and pid == target
        background = ACTIVE if active else PILL
        chunks.append(rounded(styled_label(f" {text} ", color, active), background, pid))
    used = sum(len(text) + 4 for text, _, _ in parts) + max(0, len(parts) - 1) + len(suffix)
    padding = max(0, group["width"] - used)
    return (
        " " * (padding // 2) + " ".join(chunks)
        + "#[norange,fg=#858795]" + suffix + " " * (padding - padding // 2)
    )


def render(items, row, width, active_window):
    windows, suffix = layout(items, width, active_window)
    if not windows:
        text = suffix.strip()
        return "#[norange,fg=#858795]" + text[:width]
    used = sum(g["width"] for g in windows) + len(windows) - 1 + len(suffix)
    start = max(0, (width - used) // 2)
    left = ""
    sessions = {p["session"] for p in items}
    if row == 0 and len(sessions) == 1:
        left = f"session {next(iter(sessions))}"
    if len(left) + 2 > start:
        left = ""
    output = "#[norange,fg=#858795]" + left.ljust(start)
    output += " ".join(window_cell(g, row, active_window) for g in windows)
    hidden_waiting = any(
        p["state"] == "waiting" and p["window_id"] not in {g["id"] for g in windows}
        for p in items
    )
    color = COLORS["waiting"] if hidden_waiting else "#858795"
    output += f"#[norange,fg={color}]" + suffix
    tail = time.strftime("%H:%M %d/%m") if row == 0 else ""
    if tail and start + used + len(tail) + 2 <= width:
        output += "#[fg=#858795]" + " " * (width - start - used - len(tail)) + tail
    return output


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "hook":
        try:
            hook(sys.argv[2])
        except Exception:
            # Display-only hooks must never deny a tool or interrupt Copilot.
            pass
    elif len(sys.argv) == 5 and sys.argv[1] == "render":
        try:
            row, width = int(sys.argv[2]), max(0, int(sys.argv[3]))
            print(render(panes(), row, width, sys.argv[4]))
        except Exception:
            print("#[fg=#858795] Copilot: unavailable")


if __name__ == "__main__":
    main()
