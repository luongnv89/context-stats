# Configuration

The configuration file `~/.claude/statusline.conf` is automatically created with default settings on first run. The auto-generated file is aligned with [`examples/statusline.conf`](../examples/statusline.conf), which serves as the canonical reference for all available settings.

To start from the fully-documented example:

```bash
cp examples/statusline.conf ~/.claude/statusline.conf
```

If `~/.claude/statusline.conf` already exists, it is never overwritten by auto-generation.

Windows location: `%USERPROFILE%\.claude\statusline.conf`

## Settings

```bash
# Autocompact setting - sync with Claude Code's /config
autocompact=false  # (default) Autocompact disabled
autocompact=true   # Enable when autocompact is on via /config

# Token display format
token_detail=true  # (default) Show exact token count: 64,000 free
token_detail=false # Show abbreviated tokens: 64.0k free

# Show token delta since last refresh
show_delta=true    # (default) Show delta like [+2,500]
show_delta=false   # Disable delta display

# Show session_id in status line
show_session=true  # (default) Show session ID
show_session=false # Hide session ID

# Show cumulative session cost in USD (reported by Claude Code)
show_cost=true     # (default) Show session cost like $0.42
show_cost=false    # Hide session cost

# Disable rotating text animations
reduced_motion=false  # (default) Animations enabled
reduced_motion=true   # Disable animations for accessibility

# Model Intelligence (MI) score display
show_mi=false  # (default) MI score hidden
show_mi=true   # Enable MI display in status line and summary

# MI curve beta override
mi_curve_beta=0    # (default) Use model-specific profile (opus=1.8, sonnet=1.5, haiku=1.2)
mi_curve_beta=1.5  # Override with custom beta for all models
```

## Status Line Components

```
[Opus 4.6] my-project | main [3] | 64,000 free (32.0%) [+2,500] MI:0.918 [AC:45k] session_id
```

| Component     | Description              | Default Color | Config Key             |
| ------------- | ------------------------ | ------------- | ---------------------- |
| `[Opus 4.6]`  | Current AI model         | Dim           | `color_model`          |
| `my-project`  | Current directory        | Cyan          | `color_project_name`   |
| `main`        | Git branch               | Green         | `color_branch_name`    |
| `[3]`         | Uncommitted changes      | Cyan          | `color_cyan`           |
| `64,000 free` | Available tokens         | Bold White    | `color_context_length` |
| `(32.0%)`     | Context usage percentage | -             | -                      |
| `42.5 tok/s`  | Model throughput         | Dim           | `color_tps`            |
| `[+2,500]`    | Token delta              | Dim           | `color_delta`          |
| `MI:0.918`    | Model Intelligence score | Yellow        | `color_mi_score`       |
| `$0.42`       | Cumulative session cost  | Dim           | `color_cost`           |
| `[AC:45k]`    | Autocompact buffer       | Dim           | -                      |
| `session_id`  | Current session          | Dim           | `color_session`        |

The five structural elements — model, tok/s, delta, cost, and session — default to
`color_separator` when their own key is not set, so they can be colored together
(via `color_separator`) or each given a distinct color.

The session cost is the cumulative total for the whole session as reported by
Claude Code (`cost.total_cost_usd`), shown even at `$0.00`. It is on by default;
set `show_cost=false` to hide it.

## Token Colors

Context availability is color-coded based on Model Intelligence (MI) score (not raw percentages):

| MI Score  | Color  | Meaning                   |
| --------- | ------ | ------------------------- |
| > 0.70    | Green  | Model is operating well   |
| 0.40–0.70 | Yellow | Context pressure building |
| < 0.40    | Red    | Significant degradation   |

When `color_context_length` is explicitly set, it overrides MI-based coloring.

## Model Intelligence Colors

MI score is color-coded based on degradation level:

| MI Score  | Color  | Meaning                                     |
| --------- | ------ | ------------------------------------------- |
| > 0.70    | Green  | Model is operating well                     |
| 0.40-0.70 | Yellow | Context pressure building, consider wrap up |
| < 0.40    | Red    | Significant degradation, start new session  |

MI uses per-model degradation profiles. Set `mi_curve_beta` to override the auto-detected profile.

