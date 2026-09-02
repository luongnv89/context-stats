# Troubleshooting

## Start here: `context-stats doctor`

Most "it doesn't work" reports come down to the status line never having been
activated — `pip install context-stats` installs the commands but cannot wire
`statusLine` into Claude Code's `~/.claude/settings.json` for you. `doctor`
checks that and every other link in the chain, and prints the exact fix:

```bash
context-stats doctor
```

```bash
# repair the settings.json wiring in place (backs up first, preserves other keys)
context-stats doctor --fix

# replace a statusLine that currently points at a different tool
context-stats doctor --fix --force
```

It exits non-zero when any check fails. Restart Claude Code after a `--fix`.

## The "statusLine is not wired" startup hint

Because the CLI is the one context-stats process guaranteed to run while the
status line is unwired, every `context-stats` invocation prints a one-line
hint on stderr until `statusLine` is configured:

```
! statusLine is not wired into ~/.claude/settings.json — the status line will never run. Fix: context-stats doctor --fix
```

The hint is stderr-only and never changes the command's output or exit code.
It appears once `settings.json` exists and parses but has no effective
`statusLine` block; it stays silent when the file is missing, unreadable, or
malformed (doctor diagnoses those on its own terms). Running
`context-stats doctor --fix` wires the status line and the hint disappears.

To suppress the hint without wiring the status line:

```bash
# in ~/.claude/statusline.conf
suppress_setup_hint=true
```

or with the environment variable (no config file needed):

```bash
export CONTEXT_STATS_SUPPRESS_SETUP_HINT=1
```

Either one suppresses it; see [`docs/configuration.md`](configuration.md) for
the full key reference.

## Common Issues

### Status line not appearing

Run `context-stats doctor` first — it covers every step below automatically.

**macOS/Linux (shell installer):**

1. Check script is executable:

   ```bash
   chmod +x ~/.claude/statusline.py
   ```

2. Test the script:

   ```bash
   echo '{"model":{"display_name":"Test"}}' | python3 ~/.claude/statusline.py
   ```

3. Verify settings.json configuration:

   ```bash
   cat ~/.claude/settings.json
   ```

**pip install:**

1. Verify the command is available:

   ```bash
   which claude-statusline
   ```

2. Test it:

   ```bash
   echo '{"model":{"display_name":"Test"}}' | claude-statusline
   ```

3. Ensure your settings.json uses `"command": "claude-statusline"` (not a file path).

**Windows (Python):**

```powershell
echo {"model":{"display_name":"Test"}} | python %USERPROFILE%\.claude\statusline.py
```

### context-stats command not found

1. Verify installation:

   ```bash
   which context-stats
   ```

2. Reinstall if missing:

   ```bash
   pip install context-stats
   ```

3. Check PATH if pip installed to user directory:

   ```bash
   # zsh
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
   source ~/.zshrc

   # bash
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
   source ~/.bashrc
   ```

### pip install fails

1. Ensure Python 3.10+:

   ```bash
   python3 --version
   ```

2. Try with `--user` flag:

   ```bash
   pip install --user context-stats
   ```

3. Or use `uv`:

   ```bash
   uv pip install context-stats
   ```

### `error: unrecognized arguments: <session_id>` on export

Running `context-stats <session_id> export` fails with:

```
python3 -m claude_statusline.cli.context_stats: error: unrecognized arguments: <session_id>
```

The installed Python package is missing or too old to know the `export`
subcommand — typically a stale global install left behind by an installer
from before the package was auto-installed.

1. Check the installed version and upgrade it:

   ```bash
   pip show context-stats
   pip install --upgrade context-stats
   ```

2. If pip is unavailable in your environment, reinstall with the shell
   installer, which auto-installs/upgrades the matching package version:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/luongnv89/context-stats/main/install.sh | bash
   ```

3. Verify the fix from any directory:

   ```bash
   context-stats --version
   context-stats <session_id> export --output report.md
   ```

### No token graph data

Token history requires:

1. Python statusline script (the Python script writes state files)
2. `show_delta=true` in `~/.claude/statusline.conf` (default)
3. Active Claude Code session generating state files
4. State files at `~/.claude/statusline/statusline.<session_id>.state`

Check for state files:

```bash
ls -la ~/.claude/statusline/statusline.*.state
```

### Git info not showing

1. Verify you're in a git repository:

   ```bash
   git rev-parse --is-inside-work-tree
   ```

2. Check git is installed:

   ```bash
   which git
   ```

3. Git commands have a 5-second timeout. If your repo is very large, git operations may time out silently.

### Wrong token colors

Context token colors are based on Model Intelligence (MI) score, not raw percentages:

| MI Score  | Expected Color |
| --------- | -------------- |
| > 0.70    | Green          |
| 0.40–0.70 | Yellow         |
| < 0.40    | Red            |

Per-property colors (e.g., `color_context_length=bold_white`) override MI-based coloring when explicitly set. If colors look wrong, check terminal color support and your `~/.claude/statusline.conf` settings.

### Delta always shows zero

Token delta requires multiple statusline refreshes. The first refresh establishes a baseline; subsequent refreshes show the delta.

If delta is always zero after multiple refreshes, check that the state file is being written:

```bash
wc -l ~/.claude/statusline/statusline.*.state
```

### Configuration not taking effect

1. Check config file location:

   ```bash
   cat ~/.claude/statusline.conf
   ```

2. Verify syntax (no spaces around `=`):

   ```bash
   # Correct
   show_delta=true

   # Wrong
   show_delta = true
   ```

3. Restart Claude Code after config changes.

## Debug Mode

### Test script output

```bash
# Create test input
cat << 'EOF' > /tmp/test-input.json
{
  "model": {"display_name": "Opus 4.5"},
  "cwd": "/test/project",
  "session_id": "test123",
  "context": {
    "tokens_remaining": 64000,
    "context_window": 200000,
    "autocompact_buffer_tokens": 45000
  }
}
EOF

# Test installed version
cat /tmp/test-input.json | claude-statusline

# Or test standalone script directly
cat /tmp/test-input.json | python3 ~/.claude/statusline.py
```

### Check state files

```bash
# View state file content
cat ~/.claude/statusline/statusline.*.state

# Watch state file updates
watch -n 1 'tail -5 ~/.claude/statusline/statusline.*.state'
```

## Getting Help

- Check [existing issues](https://github.com/luongnv89/context-stats/issues)
- Open a new issue with:
  - Operating system
  - Shell type (bash/zsh)
  - Installation method (pip, uv, manual)
  - Script version being used
  - Error messages or unexpected behavior
