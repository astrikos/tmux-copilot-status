# tmux-copilot-status

A rounded tmux status bar that groups every pane directly beneath its window
and shows the activity of GitHub Copilot CLI sessions.

```text
              (            1 code           ) (2 server) (3 review)
              ( copilot ) ( zsh ) ( copilot )
```

The actual bar uses rounded Powerline buttons. Status is expressed through
their background colors, not written words: blue for working, amber for
waiting, green for idle, slate gray for unknown, and dark gray for ordinary
shell panes. The active window's title is bold and underlined.

The two rows describe the same columns: **window above, its panes below**.
Single-pane windows show only their colored window header; their space on
the second row stays empty. Multi-pane windows show their process buttons
below, and their headers grow to fit those buttons. The window groups remain
centered together on both rows. Pane labels show their current process, such
as `copilot`, `zsh`, or `node`, without pane numbers. Shell panes remain
neutral, not incorrectly colored as idle Copilots. When multiple tmux sessions
exist, headers include the session name, for example `backend / 2 code`.

## Requirements

- macOS or Linux.
- tmux 3.3 or newer on `PATH`.
- Python 3.9 or newer; standard library only.
- `ps` on `PATH` with support for `pid`, `ppid`, `lstart`, and `comm`.
- A recent GitHub Copilot CLI supporting the lifecycle and notification hooks
  listed below, with hooks enabled.
- A terminal font containing the Powerline round-cap glyphs U+E0B6 and U+E0B4,
  such as a Nerd Font. Square boxes instead of rounded ends mean these glyphs
  are missing from the terminal's font.

Developed and tested on macOS with tmux 3.6b, Python 3.9, and Copilot CLI
1.0.112. Linux is an intended target, but has not yet been exercised on a
Linux machine. Native Windows is not supported.

## Install on another machine

Clone this project on that machine, then run:

```sh
git clone https://github.com/astrikos/tmux-copilot-status.git
cd tmux-copilot-status
python3 install.py
```

No `pip` packages, TPM plugins, background daemon, or administrator access are
needed. Use a Python installation that will remain available, rather than a
temporary virtual environment.

The installer prints the exact reload command for the tmux configuration it
selected. For the usual `~/.tmux.conf`:

```sh
tmux source-file ~/.tmux.conf
```

**Restart existing Copilot sessions once, and send a prompt.** A newly opened
CLI can retain the unknown color until its first prompt when hook loading is
deferred until after startup or folder admission. The first submitted prompt
should turn its button blue, then green when the response finishes.

If there is no tmux server running yet, start tmux normally instead of
reloading. Copilot must run inside a tmux pane for that pane to report state.
Normal tmux window and pane creation is discovered automatically; it does not
require reinstalling or reloading this project.

### Paths and existing configuration

By default the installer creates:

```text
~/.config/tmux/copilot-status/
    status.py        # Hook handler and renderer
    theme.conf       # Status theme and click binding
    status.conf      # Generated, machine-specific tmux commands
    font.py          # Optional font setup and independent rollback helper
~/.copilot/hooks/
    tmux-status.json # Generated lifecycle hooks
```

`XDG_CONFIG_HOME` changes the `.config` root; `COPILOT_HOME` changes the
`.copilot` root. Set these consistently when installing and running the CLI.
Generated commands contain the destination paths and the Python interpreter
used to run the installer. Reinstall on each machine; do not copy generated
configuration between machines.

The installer uses an existing `~/.tmux.conf` first, then an existing
`$XDG_CONFIG_HOME/tmux/tmux.conf` (normally `~/.config/tmux/tmux.conf`).
Otherwise it creates `~/.tmux.conf`. An explicit path is also supported:

```sh
python3 install.py --tmux-conf ~/.config/tmux/tmux.conf
```

It adds a source line at the end of that file, without replacing the rest of
your configuration. First-time installs add a marked block; the original
prototype's source line is recognized and reused. Existing user hook files
and Copilot settings are not modified.

Changed files receive a one-time adjacent `.copilot-status.bak` backup.
Repeating installation does not duplicate the include or overwrite that
backup. The generated `tmux-status.json` file belongs to this project and is
replaced on updates.

**This is an opinionated two-row status theme**, not just a state provider.
It replaces `status-format[0]` and `[1]`, status colors, the refresh interval,
and the left-click status binding. It does not change your prefix, shell,
pane layout, or keyboard navigation. Load other status themes before it, or
they may overwrite its output.

### Optional: rounded-cap font on macOS, with rollback

The status installer does not change your terminal font. For Alacritty on
macOS, an explicit opt-in command installs the Homebrew cask
`font-meslo-lg-nerd-font` and selects `MesloLGS Nerd Font Mono`:

```sh
python3 font.py install
```

Homebrew must already be installed. Existing fonts are not removed. Only
this font cask is installed; Homebrew auto-update and automatic cleanup are
disabled for that command.

**Revert the terminal configuration with one command:**

```sh
python3 ~/.config/tmux/copilot-status/font.py restore
```

