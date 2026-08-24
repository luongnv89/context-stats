# Installation Guide

## Quick Install

### Python (pip) — Recommended

```bash
pip install context-stats
```

Or with uv:

```bash
uv pip install context-stats
```

Installing the package is only half the setup — the status line stays invisible
until Claude Code is told to run it. Wire it up automatically:

```bash
context-stats doctor --fix
```

This writes the block below into `~/.claude/settings.json`, preserving every
other key and taking a timestamped backup first. It is idempotent, and it will
not overwrite a `statusLine` already pointing at a different tool unless you
add `--force`.

To do it by hand instead, add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-statusline"
  }
}
```

Restart Claude Code afterwards.

### Verify the installation

```bash
context-stats doctor
```

`doctor` checks the console scripts on `PATH`, renders a synthetic payload in a
sandbox, validates the `statusLine` wiring (including whether the configured
command actually resolves), and inspects the state directory. It exits non-zero
if anything is broken, so it is safe to drop into a provisioning script.

### Install from Source

```bash
git clone https://github.com/luongnv89/context-stats.git
cd context-stats
pip install .
```

### Windows

```powershell
pip install context-stats
```

Or manually copy the script:

```powershell
git clone https://github.com/luongnv89/context-stats.git
copy context-stats\scripts\statusline.py %USERPROFILE%\.claude\statusline.py
copy context-stats\scripts\_statusline_shared.py %USERPROFILE%\.claude\_statusline_shared.py
```

## Manual Installation

### macOS / Linux

```bash
cp scripts/statusline.py scripts/_statusline_shared.py ~/.claude/
chmod +x ~/.claude/statusline.py
```

> The statusline script loads its shared logic from the sibling
> `_statusline_shared.py` when the `context-stats` package is not installed,
> so both files must be copied together (the copy is kept byte-identical to
> the package module by the parity test suite).

## Configure Claude Code

Add to your Claude Code settings:

**File location:**

- macOS/Linux: `~/.claude/settings.json`
- Windows: `%USERPROFILE%\.claude\settings.json`

### pip Install

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-statusline"
  }
}
```

### Python (Manual Copy)

```json
{
  "statusLine": {
    "type": "command",
    "command": "python ~/.claude/statusline.py"
  }
}
```

Windows:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python %USERPROFILE%\\.claude\\statusline.py"
  }
}
```

## Requirements

Python 3.10+ is the only requirement. No additional system packages needed.

## Verify Installation

Test your statusline:

```bash
# If installed via pip
echo '{"model":{"display_name":"Test"}}' | claude-statusline

# Python script (manual copy)
echo '{"model":{"display_name":"Test"}}' | python3 ~/.claude/statusline.py

# Windows (Python)
echo {"model":{"display_name":"Test"}} | python %USERPROFILE%\.claude\statusline.py
```

You should see output like: `[Test] directory`

Restart Claude Code to see the status line.
