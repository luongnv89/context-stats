<div align="center">
  <img src="assets/logo/logo-full.svg" alt="cc-context-stats" width="320"/>

  <h3>Know your zone. Ship with confidence.</h3>

  <p>Real-time context monitoring for Claude Code — so you always know when you're sharp and when to wrap up.</p>

[![PyPI version](https://badge.fury.io/py/cc-context-stats.svg)](https://pypi.org/project/cc-context-stats/)
[![npm version](https://badge.fury.io/js/cc-context-stats.svg)](https://www.npmjs.com/package/cc-context-stats)
[![PyPI Downloads](https://img.shields.io/pypi/dm/cc-context-stats)](https://pypi.org/project/cc-context-stats/)
[![npm Downloads](https://img.shields.io/npm/dm/cc-context-stats)](https://www.npmjs.com/package/cc-context-stats)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

**Never run out of context unexpectedly** - monitor your session context in real-time.

![Context Stats](images/v1.6.1.png)

## Why Context Stats?

When working with Claude Code on complex tasks, you can easily burn through your context window without realizing it. As your context fills up, Claude's performance degrades - this is what Dex Horthy calls the "dumb zone". Context Stats helps you:

- **Know your zone** - See if you're in the Smart Zone, Dumb Zone, or Wrap Up Zone
- **Track context usage** - Real-time monitoring with live-updating graphs
- **Get early warnings** - Color-coded status alerts you before performance degrades
- **Make informed decisions** - Know when to start a fresh session

## Context Zones

| Zone                | Context Used | Status   | What It Means                                 |
| ------------------- | ------------ | -------- | --------------------------------------------- |
| 🟢 **Smart Zone**   | < 40%        | Optimal  | Claude is performing at its best              |
| 🟡 **Dumb Zone**    | 40-80%       | Degraded | Context getting full, Claude may miss details |
| 🔴 **Wrap Up Zone** | > 80%        | Critical | Better to wrap up and start a new session     |

## Installation

### Shell Script

For the quickest setup:

```bash
curl -fsSL https://raw.githubusercontent.com/luongnv89/cc-context-stats/main/install.sh | bash
```

### NPM

```bash
npm install -g cc-context-stats
```

Or with yarn:

```bash
yarn global add cc-context-stats
```

### Python

```bash
pip install cc-context-stats
```

Or with uv:

```bash
uv pip install cc-context-stats
```

## Quick Start

### Status Line Integration

Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-statusline"
  }
}
```

Restart Claude Code to see real-time token stats in your status bar.

### Real-Time Monitoring

Get your session ID from the status line (the last part after the pipe `|`), then run:

```bash
context-stats <session_id>
```

For example:

```bash
context-stats abc123def-456-789
```

This opens a live dashboard that refreshes every 2 seconds, showing:

- Your current project and session
- Context growth per interaction graph
- Your current zone status
- Remaining context percentage

Press `Ctrl+C` to exit.

## Context Stats CLI

```bash
context-stats                    # Live monitoring (default)
context-stats -w 5               # Custom refresh interval (5 seconds)
context-stats --no-watch         # Show once and exit
context-stats --type cumulative  # Show cumulative context usage
context-stats --type both        # Show both graphs
context-stats --type all         # Show all graphs including I/O
context-stats <session_id>       # View specific session
context-stats --version          # Show version
```

### Output Example

```
Context Stats (my-project • abc123def)

Context Growth Per Interaction
Max: 4,787  Min: 0  Points: 254
...graph...

Session Summary
----------------------------------------------------------------------------
  Context Remaining:   43,038/200,000 (21%)
  >>> DUMB ZONE <<< (You are in the dumb zone - Dex Horthy says so)

  Last Growth:         +2,500
  Input Tokens:        1,234
  Output Tokens:       567
  Lines Changed:       +45 / -12
  Total Cost:          $0.1234
  Model:               claude-sonnet-4-20250514
  Session Duration:    2h 29m
```

## Status Line

![Status Line](images/statusline-detail.png)

The status line shows at-a-glance metrics in your Claude Code interface:

| Component | Description                               |
| --------- | ----------------------------------------- |
| Model     | Current Claude model                      |
| Context   | Tokens used / remaining with color coding |
| Delta     | Token change since last update            |
| Git       | Branch name and uncommitted changes       |
| Session   | Session ID for correlation                |

## Configuration

Create `~/.claude/statusline.conf`:

```bash
token_detail=true    # Show exact token counts (vs abbreviated like "12.5k")
show_delta=true      # Show token delta in status line
show_session=true    # Show session ID
autocompact=true     # Show autocompact buffer indicator
reduced_motion=false # Disable animations for accessibility
```

## How It Works

Context Stats hooks into Claude Code's status line feature to track token usage across your sessions. The Python and Node.js statusline scripts write state data to local CSV files, which the context-stats CLI reads to render live graphs. Data is stored locally in `~/.claude/statusline/` and never sent anywhere.

## Documentation

- [Installation Guide](docs/installation.md) - Platform-specific setup (shell, pip, npm)
- [Context Stats Guide](docs/context-stats.md) - Detailed CLI usage guide
- [Configuration Options](docs/configuration.md) - All settings explained
- [Available Scripts](docs/scripts.md) - Script variants and features
- [Architecture](docs/ARCHITECTURE.md) - System design and components
- [CSV Format](docs/CSV_FORMAT.md) - State file field specification
- [Development](docs/DEVELOPMENT.md) - Dev setup, testing, and debugging
- [Deployment](docs/DEPLOYMENT.md) - Publishing and release process
- [Troubleshooting](docs/troubleshooting.md) - Common issues and solutions
- [Changelog](CHANGELOG.md) - Version history

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on the development setup, branching strategy, and PR process.

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).

## Migration from cc-statusline

If you were using the previous `cc-statusline` package:

```bash
pip uninstall cc-statusline
pip install cc-context-stats
```

The `claude-statusline` command still works. The main change is `token-graph` is now `context-stats`.

## Related

- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)
- [Blog: Building this project](https://medium.com/@luongnv89/closing-the-gap-between-mvp-and-production-with-feature-dev-an-official-plugin-from-anthropic-444e2f00a0ad)

## License

MIT
