# Configuration

The configuration file `~/.claude/statusline.conf` is automatically created with default settings on first run.

Windows location: `%USERPROFILE%\.claude\statusline.conf`

## Settings

```bash
# Autocompact setting - sync with Claude Code's /config
autocompact=true   # (default) Show reserved buffer for compacting
autocompact=false  # When autocompact is disabled via /config

# Token display format
token_detail=true  # (default) Show exact token count: 64,000 free
token_detail=false # Show abbreviated tokens: 64.0k free

# Show token delta since last refresh
show_delta=true    # (default) Show delta like [+2,500]
show_delta=false   # Disable delta display

# Show session_id in status line
show_session=true  # (default) Show session ID
show_session=false # Hide session ID

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

| Component     | Description              | Color            |
| ------------- | ------------------------ | ---------------- |
| `[Opus 4.6]`  | Current AI model         | Dim              |
| `my-project`  | Current directory        | Blue             |
| `main`        | Git branch               | Magenta          |
| `[3]`         | Uncommitted changes      | Cyan             |
| `64,000 free` | Available tokens         | Green/Yellow/Red |
| `(32.0%)`     | Context usage percentage | -                |
| `[+2,500]`    | Token delta              | Dim              |
| `MI:0.918`    | Model Intelligence score | Green/Yellow/Red |
| `[AC:45k]`    | Autocompact buffer       | Dim              |
| `session_id`  | Current session          | Dim              |

## Token Colors

Context availability is color-coded:

| Availability | Color  |
| ------------ | ------ |
| > 50%        | Green  |
| > 25%        | Yellow |
| <= 25%       | Red    |

## Model Intelligence Colors

MI score is color-coded based on degradation level:

| MI Score | Color  | Meaning                                    |
| -------- | ------ | ------------------------------------------ |
| > 0.70   | Green  | Model is operating well                    |
| 0.40-0.70| Yellow | Context pressure building, consider wrap up|
| < 0.40   | Red    | Significant degradation, start new session |

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

## Custom Colors

Override any status line color with named colors or hex codes:

```bash
# Available slots
color_green=#7dcfff       # Context >50% free
color_yellow=bright_yellow # Context 25-50% free
color_red=#f7768e         # Context <25% free
color_blue=bright_blue    # Directory name
color_magenta=#bb9af7     # Git branch
color_cyan=bright_cyan    # Git change count
```

### Supported color values

**Named colors**: `black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`, `bright_black`, `bright_red`, `bright_green`, `bright_yellow`, `bright_blue`, `bright_magenta`, `bright_cyan`, `bright_white`

**Hex colors**: Any `#rrggbb` value (requires terminal with 24-bit color support)

Unrecognized color values are ignored with a warning to stderr. Omitted slots use defaults.

## Config File Format

The config file uses simple `key=value` syntax:

- No spaces around `=`
- Lines starting with `#` are comments
- Unrecognized keys are ignored
- Missing keys use defaults shown above
