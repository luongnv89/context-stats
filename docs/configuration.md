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
```

## Status Line Components

```
[Opus 4.5] my-project | main [3] | 64,000 free (32.0%) [+2,500] [AC:45k] session_id
```

| Component     | Description              | Color            |
| ------------- | ------------------------ | ---------------- |
| `[Opus 4.5]`  | Current AI model         | Dim              |
| `my-project`  | Current directory        | Blue             |
| `main`        | Git branch               | Magenta          |
| `[3]`         | Uncommitted changes      | Cyan             |
| `64,000 free` | Available tokens         | Green/Yellow/Red |
| `(32.0%)`     | Context usage percentage | -                |
| `[+2,500]`    | Token delta              | -                |
| `[AC:45k]`    | Autocompact buffer       | Dim              |
| `session_id`  | Current session          | Dim              |

## Token Colors

Context availability is color-coded:

| Availability | Color  |
| ------------ | ------ |
| > 50%        | Green  |
| > 25%        | Yellow |
| <= 25%       | Red    |

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

## Config File Format

The config file uses simple `key=value` syntax:

- No spaces around `=`
- Lines starting with `#` are comments
- Unrecognized keys are ignored
- Missing keys use defaults shown above