The installer prints an exact restore command for your paths. If you use
`XDG_CONFIG_HOME`, use its `tmux/copilot-status/font.py` helper instead.
Both actions support `--config /path/to/alacritty.toml`.

Before installing anything, the font tool saves the original configuration
byte-for-byte as an adjacent `alacritty.copilot-font-backup.toml`, plus a
`alacritty.copilot-font-state.json` containing integrity hashes. It then
imports that saved original from a small new config that selects explicit
Regular, Bold, Italic, and Bold Italic faces. Keeping the backup in the same
directory preserves relative imports. **Do not edit, move, or delete these
recovery files.**

Repeated installation preserves the first backup. Restore checks its
integrity and refuses to overwrite subsequent config edits. If you have
saved those later edits elsewhere and deliberately want to discard them:

```sh
python3 ~/.config/tmux/copilot-status/font.py restore --force
```

Restore leaves the font installed but unused by this setup. Removing the
font package is a separate, optional action; check that other apps do not
use it first:

```sh
brew uninstall --cask font-meslo-lg-nerd-font
```

Alacritty normally reloads its config automatically. If it reports
`Unable to load specified font` immediately after installation, fully quit
and reopen Alacritty so it can discover the newly installed font; opening
another window in the same process might not be sufficient. Detach from
tmux first and reattach afterward. No tmux server or Copilot restart is
needed for a font change.
Symlinked Alacritty configs are intentionally refused rather than rewritten.
On Linux or other terminals, configure a compatible font manually; this
optional installer only automates macOS Alacritty.

## Reading the bar

| Button background | Meaning |
| --- | --- |
| Blue | Copilot has received a prompt or reported tool activity. |
| Amber | A permission prompt or question requests your attention. |
| Green | Copilot reported the end of its turn. |
| Slate gray | A Copilot process exists, but no usable hook state is available. |
| Dark gray | An ordinary pane, or a pane without an active Copilot process. |

Window headers summarize their panes in this priority order: waiting,
working, idle, unknown, then ordinary panes. A single waiting pane therefore
turns its window header amber too.

Pane labels come from tmux's `pane_current_command`, without arguments.
Identical processes have identical labels but remain separately clickable.
Window numbers come from tmux; the installer does not force zero-based or
one-based numbering. To see pane indexes temporarily, use your tmux prefix
followed by `q`.

When there is room, a session label appears on the left and a clock on the
right; the window/pane groups remain centered. If the terminal is too narrow,
it keeps the active window first, then prefers windows needing attention and
those with working agents.
`+N windows` or a `+N` count beneath a window indicates hidden content.
The window-overflow label turns amber if any hidden window needs attention.
More terminal width lets the renderer show more groups.

With tmux mouse support enabled, clicking a window header selects its active
pane; clicking a pane label selects that pane, even in another session:

```tmux
set -g mouse on
```

## Architecture

```text
Copilot CLI lifecycle event
    |
    v
~/.copilot/hooks/tmux-status.json
    |
    v
status.py hook EVENT   < JSON payload on stdin
    |
    +-- locate the owning Copilot process
    +-- validate session identity and event ordering
    +-- store small JSON metadata in the tmux pane option @copilot_status
    +-- request a status redraw
    |
    v
tmux status-format[0] and status-format[1]
    |
    v
status.py render ROW WIDTH ACTIVE_WINDOW
    |
    +-- enumerate panes in every session on this tmux server
    +-- verify process identity and pane ancestry
    +-- group panes beneath their owning windows
    +-- emit bounded-width tmux style strings and mouse target ranges
```

### State producer

Copilot runs a short local command for each registered event. The handler
uses `TMUX_PANE` to identify the pane and `TMUX` to address the correct server.
It walks its parent processes to find the owning `copilot` or `copilot-cli`
process. Outside tmux, it does nothing.

| Event | State |
| --- | --- |
| `sessionStart` | `IDLE`, or `WORK` if there is an initial prompt |
| `userPromptSubmitted` | `WORK` |
| `preToolUse`, `postToolUse`, `postToolUseFailure` | `WORK` |
| `notification` with `permission_prompt` or `elicitation_dialog` | `WAIT` |
| `agentStop` | `IDLE` |
| `sessionEnd` | Ended; no active Copilot state is displayed |

Permission checks alone do not set `WAIT`: checks can be automatically
approved without ever blocking on a person. Background completion
notifications also do not change the foreground state.

Each pane's JSON record contains only:

```json
{
  "state": "working",
  "session": "copilot-session-id",
  "timestamp": 1794668000000,
  "owner": {
    "pid": 12345,
    "started": "Sat Nov 14 15:48:59 2026"
  }
}
```

No prompts, responses, tool arguments, or terminal scrollback are persisted.
The tracker reads the hook payload to select an event, then discards it.
It makes no network requests.

Concurrent hook updates serialize with `flock` on the installed script.
Older timestamps and late events from ended sessions are ignored. The shell
wrapper and Python entry point suppress display-hook failures so they cannot
accidentally deny a tool or change the CLI's permission policy.

### State consumer

