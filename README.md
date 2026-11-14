# tmux-copilot-status

Centered, rounded tmux windows with per-pane GitHub Copilot CLI activity.
Python standard library only; no plugin manager or daemon.

## Contents

- [Install](#install)
- [Appearance](#appearance)
- [How it works](#how-it-works)
- [Font and rollback](#font-and-rollback)
- [Update and test](#update-and-test)
- [Uninstall](#uninstall)

## Install

Requires macOS or Linux, Python 3.9+, tmux 3.3+, `ps`, and Copilot CLI with
lifecycle hooks enabled. Linux support is not yet tested.

```sh
git clone https://github.com/astrikos/tmux-copilot-status.git
cd tmux-copilot-status
python3 install.py
tmux source-file ~/.tmux.conf
```

Use the installer's reload command if it selects another config path.
Restart existing Copilots once and send a prompt to initialize their status.

Runtime files go in `~/.config/tmux/copilot-status`; hooks go in
`~/.copilot/hooks/tmux-status.json`. Supports `XDG_CONFIG_HOME`, `COPILOT_HOME`,
and `install.py --tmux-conf PATH`. Changed files get a one-time
`.copilot-status.bak` backup.

This replaces the status theme and status-click binding, not your pane layout
or keyboard shortcuts.

## Appearance

**Green = active window. Slate with bold white text = selected pane.**
Other pills stay neutral.
Only `copilot` and `copilot-cli` processes get colored activity dots:

| Dot | State |
| --- | --- |
| Blue | Working |
| Amber | Waiting for permission or an answer |
| Green | Idle |
| Gray | Selected pane, or unknown status |

Single-pane windows have no lower button; their dot sits inside the header,
immediately before `copilot`. The selected Copilot's dot stays gray; status
tracking continues, and its status color returns when you switch away.
Split windows show process buttons underneath. Groups stay centered;
`+N windows` indicates overflow. Enable tmux mouse support to click headers
or pane buttons, including across sessions.

## How it works

```text
Copilot hook -> status.py -> pane-local @copilot_status -> tmux status rows
```

Hooks track prompts, tools, attention requests, turn completion, and session
end. The renderer refreshes every two seconds across the same tmux server,
checking process identity to discard stale owners.

Status rendering runs asynchronously; navigation never waits for Python.
Mouse clicks use native tmux commands. Repeated hook states update metadata
without requesting redundant redraws.

Only state, session ID, timestamp, and process identity are stored. No prompts,
tool arguments, or scrollback. Hook-derived states are approximate: missed
events can leave an old state, and waiting clears on the next activity event.

## Font and rollback

Rounded ends need a font with U+E0B6/U+E0B4. For macOS Alacritty, optionally
install MesloLGS Nerd Font Mono through Homebrew:

```sh
python3 font.py install
```

Undo the terminal change:

```sh
python3 ~/.config/tmux/copilot-status/font.py restore
```

Both commands support `--config PATH`. The original config is preserved
byte-for-byte in an adjacent `.copilot-font-backup.toml`, with integrity hashes
in `.copilot-font-state.json`. Keep both files. Restore refuses later edits
unless explicitly forced; the font itself remains installed.

If glyphs remain boxes, detach from tmux and fully quit/reopen Alacritty.
For other terminals, select a compatible font manually.

## Update and test

After pulling updates, rerun `python3 install.py` and its reload command.
Installed files are copies, so the checkout can move afterward.

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use temporary homes and isolated tmux servers. The terminal integration
test needs `cc`; no real Copilot sessions or AI calls are made.

## Uninstall

Restore the font first if desired. Remove this project's source include from
your tmux config, then:

```sh
rm "${COPILOT_HOME:-$HOME/.copilot}/hooks/tmux-status.json"
tmux set-option -gu status-format
tmux set-option -g status 1
tmux set-option -gu status-style
tmux set-option -gu status-interval
tmux bind-key -n MouseDown1Status select-window -t =
tmux source-file ~/.tmux.conf
```

Use your actual config path and restore any custom status-click binding.
Restart Copilot to unload the hooks.

Inspired by `JanSuthacheeva/tmux-agent-status`; implemented independently.
