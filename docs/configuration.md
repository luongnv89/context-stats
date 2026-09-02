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

# Show input/output token breakdown
show_io_tokens=true  # (default) Reserved for future use — read but not displayed
show_io_tokens=false # Same behavior; key is accepted for forward compatibility

# Show the associated PR number for the current branch
show_pr=true     # (default) Show PR number like #42 (requires the gh CLI)
show_pr=false    # Hide PR number

# Disable rotating text animations
reduced_motion=false  # (default) Animations enabled
reduced_motion=true   # Disable animations for accessibility

# Pacman-style icon reflecting the current context zone (Plan/Pricing/Code/Dump/ExDump/Dead)
show_pacman=true   # (default) Show icon next to the zone label
show_pacman=false  # Icon hidden

# Show cumulative session cost in USD (reported by Claude Code)
show_cost=true     # (default) Show session cost like $0.42
show_cost=false    # Hide session cost

# Show reasoning effort level next to the model name (reported by Claude Code)
show_effort=true   # (default) Show effort like Opus 4.6·high
show_effort=false  # Hide effort level

# Suppress the one-line "statusLine is not wired" startup hint (see below)
suppress_setup_hint=false  # (default) hint shown while statusLine is missing from settings.json
suppress_setup_hint=true   # never print the hint; same as CONTEXT_STATS_SUPPRESS_SETUP_HINT=1

# Model Intelligence (MI) score display
show_mi=false  # (default) MI score hidden
show_mi=true   # Enable MI display in status line and summary

# MI curve beta override
mi_curve_beta=0    # (default) Use model-specific profile (opus=1.8, sonnet=1.5, haiku=1.2)
mi_curve_beta=1.5  # Override with custom beta for all models

# Model throughput display (tokens per second)
show_tps=false      # (default) Throughput hidden
show_tps=true       # Show rolling tok/s like 42.5 tok/s
tps_precision=1     # (default) Decimal places for the value (0 -> "42", 1 -> "42.5")
tps_unit=tok/s      # (default) Unit label ("tok/s", or "tokens/s" to be explicit)
tps_window=5        # (default) Recent turns averaged for the rolling throughput

# Compaction detection thresholds (fractions strictly between 0 and 1)
compaction_drop_threshold=0.5  # (default) Context drop fraction that qualifies as /compact
compact_mi_warn_threshold=0.6  # (default) MI below this at compact time -> lossy warning
```

## Status Line Components

```
my-project | main [3] | #42 | 130,000 (65.0%)·Code·ᗤ | MI:0.849 | 42.5 tok/s | +2,500 | $0.42 | Opus 4.6·high | abc-123
```

| Component    | Description              | Default Color | Config Key             |
| ------------ | ------------------------ | ------------- | ---------------------- |
| `Opus 4.6`   | Current AI model         | Dim           | `color_model`          |
| `my-project` | Current directory        | Cyan          | `color_project_name`   |
| `main`       | Git branch               | Green         | `color_branch_name`    |
| `[3]`        | Uncommitted changes      | Cyan          | `color_cyan`           |
| `#42`        | PR number for the branch | Dim           | `color_separator`      |
| `130,000`    | Available tokens         | Bold White    | `color_context_length` |
| `(65.0%)`    | Context usage percentage | -             | -                      |
| `42.5 tok/s` | Model throughput         | Dim           | `color_tps`            |
| `+2,500`     | Token delta              | Dim           | `color_delta`          |
| `Code`       | Context zone             | Zone color    | `color_zone`           |
| `ᗤ`          | Pacman context-zone icon | Zone color    | `color_zone`           |
| `MI:0.849`   | Model Intelligence score | Yellow        | `color_mi_score`       |
| `$0.42`      | Cumulative session cost  | Dim           | `color_cost`           |
| `·high`      | Reasoning effort level   | Dim (model)   | `color_model`          |
| `abc-123`    | Current session          | Dim           | `color_session`        |

The five structural elements — model, tok/s, delta, cost, and session — default to
`color_separator` when their own key is not set, so they can be colored together
(via `color_separator`) or each given a distinct color. The PR number shares
`color_separator` as well.

The PR number is looked up with the GitHub CLI (`gh`) for the current branch and
cached briefly per branch, so the network round-trip happens at most once per
minute. It requires `gh` to be installed and authenticated; set `show_pr=false`
to hide it (on by default).

The session cost is the cumulative total for the whole session as reported by
Claude Code (`cost.total_cost_usd`), shown even at `$0.00`. It is on by default;
set `show_cost=false` to hide it.

The reasoning effort level is reported by Claude Code (`effort.level`, one of
`low`/`medium`/`high`/`xhigh`/`max`) and shown next to the model name, e.g.
`Opus 4.6·high`. It is on by default and hides automatically when Claude Code
reports no effort (e.g. models without an effort setting); set
`show_effort=false` to hide it. The effort label shares the model color
(`color_model`).

