# CLAUDE.md

## Project Purpose

context-stats provides real-time context window monitoring for Claude Code sessions. It tracks token consumption over time and displays live ASCII graphs so users can see how much context remains.

## Implementation

The statusline is implemented in Python. Claude Code invokes the statusline script via stdin JSON pipe — the script reads JSON from stdin and writes formatted text to stdout. The Python implementation persists state to CSV files read by the `context-stats` CLI.

## CSV Format Contract

State files are append-only CSV at `~/.claude/statusline/statusline.<session_id>.state` with 15 comma-separated fields. See [docs/CSV_FORMAT.md](docs/CSV_FORMAT.md) for the full field specification. Key constraint: `workspace_project_dir` has commas replaced with underscores before writing.

## Statusline Script

| Script                  | Language | State writes | Notes                       |
| ----------------------- | -------- | ------------ | --------------------------- |
| `scripts/statusline.py` | Python 3 | Yes          | Pip-installable via package |

## Test Commands

```bash
# Python tests
source venv/bin/activate
pytest tests/python/ -v

# All tests
pytest tests/python/ -v
```

## Key Architectural Decisions

- **Append-only CSV state files** with rotation at 10,000 lines (keeps most recent 5,000)
- **No network requests** — all data stays local in `~/.claude/statusline/`
- **Session ID validation** — rejects `/`, `\`, `..`, and null bytes for path-traversal defense
- **5-second git command timeout** in the Python implementation
- **Config via `~/.claude/statusline.conf`** — simple key=value pairs

## Sync Points: Package vs Standalone Script

The following logic is duplicated between the installable package (`src/`) and the standalone script (`scripts/statusline.py`) and **must be kept in sync** when modified:

| Logic                                                    | Package (`src/`)                                                                                                                                                                                            | Standalone Python (`scripts/statusline.py`)                                                                |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Config parsing                                           | `core/config.py`                                                                                                                                                                                            | `read_config()`                                                                                            |
| Color name map                                           | `core/colors.py:COLOR_NAMES`                                                                                                                                                                                | `_COLOR_NAMES`                                                                                             |
| Color parser                                             | `core/colors.py:parse_color()`                                                                                                                                                                              | `_parse_color()`                                                                                           |
| Git info                                                 | `core/git.py:get_git_info()`                                                                                                                                                                                | `get_git_info()`                                                                                           |
| PR number lookup                                         | `core/git.py:_get_pr_number()`                                                                                                                                                                              | `get_pr_number()`                                                                                          |
| PR number cache (60s TTL, per-branch, `~/.claude/statusline/pr_number_cache.json`) | `core/git.py:_PR_CACHE_TTL_SECONDS`, `_pr_cache_file()`, `_pr_cache_get()`, `_pr_cache_set()`                                                                                   | `_PR_CACHE_TTL_SECONDS`, `_pr_cache_file()`, `_pr_cache_get()`, `_pr_cache_set()`                          |
| State rotation                                           | `core/state.py`                                                                                                                                                                                             | `maybe_rotate_state_file()`                                                                                |
| MI profiles                                              | `graphs/intelligence.py:MODEL_PROFILES`                                                                                                                                                                     | `MODEL_PROFILES`                                                                                           |
| MI formula                                               | `graphs/intelligence.py:calculate_context_pressure()`                                                                                                                                                       | `compute_mi()`                                                                                             |
| MI colors                                                | `graphs/intelligence.py:get_mi_color()`                                                                                                                                                                     | `get_mi_color()`                                                                                           |
| Zone indicator                                           | `graphs/intelligence.py:get_context_zone()`                                                                                                                                                                 | `get_context_zone()`                                                                                       |
| Zone constants                                           | `ZONE_1M_*`, `ZONE_STD_*`, `LARGE_MODEL_THRESHOLD`                                                                                                                                                          | same                                                                                                       |
| Per-property colors                                      | `colors.py:ColorManager` props, `config.py:_COLOR_KEYS`                                                                                                                                                     | `_COLOR_KEYS`, per-property vars                                                                           |
| Context group separator (`tokens·zone·pacman` as ONE atomic part, `·` unspaced) | `cli/statusline.py` `parts` entry `context_info + zone_info + pacman_info`; `zone_info`/`pacman_info` built with a `"·"` prefix | same: `parts` entry `context_info + zone_info + pacman_info`, `"·"` prefixes |
| Model suffix separator (`Model·effort`, unspaced)        | `cli/statusline.py` `model_suffix` (`f"·{...}"`)                                                                          | `model_suffix` (`f"·{...}"`)                                                                               |
| Layout / responsive width fit (multi-line reflow)        | `formatters/layout.py:visible_width()`, `get_terminal_width()`, `fit_to_width()`, `_PART_SEPARATOR`                                                                                                          | `visible_width()`, `get_terminal_width()`, `fit_to_width()`, `_PART_SEPARATOR`                             |
| Compaction detection                                     | `graphs/statistics.py:detect_compaction_events()`                                                                                                                                                           | `detect_compaction_events()`                                                                               |
| Compaction constants                                     | `core/config.py:compaction_drop_threshold`, `compact_mi_warn_threshold`                                                                                                                                     | `COMPACTION_DROP_THRESHOLD`, `COMPACT_MI_WARN_THRESHOLD`                                                   |
| tok/s compute (rolling, token-weighted avg over N turns) | `graphs/statistics.py:compute_tps(samples, window)`, `format_tps()`                                                                                                                                         | `compute_tps(samples, window)`, `format_tps()`                                                             |
| tok/s config                                             | `core/config.py:show_tps`, `tps_precision`, `tps_unit`, `tps_window`                                                                                                                                        | `read_config()` `show_tps`/`tps_precision`/`tps_unit`/`tps_window`                                         |
| tok/s state field                                        | `core/state.py:StateEntry.api_duration_ms` (CSV index 14)                                                                                                                                                   | `state_data` list + `csv_parts[14]`                                                                        |
| tok/s rolling read (bounded tail)                        | `cli/statusline.py` calls `core/state.py:StateFile.read_tail(_tps_tail_size(tps_window))` → `(output, api_duration_ms)` samples (NOT `read_history()`, which stays full for the CLI graph/export consumers) | tail-bounded loop over `file_lines[-_tps_tail_size(tps_window):]` building `tps_samples` from index 4 + 14 |
| tok/s tail size helper                                   | `cli/statusline.py:_tps_tail_size()`, `_TPS_TAIL_BUFFER`                                                                                                                                                    | `_tps_tail_size()`, `_TPS_TAIL_BUFFER`                                                                     |
| Session cost display (`$X.XX`, default on)               | `core/config.py:show_cost`, `cli/statusline.py` `cost_info` segment + `parts`, `colors.py:ColorManager.cost`, `_COLOR_KEYS:color_cost`                                                                       | `read_config()` `show_cost`, `cost_info` build + `parts`, `c_cost`, `_COLOR_KEYS:color_cost`               |
| Effort display (`effort.level` next to model, default on) | `core/config.py:show_effort` (dataclass + parse + `to_dict` + `_MINIMAL_CONFIG_FALLBACK`), `cli/statusline.py` `effort_level` extract (isinstance-guarded `effort_data.get("level")`) + `model_suffix`; conf comment synced in `data/statusline.conf.default` + `examples/statusline.conf` (kept byte-identical by `test_config_colors.py`) | `read_config()` `show_effort` (defaults + parse), `effort_level` extract + `model_suffix`, conf comment block |
| UTF-8 stdout guard (Windows cp1252 defense, called first in `main()`) | `cli/statusline.py:_ensure_utf8_stdout()` (mirrors `cli/context_stats.py:_ensure_utf8_stdout()`)                                                                                                            | `_ensure_utf8_stdout()`                                                                                    |
| Pacman icon mapping (zone → glyph)                       | `graphs/intelligence.py:PACMAN_ICONS`, `get_pacman_icon()`                                                                                                                                                 | `PACMAN_ICONS`, `get_pacman_icon()`                                                                        |
| Pacman icon display (`show_pacman`, default on, next to zone label, reuses zone color) | `core/config.py:show_pacman` (dataclass + parse + `to_dict()` + fallback), `cli/statusline.py` `pacman_info` build (reuses `zone_result`/`zone_color`) + `parts`; conf comment synced in `data/statusline.conf.default` + `examples/statusline.conf` (kept byte-identical by `test_config_colors.py`) | `read_config()` `show_pacman` (defaults + parse), `pacman_info` build (reuses `zone_word`/`zone_ansi`) + `parts`, conf comment block |

## Cross-References

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system architecture and data flow
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — setup, testing, and contribution guide
- [docs/CSV_FORMAT.md](docs/CSV_FORMAT.md) — state file field specification
