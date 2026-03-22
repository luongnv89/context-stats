# Troubleshooting

## Common Issues

### Status line not appearing

**macOS/Linux:**

1. Check script is executable:

   ```bash
   chmod +x ~/.claude/statusline.sh
   ```

2. Test the script:

   ```bash
   echo '{"model":{"display_name":"Test"}}' | ~/.claude/statusline.sh
   ```

3. Verify settings.json configuration:

   ```bash
   cat ~/.claude/settings.json
   ```

**pip/npm install:**

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

### jq not found

The bash scripts require `jq` for JSON parsing. Python and Node.js scripts do **not** need `jq`.

**macOS:**

```bash
brew install jq
```

**Linux (Debian/Ubuntu):**

```bash
sudo apt install jq
```

**Linux (Fedora/RHEL):**

```bash
sudo dnf install jq
```

Alternatively, use the Python or Node.js version which don't require `jq`.

### context-stats command not found

**If installed via pip or npm:**

1. Verify installation:

   ```bash
   which context-stats
   ```

2. Reinstall if missing:

   ```bash
   pip install cc-context-stats   # or: npm install -g cc-context-stats
   ```

**If installed via shell installer:**

1. Verify installation:

   ```bash
   ls -la ~/.local/bin/context-stats
   ```

2. Check PATH:

   ```bash
   echo $PATH | grep -q "$HOME/.local/bin" && echo "In PATH" || echo "Not in PATH"
   ```

3. Add to PATH if needed:

   ```bash
   # zsh
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
   source ~/.zshrc

   # bash
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
   source ~/.bashrc
   ```

### pip install fails

1. Ensure Python 3.9+:

   ```bash
   python3 --version
   ```

2. Try with `--user` flag:

   ```bash
   pip install --user cc-context-stats
   ```

3. Or use `uv`:

   ```bash
   uv pip install cc-context-stats
   ```

### npm install fails

1. Ensure Node.js 18+:

   ```bash
   node --version
   ```

2. Try with sudo (Linux/macOS):

   ```bash
   sudo npm install -g cc-context-stats
   ```

3. Or fix npm permissions:

   ```bash
   mkdir -p ~/.npm-global
   npm config set prefix '~/.npm-global'
   echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> ~/.zshrc
   source ~/.zshrc
   npm install -g cc-context-stats
   ```

### No token graph data

Token history requires:

1. Python or Node.js statusline script (bash scripts do **not** write state files)
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

# Test each script
cat /tmp/test-input.json | ~/.claude/statusline.sh
cat /tmp/test-input.json | python3 ~/.claude/statusline.py
cat /tmp/test-input.json | node ~/.claude/statusline.js

# Test pip/npm installed version
cat /tmp/test-input.json | claude-statusline
```

### Check state files

```bash
# View state file content
cat ~/.claude/statusline/statusline.*.state

# Watch state file updates
watch -n 1 'tail -5 ~/.claude/statusline/statusline.*.state'
```

## Getting Help

- Check [existing issues](https://github.com/luongnv89/cc-context-stats/issues)
- Open a new issue with:
  - Operating system
  - Shell type (bash/zsh)
  - Installation method (pip, npm, shell installer, manual)
  - Script version being used
  - Error messages or unexpected behavior
