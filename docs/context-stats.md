# Context Stats

Real-time context monitoring for Claude Code sessions. Know when you're in the Smart Zone, Dumb Zone, or Wrap Up Zone.

## Context Zones

Context Stats tracks your context usage and warns you as performance degrades:

| Zone                | Context Used | Status   | Message                                         |
| ------------------- | ------------ | -------- | ----------------------------------------------- |
| 🟢 **Smart Zone**   | < 40%        | Optimal  | "You are in the smart zone"                     |
| 🟡 **Dumb Zone**    | 40-80%       | Degraded | "You are in the dumb zone - Dex Horthy says so" |
| 🔴 **Wrap Up Zone** | > 80%        | Critical | "Better to wrap up and start a new session"     |

## Usage

By default, `context-stats` runs in live monitoring mode:

```bash
# Live monitoring (default, refreshes every 2s)
context-stats

# Custom refresh interval
context-stats -w 5

# Show once and exit
context-stats --no-watch

# Show specific session
context-stats <session_id>
```

### Graph Types

```bash
context-stats --type delta       # Context growth per interaction (default)
context-stats --type cumulative  # Total context usage over time
context-stats --type both        # Show both graphs
context-stats --type io          # Input/output token breakdown
context-stats --type cache       # Cache creation/read tokens over time
context-stats --type mi          # Model Intelligence over time
context-stats --type all         # Show all graphs including I/O, cache, and MI
```

### Diagnostic Dump

The `explain` command shows how cc-context-stats interprets Claude Code's JSON context. Pipe any session JSON to stdin:

```bash
echo '{"model":{"display_name":"Opus"},...}' | context-stats explain
echo '{"model":{"display_name":"Opus"},...}' | context-stats explain --no-color
```

Output includes model info, workspace, context window breakdown with derived values (free tokens, autocompact buffer), cost, session metadata, vim/agent extensions, active config, and raw JSON.

## Output

```
Context Stats (my-project • abc123def)

Context Growth Per Interaction
Max: 4,787  Min: 0  Points: 254

     4,787 │                                        ●
           │                                    ●   ▒
           │     ●●         ●                   ▒   ░
           │     ●                              ░   ░
     2,052 │     ░ ●    ● ●                     ░   ░ ●
           │     ░        ▒ ●  ● ●   ●  ●    ● ●░   ░ ▒   ●●
           │●●●●●●●●●●●●●●●●●●●●●●●●●●● ●●●●●●●●●●●●●●●●●●●●●●
         0 │●●●●●░▒●●●●▒▒●●▒░●●░▒▒▒▒▒●●●▒●▒●●▒●▒░●●▒●░●●▒●▒▒●▒
           └─────────────────────────────────────────────────
           10:40                11:29                12:01

Session Summary
----------------------------------------------------------------------------
  Context Remaining:   43,038/200,000 (21%)
  >>> DUMB ZONE <<< (You are in the dumb zone - Dex Horthy says so)
  Model Intelligence:  0.646  (Context pressure building, consider wrapping up)
    Context: 79% used

  Last Growth:         +2,500
  Input Tokens:        59,015
  Output Tokens:       43,429
  Cache Creation:      10,000
  Cache Read:          20,000
  Total Cost:          $0.1234
  Model:               claude-sonnet-4-6
  Session Duration:    2h 29m

Powered by cc-context-stats v1.15.1 - https://github.com/luongnv89/cc-context-stats
```

## Features

- **Live Monitoring**: Automatic refresh every 2 seconds (configurable)
- **Zone Awareness**: Color-coded status based on context usage
- **Model Intelligence (MI)**: Benchmark-calibrated score with per-model profiles (Opus/Sonnet/Haiku) showing how much the model has degraded
- **MI Over Time Graph**: `--type mi` shows MI degradation trajectory across the session
- **Project Display**: Shows project name and session ID
- **ASCII Graphs**: Smooth area charts with gradient fills
- **Minimal Output**: Clean summary with just the essential info

## Graph Symbols

| Symbol | Meaning                 |
| ------ | ----------------------- |
| `●`    | Trend line              |
| `▒`    | Medium fill (near line) |
| `░`    | Light fill (area below) |
| `│`    | Y-axis                  |
| `└─`   | X-axis                  |

## Watch Mode

By default, context-stats runs in watch mode. Press `Ctrl+C` to exit.

Features:

- **Flicker-free updates**: Uses cursor repositioning for smooth redraws
- **Live timestamp**: Shows refresh indicator in header
- **Hidden cursor**: Clean display without cursor blinking
- **Auto-adapt**: Responds to terminal size changes

To disable watch mode and show graphs once:

```bash
context-stats --no-watch
```

## Data Source

Reads from `~/.claude/statusline/statusline.<session_id>.state` files, automatically created by the status line script.

## CLI Reference

```
context-stats [session_id] [options]

ARGUMENTS:
    session_id    Optional session ID. If not provided, uses the latest session.

COMMANDS:
    export        Export session stats as a markdown report
                   context-stats export [session_id] [--output FILE]

OPTIONS:
    --type <type>  Graph type to display:
                   - delta: Context growth per interaction (default)
                   - cumulative: Total context usage over time
                   - io: Input/output tokens over time
                   - cache: Cache creation/read tokens over time
                            Includes a Cache TTL countdown (5m) based on last cache write
                   - mi: Model Intelligence over time
                   - both: Show cumulative and delta graphs
                   - all: Show all graphs including I/O, cache, and MI
    -w [interval]  Set refresh interval in seconds (default: 2)
    --no-watch     Show graphs once and exit (disable live monitoring)
    --no-color     Disable color output
    --help         Show help message
```

The export report includes a summary table, timestamp-based Mermaid trend charts, a zone distribution pie chart, and a final context composition pie chart.
Each chart includes a short explanation so the reader knows what to look for.
The report begins with a copyable `context-stats export <session_id> --output report.md` command and an executive snapshot that folds the header metadata into one compact table so the report can be regenerated and scanned quickly.
It also adds a Key Takeaways section and samples the cache activity line chart every 10 minutes when cache data is present.
The charts use distinct colors and a manual legend because Mermaid xychart does not render a legend automatically.
