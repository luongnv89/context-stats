# Installation Guide

## Quick Install

### One-Line Install (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/luongnv89/cc-context-stats/main/install.sh | bash
```

This downloads and runs the installer directly from GitHub. It installs the **full** statusline script and the `context-stats` CLI tool.

### NPM (Recommended for Node.js users)

```bash
npm install -g cc-context-stats
```

Or with yarn:

```bash
yarn global add cc-context-stats
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

### Python (Recommended for Python users)

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
./install.sh
```

The installer will:

1. Install the statusline script to `~/.claude/`
2. Install `context-stats` CLI tool to `~/.local/bin/`
3. Create default configuration at `~/.claude/statusline.conf`
4. Update `~/.claude/settings.json`

### Windows

Use the Python or Node.js version (no `jq` required):

```powershell
# Python (via pip)
pip install cc-context-stats

# Or manually copy the script
git clone https://github.com/luongnv89/cc-context-stats.git
copy cc-context-stats\scripts\statusline.py %USERPROFILE%\.claude\statusline.py
```

Or with Node.js:

```powershell
# Node.js (via npm)
npm install -g cc-context-stats

# Or manually copy the script
copy cc-context-stats\scripts\statusline.js %USERPROFILE%\.claude\statusline.js
```

## Manual Installation

### macOS / Linux

```bash
cp scripts/statusline-full.sh ~/.claude/statusline.sh
chmod +x ~/.claude/statusline.sh
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

### pip / npm Install

If you installed via `pip install cc-context-stats` or `npm install -g cc-context-stats`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-statusline"
  }
}
```

### Bash (macOS/Linux)

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.sh"
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

### Node.js (Manual Copy)

```json
{
  "statusLine": {
    "type": "command",
    "command": "node ~/.claude/statusline.js"
  }
}
```

Windows:

```json
{
  "statusLine": {
    "type": "command",
    "command": "node %USERPROFILE%\\.claude\\statusline.js"
  }
}
```

## Requirements

### macOS

```bash
brew install jq   # Only needed for bash scripts
```

### Linux (Debian/Ubuntu)

```bash
sudo apt install jq   # Only needed for bash scripts
```

### Linux (Fedora/RHEL)

```bash
sudo dnf install jq   # Only needed for bash scripts
```

### Windows

No additional requirements for Python/Node.js scripts (via pip or npm).

For bash scripts via WSL:

```bash
sudo apt install jq
```

## Verify Installation

Test your statusline:

```bash
# If installed via pip or npm
echo '{"model":{"display_name":"Test"}}' | claude-statusline

# Bash script (macOS/Linux)
echo '{"model":{"display_name":"Test"}}' | ~/.claude/statusline.sh

# Python script (manual copy)
echo '{"model":{"display_name":"Test"}}' | python3 ~/.claude/statusline.py

# Node.js script (manual copy)
echo '{"model":{"display_name":"Test"}}' | node ~/.claude/statusline.js

# Windows (Python)
echo {"model":{"display_name":"Test"}} | python %USERPROFILE%\.claude\statusline.py
```

You should see output like: `[Test] directory`

Restart Claude Code to see the status line.
