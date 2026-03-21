<div align="center">
  <img src="assets/logo/logo-full.svg" alt="cc-context-stats" width="320"/>

  <h3>Keep your model sharp. Ship with confidence.</h3>

  <p>Real-time model intelligence monitoring for Claude Code — know exactly when your model is at peak quality and when it's time for a fresh session.</p>

[![PyPI version](https://img.shields.io/pypi/v/cc-context-stats)](https://pypi.org/project/cc-context-stats/)
[![npm version](https://img.shields.io/npm/v/cc-context-stats)](https://www.npmjs.com/package/cc-context-stats)
[![PyPI Downloads](https://img.shields.io/pypi/dm/cc-context-stats)](https://pypi.org/project/cc-context-stats/)
[![npm Downloads](https://img.shields.io/npm/dm/cc-context-stats)](https://www.npmjs.com/package/cc-context-stats)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

**Always use Claude at its best** — monitor model intelligence in real-time so you know exactly when quality starts to drop.

![Context Stats - Model Intelligence](images/1.10/1.10.0-model-intelligence.png)

## Why Context Stats?

Research shows that LLM quality degrades as the context window fills up — even the best models lose retrieval accuracy at longer contexts. But you can't see this happening. Context Stats makes it visible:

- **Model Intelligence (MI)** - A benchmark-calibrated score (1.000 → 0.000) that tracks how much quality has degraded, with per-model profiles for Opus, Sonnet, and Haiku
- **Know your zone** - See if you're in the Smart Zone, Dumb Zone, or Wrap Up Zone
- **Track context usage** - Real-time monitoring with live-updating ASCII graphs
- **Get early warnings** - Color-coded alerts tell you when to start a fresh session
- **Per-model awareness** - Opus retains quality longer than Sonnet, which degrades faster than Haiku. MI reflects this automatically

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

### Verify Installation

After installing via any method, verify that both the statusline and context-stats CLI are working:

```bash
curl -fsSL https://raw.githubusercontent.com/luongnv89/cc-context-stats/main/scripts/check-install.sh | bash
```

Or if you cloned the repo:

```bash
./scripts/check-install.sh
```

## Quick Start

### Status Line Integration

Add to `~/.claude/settings.json` (the command depends on how you installed):

**pip or npm install:**
```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-statusline"
  }
}
```

**Shell script install (`install.sh`):**
```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.sh"
  }
}
```

Restart Claude Code to see real-time model intelligence and context stats in your status bar.

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
- Model Intelligence degradation over time
- Your current zone status and MI score
- Remaining context percentage

Press `Ctrl+C` to exit.

### Graph Types

| Delta (default) | Cumulative |
|:---:|:---:|
| ![Delta](images/1.10/1.10-delta.png) | ![Cumulative](images/1.10/1.10-cumulative.png) |

## Context Stats CLI

```bash
context-stats                    # Live monitoring (default)
context-stats -w 5               # Custom refresh interval (5 seconds)
context-stats --no-watch         # Show once and exit
context-stats --type cumulative  # Show cumulative context usage
context-stats --type both        # Show both graphs
context-stats --type mi          # Model Intelligence over time
context-stats --type all         # Show all graphs including I/O and MI
context-stats <session_id>       # View specific session
context-stats explain            # Diagnostic dump (pipe JSON to stdin)
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
  Model Intelligence:  0.646  (Context pressure building, consider wrapping up)
    Context: 79% used

  Last Growth:         +2,500
  Input Tokens:        1,234
  Output Tokens:       567
  Lines Changed:       +45 / -12
  Total Cost:          $0.1234
  Model:               claude-sonnet-4-6
  Session Duration:    2h 29m
```

## Status Line

Colors change based on MI score and context utilization — green when the model is sharp, yellow as quality degrades:

| MI >= 0.90 (green) | MI < 0.90 (yellow) |
|:---:|:---:|
| ![Green](images/1.10/statusline-green.png) | ![Yellow](images/1.10/1.10-statusline.png) |

The status line shows at-a-glance metrics in your Claude Code interface:

| Component | Description                               |
| --------- | ----------------------------------------- |
| Model     | Current Claude model                      |
| Context   | Tokens used / remaining with color coding |
| Delta     | Token change since last update            |
| MI        | Model Intelligence score (per-model)      |
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
show_mi=false        # Show Model Intelligence score (disabled by default)
mi_curve_beta=0      # Use model-specific profile (0=auto, or set custom beta)

# Custom colors - named colors or hex (#rrggbb)
color_green=#7dcfff
color_red=#f7768e
color_yellow=bright_yellow
```

## Model Intelligence (MI)

MI estimates how well the model will perform at your current context fill level, calibrated from the [MRCR v2 8-needle](https://docs.anthropic.com/) long context retrieval benchmark. The score drops from 1.000 (fresh context) to 0.000 (full context), with model-specific degradation rates:

| Model | Beta | MI at 50% | MI at 75% | When to worry |
|-------|------|-----------|-----------|---------------|
| Opus  | 1.8  | 0.713     | 0.404     | ~60% used     |
| Sonnet| 1.5  | 0.646     | 0.350     | ~50% used     |
| Haiku | 1.2  | 0.565     | 0.292     | ~45% used     |

The model is auto-detected from your session. See [Model Intelligence docs](docs/MODEL_INTELLIGENCE.md) for the full formula and benchmark data.

## How It Works

Context Stats hooks into Claude Code's status line feature to track token usage across your sessions. The Python and Node.js statusline scripts write state data to local CSV files, which the context-stats CLI reads to render live graphs. Data is stored locally in `~/.claude/statusline/` and never sent anywhere.

## Documentation

- [Installation Guide](docs/installation.md) - Platform-specific setup (shell, pip, npm)
- [Context Stats Guide](docs/context-stats.md) - Detailed CLI usage guide
- [Configuration Options](docs/configuration.md) - All settings explained
- [Available Scripts](docs/scripts.md) - Script variants and features
- [Model Intelligence](docs/MODEL_INTELLIGENCE.md) - MI formula, per-model profiles, benchmark data
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