Related elements are grouped with a thin `·` separator instead of the `|`
used between groups: context usage, zone, and pacman icon form one group
(`64,000 free (32.0%)·Code·ᗤ`), and the model carries its effort suffix
(`Opus 4.6·high`). The `·` is unspaced to save horizontal room. A group is
kept together when the statusline wraps on a narrow terminal.

The pacman icon is a quick emotional cue for the current context zone,
shown next to the zone label. Each of the six zones maps to a distinct
glyph — `ᗧ` (Plan), `$` (Pricing), `ᗤ` (Code), `ᗣ` (Dump), `ᗢ` (ExDump),
`×` (Dead) — and shares the zone's traffic-light color (`color_zone`). It
is on by default; set `show_pacman=false` to hide it and keep the status
line more compact.

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

## Model Throughput (tok/s)

Set `show_tps=true` to display the model's generation speed, e.g. `42.5 tok/s`.
Speed is measured from the time Claude Code spent waiting for API responses
(`cost.total_api_duration_ms`), so it reflects pure model throughput and
excludes your idle time and tool execution.

The displayed value is a rolling, token-weighted average over the last
`tps_window` turns (default 5), not the raw per-turn speed — per-turn speed
swings wildly (a 3-token reply looks like 1.5 tok/s, a long answer like 80
tok/s), so the average is far steadier. Once established it persists across
turns that carry no new timing information.

```bash
show_tps=true       # enable the segment
tps_precision=1     # decimal places (0 -> "42", 1 -> "42.5", 2 -> "42.53")
tps_unit=tok/s      # unit label appended after the value
tps_window=5        # recent turns averaged; minimum 1
```

Like MI and delta, tok/s requires state-file I/O to track values across
refreshes.

## Compaction Detection

These thresholds tune how `/compact` events are detected and flagged in
graphs and reports:

- `compaction_drop_threshold=0.5` — a single-step context drop larger than
  this fraction qualifies as a compaction event (annotated with `▼`)
- `compact_mi_warn_threshold=0.6` — when compaction occurs while the MI score
  is below this value, the summary is flagged as potentially lossy

Both accept fractions strictly between 0 and 1; invalid values (negative,
non-numeric, outside 0-1) are ignored with a warning to stderr.

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
# Token counts for 1M models (keep plan_max < pricing_max < code_max)
zone_1m_plan_max=150000    # (default) Plan → Pricing boundary
zone_pricing_max=200000    # (default) Pricing → Code boundary (cost warning band)
zone_1m_code_max=250000    # (default) Code → Dump boundary
zone_1m_dump_max=400000    # (default) Dump → ExDump boundary
zone_1m_xdump_max=450000   # (default) ExDump → Dead boundary
```

The **Pricing** zone appears between Plan and Code when the context used
exceeds `zone_1m_plan_max` (150k). It is shown in **amber** with a `$` icon
and a cost-aware recommendation (`Pricing tier increases — consider
/compact`) because long sessions are more expensive even when cached. If
`zone_pricing_max <= zone_1m_plan_max` the band never fires; if it is `>=`
`zone_1m_code_max`, the Code zone becomes unreachable — keep
`plan_max < pricing_max < code_max`.

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

## Setup Hint

`pip install context-stats` installs the commands but cannot wire `statusLine`
into Claude Code's `~/.claude/settings.json` for you — that activation step
lives in the README, and `context-stats doctor` (added in #187) diagnoses it.
Because the CLI is the one context-stats process guaranteed to run while the
status line is unwired, every `context-stats` invocation volunteers a one-line
hint on stderr until the wiring exists (see `docs/troubleshooting.md`):

```bash
! statusLine is not wired into ~/.claude/settings.json — the status line will never run. Fix: context-stats doctor --fix
```

The hint goes to stderr only, never to stdout, and never changes the exit
code. It is silent when the wiring exists, and also when `settings.json` is
missing, unreadable, or malformed (doctor diagnoses those on their own
terms). Once you run `context-stats doctor --fix` the hint disappears.

To suppress it without wiring the status line, either set the config key:

```bash
suppress_setup_hint=true   # in ~/.claude/statusline.conf
```

or export the environment variable:

```bash
export CONTEXT_STATS_SUPPRESS_SETUP_HINT=1
```

Either one suppresses the hint (both are honored; the env var needs no
config file). Default is `false` / unset — the hint is shown when unwired.

## Config File Format

The config file uses simple `key=value` syntax:

- No spaces around `=`
- Lines starting with `#` are comments
- Unrecognized keys are ignored
- Missing keys use defaults shown above
