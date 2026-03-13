# CSV State File Format

State files are stored at `~/.claude/statusline/statusline.<session_id>.state`. Each line is a CSV record with 14 comma-separated fields.

## Field Specification

| Index | Field | Type | Description |
|-------|-------|------|-------------|
| 0 | `timestamp` | integer | Unix timestamp in seconds |
| 1 | `total_input_tokens` | integer | Cumulative input tokens for the session |
| 2 | `total_output_tokens` | integer | Cumulative output tokens for the session |
| 3 | `current_input_tokens` | integer | Input tokens for the current request |
| 4 | `current_output_tokens` | integer | Output tokens for the current request |
| 5 | `cache_creation` | integer | Cache creation input tokens |
| 6 | `cache_read` | integer | Cache read input tokens |
| 7 | `cost_usd` | float | Total session cost in USD |
| 8 | `lines_added` | integer | Total lines added in session |
| 9 | `lines_removed` | integer | Total lines removed in session |
| 10 | `session_id` | string | Session identifier (UUID) |
| 11 | `model_id` | string | Model identifier (e.g., `claude-opus-4-5`) |
| 12 | `workspace_project_dir` | string | Project directory path (commas replaced with underscores) |
| 13 | `context_window_size` | integer | Context window size in tokens |

## Constraints

- Fields are separated by commas with no quoting or escaping.
- The `workspace_project_dir` field (index 12) is sanitized before writing: all comma characters (`,`) are replaced with underscores (`_`) to prevent CSV corruption.
- Numeric fields default to `0` when absent. String fields default to empty string.
- Lines are newline-terminated (`\n`).
- Files are append-only.
- Files are automatically rotated at 10,000 lines (keeps most recent 5,000) by the Python and Node.js statusline scripts.
- Duplicate entries (same token count as previous line) are skipped to prevent file bloat.

## Legacy Format

Older state files may contain 2-field lines: `timestamp,total_input_tokens`. The reader defaults all other fields to zero/empty for these lines.

## Example

```
1710288000,75000,8500,50000,5000,10000,20000,0.05234,250,45,abc-123-def,claude-opus-4-5,/home/user/my-project,200000
```
