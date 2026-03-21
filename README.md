<div align="center">
  <img src="assets/logo/logo-full.svg" alt="cc-context-stats" width="320"/>

  <h1>Stop Shipping from a Half-Blind Model</h1>

  <p><strong>Real-time model intelligence monitoring for Claude Code.</strong><br/>Know exactly when your model is at peak quality — and when it's time for a fresh session.</p>

[![PyPI version](https://img.shields.io/pypi/v/cc-context-stats)](https://pypi.org/project/cc-context-stats/)
[![npm version](https://img.shields.io/npm/v/cc-context-stats)](https://www.npmjs.com/package/cc-context-stats)
[![PyPI Downloads](https://img.shields.io/pypi/dm/cc-context-stats)](https://pypi.org/project/cc-context-stats/)
[![npm Downloads](https://img.shields.io/npm/dm/cc-context-stats)](https://www.npmjs.com/package/cc-context-stats)
[![GitHub stars](https://img.shields.io/github/stars/luongnv89/cc-context-stats)](https://github.com/luongnv89/cc-context-stats)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[**Get Started in 60 Seconds →**](#installation)

</div>

---

![Context Stats - Model Intelligence](images/1.10/1.10.0-model-intelligence.png)

## The Problem

You're deep into a Claude Code session — refactoring, debugging, shipping. Everything feels fine. But behind the scenes:

- **Your model is getting dumber and you can't see it.** Research shows LLM retrieval accuracy drops as the context window fills. Claude starts missing details, hallucinating references, and losing track of your codebase — silently.
- **You don't know when to start fresh.** Is 50% context usage safe? 70%? It depends on the model. Opus holds quality longer than Sonnet, which degrades faster than Haiku. Without data, you're guessing.
- **Wasted sessions cost real money.** Pushing through a degraded context means more back-and-forth, more corrections, more tokens burned on worse output. You pay more for less.

You can't fix what you can't measure.

## How cc-context-stats Fixes This

cc-context-stats gives you a **Model Intelligence (MI) score** — a single number from 1.000 to 0.000 that tells you how sharp your model is right now, calibrated from Anthropic's [MRCR v2 8-needle](https://docs.anthropic.com/) retrieval benchmark.

- **One glance, full picture** — MI score lives in your Claude Code status bar. Green means sharp. Yellow means degrading. Red means stop and start fresh.
- **Per-model awareness** — Opus (beta=1.8) retains quality longest. Sonnet (beta=1.5) is moderate. Haiku (beta=1.2) degrades earliest. MI reflects your actual model automatically.
- **Live dashboard** — ASCII graphs track context growth, MI degradation, and token I/O over time. Watch quality erode in real-time so you can make informed decisions.
- **Zero config, zero dependencies** — Install in one command. Works with pip, npm, or a shell script. No API keys, no network calls. All data stays local.
- **Context zones (P/C/D/X/Z)** — Five-state indicators tell you where you stand:

| Zone | Letter | Color | What It Means |
| --- | --- | --- | --- |
| **Planning** | P | Green | Safe to plan and code |
| **Code-only** | C | Yellow | Avoid starting new plans |
| **Dump zone** | D | Orange | Quality declining — finish up |
| **Hard limit** | X | Dark red | Start a new session now |
| **Dead zone** | Z | Gray | Nothing productive here |

[**Install and See Your MI Score →**](#installation)

## How It Works

1. **Install** — One command: `pip install cc-context-stats` or `npm install -g cc-context-stats`
2. **Configure** — Add the statusline command to `~/.claude/settings.json` (two lines of JSON)
3. **Restart Claude Code** — MI score and context stats appear in your status bar immediately
4. **Monitor** — Run `context-stats <session_id>` for a live dashboard with graphs, zone status, and session summary

| Status Bar (green — model is sharp) | Status Bar (yellow — quality degrading) |
|:---:|:---:|
| ![Green](images/1.10/statusline-green.png) | ![Yellow](images/1.10/1.10-statusline.png) |

| Delta Graph | Cumulative Graph |
|:---:|:---:|
| ![Delta](images/1.10/1.10-delta.png) | ![Cumulative](images/1.10/1.10-cumulative.png) |

[**See Full CLI Options →**](#context-stats-cli)

## Model Intelligence — The Science

MI isn't a guess. It's derived from `MI(u) = max(0, 1 - u^beta)` where `u` is context utilization and `beta` is a model-specific degradation rate calibrated against Anthropic's MRCR v2 8-needle long-context retrieval benchmark.

| Model | Beta | MI at 50% Context | MI at 75% Context | When to Worry |
|-------|------|-----------|-----------|---------------|
| Opus  | 1.8  | 0.713     | 0.404     | ~60% used     |
| Sonnet| 1.5  | 0.646     | 0.350     | ~50% used     |
| Haiku | 1.2  | 0.565     | 0.292     | ~45% used     |

The model is auto-detected from your session. See [Model Intelligence docs](docs/MODEL_INTELLIGENCE.md) for the full formula and benchmark data.

## Installation

### Shell Script (quickest)

```bash
curl -fsSL https://raw.githubusercontent.com/luongnv89/cc-context-stats/main/install.sh | bash
```

### npm

```bash
npm install -g cc-context-stats
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

```bash
curl -fsSL https://raw.githubusercontent.com/luongnv89/cc-context-stats/main/scripts/check-install.sh | bash
```

### Quick Start

Add to `~/.claude/settings.json`:

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

Restart Claude Code. MI score and context stats appear in your status bar immediately.

### Real-Time Dashboard

Get your session ID from the status line (the last part after the pipe `|`), then:

```bash
context-stats <session_id>
```

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

[**See All Graph Types and Options →**](#context-stats-cli)

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

## FAQ

**Is it free?**
Yes. MIT licensed, zero dependencies, free forever. [See the license](LICENSE).

**Does it send my data anywhere?**
No. All data stays local in `~/.claude/statusline/`. No network requests, no telemetry, no API keys required.

**Is it actively maintained?**
Very. 11 releases since January 2025, with MI per-model profiles, configurable colors, state rotation, and cross-implementation parity tests all shipped in the last few months.

**How does it compare to just watching the context counter?**
The raw context counter tells you how full the window is. MI tells you how much quality you've lost — which depends on the model. 50% context on Opus (MI: 0.713) is fine. 50% on Haiku (MI: 0.565) means you should start wrapping up. cc-context-stats gives you the nuance.

**Can I use it with Opus, Sonnet, and Haiku?**
Yes. MI auto-detects your model and applies the correct degradation curve. Each model has a calibrated beta value from benchmark data.

**What runtimes does it support?**
Python (pip), Node.js (npm), or pure Bash. The statusline scripts are implemented in all three languages so you can use whichever runtime you have available.

**How do I customize colors?**
Create `~/.claude/statusline.conf` with named colors or hex codes. See [Configuration docs](docs/configuration.md) for all options.

## Start Shipping with Confidence

You wouldn't deploy without monitoring your servers. Don't code without monitoring your model.

cc-context-stats is MIT licensed, has zero dependencies, installs in one command, and works with any Claude Code setup. If you don't like it, `pip uninstall cc-context-stats` and it's gone.

[**Install cc-context-stats Now →**](#installation)

---

<details>
<summary><strong>Status Line Components</strong></summary>

The status line shows at-a-glance metrics in your Claude Code interface:

| Component | Description                               |
| --------- | ----------------------------------------- |
| Model     | Current Claude model                      |
| Context   | Tokens used / remaining with color coding |
| Delta     | Token change since last update            |
| MI        | Model Intelligence score (per-model)      |
| Git       | Branch name and uncommitted changes       |
| Session   | Session ID for correlation                |

Colors change based on MI score and context utilization — green when the model is sharp, yellow as quality degrades.

</details>

<details>
<summary><strong>Configuration</strong></summary>

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

</details>

<details>
<summary><strong>Migration from cc-statusline</strong></summary>

If you were using the previous `cc-statusline` package:

```bash
pip uninstall cc-statusline
pip install cc-context-stats
```

The `claude-statusline` command still works. The main change is `token-graph` is now `context-stats`.

</details>

<details>
<summary><strong>Documentation</strong></summary>

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

</details>

<details>
<summary><strong>Contributing</strong></summary>

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on the development setup, branching strategy, and PR process.

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).

</details>

<details>
<summary><strong>How It Works (Architecture)</strong></summary>

Context Stats hooks into Claude Code's status line feature to track token usage across your sessions. The Python and Node.js statusline scripts write state data to local CSV files, which the context-stats CLI reads to render live graphs. Data is stored locally in `~/.claude/statusline/` and never sent anywhere.

The statusline is implemented in three languages (Bash, Python, Node.js) so you can choose whichever runtime you have available. Claude Code invokes the statusline script via stdin JSON pipe — any implementation that reads JSON from stdin and writes formatted text to stdout works.

</details>

## Related

- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)
- [Blog: Building this project](https://medium.com/@luongnv89/closing-the-gap-between-mvp-and-production-with-feature-dev-an-official-plugin-from-anthropic-444e2f00a0ad)

## License

MIT
