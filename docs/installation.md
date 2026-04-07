# Installation Guide

## Quick Install

### Python (pip) — Recommended

```bash
pip install cc-context-stats
```

Or with uv:

```bash
uv pip install cc-context-stats
```

After installation, add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-statusline"
  }
}
```

### Install from Source

```bash
git clone https://github.com/luongnv89/cc-context-stats.git
cd cc-context-stats
pip install .
```

### Windows

```powershell
pip install cc-context-stats
```

Or manually copy the script:

```powershell
git clone https://github.com/luongnv89/cc-context-stats.git
copy cc-context-stats\scripts\statusline.py %USERPROFILE%\.claude\statusline.py
```

## Manual Installation

### macOS / Linux

```bash
cp scripts/statusline.py ~/.claude/statusline.py
chmod +x ~/.claude/statusline.py
```

### Context Stats CLI (Optional)

```bash
cp scripts/context-stats.sh ~/.local/bin/context-stats
chmod +x ~/.local/bin/context-stats
```

Ensure `~/.local/bin` is in your PATH:

```bash
# For zsh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# For bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

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

Python 3.9+ is the only requirement. No additional system packages needed.

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
