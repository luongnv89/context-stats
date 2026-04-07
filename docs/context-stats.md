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

The CLI uses an explicit action-based pattern: `context-stats <session_id> <action> [options]`

By default, `context-stats` runs in live monitoring mode:

```bash
# Live monitoring (default, refreshes every 2s)
context-stats <session_id> graph

# Custom refresh interval
context-stats <session_id> graph -w 5

# Show once and exit
context-stats <session_id> graph --no-watch
```

### Graph Types

```bash
context-stats <session_id> graph --type delta       # Context growth per interaction (default)
context-stats <session_id> graph --type cumulative  # Total context usage over time
context-stats <session_id> graph --type both        # Show both graphs
context-stats <session_id> graph --type io          # Input/output token breakdown
context-stats <session_id> graph --type cache       # Cache creation/read tokens over time
context-stats <session_id> graph --type mi          # Model Intelligence over time
context-stats <session_id> graph --type all         # Show all graphs including I/O, cache, and MI
```

### Diagnostic Dump

The `explain` action shows how cc-context-stats interprets Claude Code's JSON context. Pipe any session JSON to stdin:

```bash
echo '{"model":{"display_name":"Opus"},...}' | context-stats explain
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

Powered by cc-context-stats v1.16.1 - https://github.com/luongnv89/cc-context-stats
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
context-stats <session_id> graph --no-watch
```

## Data Source

Reads from `~/.claude/statusline/statusline.<session_id>.state` files, automatically created by the status line script.

## CLI Reference

```
context-stats <session_id> <action> [options]

ARGUMENTS:
    session_id    Required. The session ID to operate on.
    action        Required. The action to perform: graph, export, or explain.

ACTIONS:
    graph         Show live ASCII graphs of context usage
    export        Export session stats as a markdown report
    explain       Diagnostic dump of Claude Code's JSON context (reads from stdin)

GRAPH OPTIONS:
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

EXPORT OPTIONS:
    --output FILE  Output file path (default: context-stats-<session>.md)

GLOBAL OPTIONS:
    --no-color     Disable color output
    --help         Show help message
    --version, -V  Show version and exit

EXAMPLES:
    context-stats abc123def graph
    context-stats abc123def graph --type cumulative
    context-stats abc123def graph -w 5
    context-stats abc123def export --output report.md
    echo '{"model":...}' | context-stats explain
```

The export report includes a summary table, timestamp-based Mermaid trend charts, a zone distribution pie chart, and a final context composition pie chart.
Each chart includes a short explanation so the reader knows what to look for.
The report begins with a copyable `context-stats <session_id> export --output report.md` command and an executive snapshot that folds the header metadata into one compact table so the report can be regenerated and scanned quickly.
It also adds a Key Takeaways section and samples the cache activity line chart every 10 minutes when cache data is present.
The charts use distinct colors and a manual legend because Mermaid xychart does not render a legend automatically.