## Autocompact Display

- `[AC:45k]` - Autocompact enabled, 45k tokens reserved
- `[AC:off]` - Autocompact disabled

## Token Display Formats

| Setting              | Display                          |
| -------------------- | -------------------------------- |
| `token_detail=true`  | `64,000 free (32.0%)` `[+2,500]` |
| `token_detail=false` | `64.0k free (32.0%)` `[+2.5k]`   |

## Token Delta

The `[+X,XXX]` indicator shows tokens consumed since last refresh:

- Only positive deltas are shown
- First run shows no delta (no baseline yet)
- Each session has its own state file to avoid conflicts

## Session ID

The session ID at the end helps:

- Identify sessions when running multiple Claude Code instances
- Correlate logs with specific sessions
- Debug session-specific issues

Double-click to select and copy. Set `show_session=false` to hide.

## Zone Threshold Overrides

Override the default zone indicator thresholds to customize when zone transitions occur.

### 1M-Class Models (context >= 500k tokens)

```bash
# Token counts for 1M models
zone_1m_plan_max=70000     # (default) Plan → Code boundary
zone_1m_code_max=100000    # (default) Code → Dump boundary
zone_1m_dump_max=250000    # (default) Dump → ExDump boundary
zone_1m_xdump_max=275000   # (default) ExDump → Dead boundary
```

### Standard Models (< 500k context)

```bash
# Ratios (0-1) for standard models
zone_std_dump_ratio=0.40   # (default) Dump zone starts at 40% utilization
zone_std_warn_buffer=30000 # (default) Warn 30k tokens before dump zone
zone_std_hard_limit=0.70   # (default) Hard limit at 70% utilization
zone_std_dead_ratio=0.75   # (default) Dead zone starts at 75% utilization
```

### Model Classification

```bash
# Context windows >= this threshold use the 1M thresholds
large_model_threshold=500000  # (default)
```

Invalid values (negative, non-numeric, ratios outside 0-1) are ignored with a warning to stderr, falling back to the defaults.

## Custom Colors

### Per-Property Colors

Override individual statusline elements with their own colors. These take precedence over the base color slots:

```bash
# Per-property color keys
color_context_length=bold_white   # Context remaining (most critical info)
color_project_name=cyan           # Which project you're in
color_branch_name=green           # Git branch at a glance
color_mi_score=yellow             # MI score
color_zone=default                # Zone indicator (uses zone color by default)
color_separator=dim               # tok/s, delta, cost, model, session (visual structure)

# Structural elements — each defaults to color_separator, override for distinct colors
color_tps=#6ED7D2                 # Model throughput (tok/s)
color_delta=#FFF8DC               # Token delta since last refresh
color_cost=#9ECE6A                # Session cost in USD
color_model=#C0C0C0               # Model name
color_session=#8B8682             # Session ID
```

**Fallback chain:** Per-property key → base color key → built-in default. For example, if `color_project_name` is not set, the `color_blue` value is used (if set), otherwise the built-in default (cyan).

### Base Color Slots

Override the base MI/context colors and legacy element colors:

```bash
# Base color slots (used for MI-based context coloring and as fallbacks)
color_green=#7dcfff       # MI score > 0.70
color_yellow=bright_yellow # MI score 0.40–0.70
color_red=#f7768e         # MI score < 0.40
color_blue=bright_blue    # Fallback for project name (if color_project_name not set)
color_magenta=#bb9af7     # Fallback for branch name (if color_branch_name not set)
color_cyan=bright_cyan    # Git change count
```

### Supported Color Values

**Named colors**: `black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`, `bright_black`, `bright_red`, `bright_green`, `bright_yellow`, `bright_blue`, `bright_magenta`, `bright_cyan`, `bright_white`, `bold_white`, `dim`

**Hex colors**: Any `#rrggbb` value (requires terminal with 24-bit color support)

Unrecognized color values are ignored with a warning to stderr. Omitted slots use defaults.

## Config File Format

The config file uses simple `key=value` syntax:

- No spaces around `=`
- Lines starting with `#` are comments
- Unrecognized keys are ignored
- Missing keys use defaults shown above