Tmux invokes the renderer separately for each status row every two seconds.
Both rows use the same sizing rules, so each lower pane group sits beneath
the matching window. The renderer lists all sessions on the **same tmux
server**, including detached sessions. Linked windows are shown once.

It checks each stored owner's PID, process start time, and ancestry against
the pane's root process. Exited or replaced processes do not keep stale
working badges. A still-running CLI without valid metadata uses the unknown
color, not a guessed idle state. Ordinary shell panes remain visible.
Process timestamps use a fixed locale, with compatibility for the original
prototype's date ordering.

There is no polling daemon or separate state database. Tmux owns the
ephemeral per-pane metadata; installed Python and configuration files are the
only persistent components.

## Limitations

- **These are event-derived states, not a perfect live execution feed.**
  There is no documented approval-dialog-dismissed event in the hooks used
  here. After approval, the amber color may remain until another tool event
  arrives. Concurrent tools and asynchronously delivered notifications can
  also temporarily make the state approximate.
- Interruptions or missed hooks can leave the last state visible until
  another event arrives. There is deliberately no idle timeout that would
  incorrectly dismiss a long-running operation or permission prompt.
- The green idle color describes the foreground turn, not completion of every
  background task or subagent. This project tracks CLI instances in panes,
  not individual subagents.
- One foreground Copilot process per pane is assumed. Process discovery
  recognizes executables named `copilot` and `copilot-cli`; unusual launchers
  that keep a different process name may need adaptation.
- Separate tmux servers, remote hosts, and nested tmux instances are separate
  inventories. Install on each host and look at that server's status bar.
- Names are sanitized to ASCII before rendering; non-ASCII and tmux format
  metacharacters become `?`. Very long names are shortened.
- Theme colors are currently constants in `status.py` and `theme.conf`.
  Edit the source and rerun the installer to customize them.

## Troubleshooting

**A new window is missing:** it should appear within two seconds. Check
`tmux list-windows -a`, then the terminal width and any `+N windows` label.
An empty state on a new pane must not hide it; this has a regression test.

**Copilot stays slate gray:** restart it after the first installation and send
one prompt. If it stays unknown, check that hooks are enabled and inspect
only the pane's metadata:

```sh
tmux show-options -pqv -t %9 @copilot_status
```

Replace `%9` with the pane ID from:

```sh
tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} #{pane_id}'
```

For example, `project:2.0 %9` means session `project`, window `2`, pane index
`0`, internal pane ID `%9`. The visible bar deliberately avoids this compact
address notation.

**The bar says `unavailable`:** verify `tmux` and `ps` are on the PATH inherited
by the tmux server, and rerun installation if the selected Python interpreter
moved. For an unsuppressed diagnostic, run the renderer with your actual
window ID:

```sh
python3 -c 'import status; print(status.render(status.panes(), 1, 160, "@0"))'
```

Run that command from this project's directory inside tmux. `@0` identifies
the window to highlight, not a session or pane.

**Clicks do not work:** enable `mouse` in tmux, check that another config did
not replace `MouseDown1Status`, and reload the tmux configuration.

## Updating and testing

After changing or updating this checkout, rerun `python3 install.py` and the
printed tmux reload command. The installation uses copies, not symlinks, so
moving the checkout does not break the running setup. Restart Copilot if the
hook event configuration changed.

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use temporary home directories and isolated tmux sockets. They cover
installation idempotence, quoted paths, lifecycle transitions, stale events,
PID reuse, locale migration, aligned window/pane widths, overflow, newly
created windows, and actual status output through a pseudo-terminal.
Font tests verify exact rollback, later-edit protection, corrupt-backup
protection, failed-install recovery, and idempotence without installing fonts.
The end-to-end test uses `cc` to build a tiny local process-name fixture; it
does not launch a real Copilot session or call an AI service, and is skipped
if no C compiler is available. Production installation does not need `cc`.

## Removing it

Remove this project's marked source block (or the prototype's source line)
from your tmux configuration and remove only its hook file:

```sh
rm "${COPILOT_HOME:-$HOME/.copilot}/hooks/tmux-status.json"
```

Do not delete the whole Copilot hooks directory: it may contain other hooks.
After removing the include, reset the generated status formats and restore
tmux's standard status-click action before reloading your own config:

```sh
tmux set-option -gu status-format
tmux set-option -g status 1
tmux bind-key -n MouseDown1Status select-window -t =
tmux source-file ~/.tmux.conf
```

Use your actual configuration path for the last command. Restore any custom
status-click binding you had instead of the standard binding above. If your
config does not set status colors or the refresh interval, those runtime
options will remain until you reset them or start a fresh tmux server.
Restart Copilot to unload the hooks. The installed files and their backups
can then be removed individually if desired.

## References

- GitHub Docs: Copilot hooks reference and notification payloads.
- The `tmux(1)` manual: pane user options, status formats, and mouse ranges.
- Visual inspiration: `JanSuthacheeva/tmux-agent-status`. This project
  implements its own per-pane tracker and grouped renderer; it does not
  require that plugin.
