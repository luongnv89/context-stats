"""Cross-implementation parity suite (issue #136 — F-TEST-001, F-BUG-010).

Every row of the ``Sync Points: Package vs Standalone Script`` table in
CLAUDE.md pairs a symbol in the installable package (``src/claude_statusline/``)
with its twin in the standalone script (``scripts/statusline.py``). This suite
imports each pair and asserts behavioral equivalence over shared fixtures, so a
change to either copy of any covered pair alone fails here (drift children such
as the unguarded ``cli/context_stats.py:_ensure_utf8_stdout`` — F-BUG-010 — can
no longer ship unnoticed).

Coverage is enforced two ways:

1. A registry (:data:`SYNC_ROWS`) maps every CLAUDE.md sync-table row to the
   tests covering it; :class:`TestSyncTableFullyCovered` fails when the table
   grows or shrinks without the registry following.
2. Each covered pair is exercised behaviorally (pure-function grids, constant
   equality, file-backed rotation/migration/config flows, and byte-identical
   full renders through both entry points).

The standalone script is imported as ``scripts.statusline`` (conftest puts the
repo root on ``sys.path``). Full renders of the standalone side always run in a
subprocess so an isolated HOME/state dir is guaranteed regardless of how many
in-process renders ran earlier (Task 5.4 removed the module-global palette
mutation, but subprocess isolation also keeps config templates and state files
from leaking between cases).
"""

from __future__ import annotations

import ast as ast_mod
import builtins
import io
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import statusline as sl

import claude_statusline._shared as shared_module
from claude_statusline.cli import context_stats as cs
from claude_statusline.cli import statusline as pkg
from claude_statusline.core.colors import COLOR_NAMES, ColorManager, parse_color
from claude_statusline.core.config import _COLOR_KEYS as PKG_COLOR_KEYS
from claude_statusline.core.config import Config
from claude_statusline.core.git import (
    _PR_CACHE_NEGATIVE_TTL_SECONDS,
    _PR_CACHE_TTL_SECONDS,
    _get_pr_number,
    _pr_cache_file,
    _pr_cache_get,
    _pr_cache_set,
    get_git_info,
)
from claude_statusline.core.state import (
    StateEntry,
    StateFile,
    _csv_unsafe_reason,
    _sanitize_workspace_dir,
    _validate_csv_field,
    _validate_session_id,
)
from claude_statusline.formatters.layout import (
    _PART_SEPARATOR,
    fit_to_width,
    get_terminal_width,
    visible_width,
)
from claude_statusline.graphs.intelligence import (
    LARGE_MODEL_THRESHOLD,
    MODEL_PROFILES,
    PACMAN_ICONS,
    ZONE_1M_C_MAX,
    ZONE_1M_D_MAX,
    ZONE_1M_P_MAX,
    ZONE_1M_PRICING_MAX,
    ZONE_1M_X_MAX,
    ZONE_STD_DEAD_ZONE,
    ZONE_STD_DUMP_ZONE,
    ZONE_STD_HARD_LIMIT,
    ZONE_STD_WARN_BUFFER,
    ZoneThresholds,
    calculate_context_pressure,
    get_context_zone,
    get_mi_color,
    get_model_profile,
    get_pacman_icon,
)
from claude_statusline.graphs.statistics import (
    compute_tps,
    detect_compaction_events,
    format_tps,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "statusline.py"
SHARED_MODULE_PATH = PROJECT_ROOT / "src" / "claude_statusline" / "_shared.py"
VENDORED_SHARED_PATH = PROJECT_ROOT / "scripts" / "_statusline_shared.py"
GOLDEN_FIXTURES_PATH = PROJECT_ROOT / "tests" / "python" / "fixtures" / "render_goldens.json"

PKG_ROTATION_THRESHOLD = StateFile.ROTATION_THRESHOLD
PKG_ROTATION_KEEP = StateFile.ROTATION_KEEP

ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# ---------------------------------------------------------------------------
# Sync-table coverage registry — one key per CLAUDE.md sync-table row
# (first column text, verbatim). TestSyncTableFullyCovered enforces that the
# table and this registry stay in lockstep.
# ---------------------------------------------------------------------------

SYNC_ROWS: dict[str, tuple[str, ...]] = {
    "Config parsing": ("test_config_parsing_parity",),
    "Color name map": ("test_color_name_map_equal",),
    "Color parser": ("test_parse_color_grid",),
    "Git info (accepts `.git` as directory OR worktree/submodule pointer file)": (
        "test_git_info_parity",
        "test_subprocess_count_render_budget",
        "test_status_changes_cap_display",
    ),
    "PR number lookup": (
        "test_pr_number_lookup_unavailable_gh",
        "test_pr_number_shares_branch_cache",
    ),
    "PR number cache (60s TTL, 10s negative TTL for gh failures, per-branch, "
    "`~/.claude/statusline/pr_number_cache.json`)": (
        "test_pr_cache_constants_equal",
        "test_pr_cache_roundtrip_and_cross_read",
    ),
    "Branch cache (10s TTL, 5s negative TTL, dir-keyed, `~/.claude/statusline/branch_cache.json`; hoists the per-render rev-parse)": (
        "test_branch_cache_constants_equal",
        "test_branch_cache_roundtrip_and_cross_read",
    ),
    "State rotation (append+rotate serialized under best-effort `fcntl` exclusive lock; "
    "rotation core atomic temp+rename; `_ROTATION_SCAN_FLOOR_BYTES` byte gate skips the line count below a provable size floor, F-PERF-002)": (
        "test_rotation_constants_equal",
        "test_maybe_rotate_keeps_recent_tail",
        "test_rotate_locked_via_append_cross_format",
        "test_rotate_byte_gate_skips_scan_below_floor",
        "test_rotate_byte_gate_boundary_tiny_rows",
    ),
    "MI profiles": ("test_model_profiles_equal", "test_get_model_profile_grid"),
    "MI formula": ("test_mi_formula_grid",),
    "MI colors": ("test_mi_color_grid",),
    "Zone indicator": ("test_context_zone_grid", "test_pricing_zone_grid"),
    "Zone constants": ("test_zone_constants_equal",),
    "Per-property colors": (
        "test_color_keys_equal",
        "test_color_manager_property_fallback_chain",
    ),
    "Context group separator (`tokens·zone·pacman` as ONE atomic part, `·` unspaced)": (
        "test_render_byte_parity_basic",
        "test_render_byte_parity_narrow_width_group_atomic",
    ),
    "Model suffix separator (`Model·effort`, unspaced)": (
        "test_render_byte_parity_effort_and_thinking",
    ),
    "Layout / responsive width fit (multi-line reflow)": (
        "test_layout_helpers_grid",
        "test_render_byte_parity_narrow_width_group_atomic",
    ),
    "Compaction detection": ("test_detect_compaction_events_grid",),
    "Compaction constants": ("test_compaction_constants_equal",),
    "tok/s compute (rolling, token-weighted avg over N turns)": (
        "test_compute_tps_grid",
        "test_format_tps_grid",
    ),
    "tok/s config": ("test_config_parsing_parity",),
    "tok/s state field": ("test_api_duration_state_field_index14",),
    "tok/s rolling read (bounded tail)": (
        "test_render_byte_parity_tps_rolling_read",
        "test_read_tail_window_bounded_bytes",
        "test_load_state_history_window_bounded_bytes",
        "test_windowed_reads_agree_across_implementations",
    ),
    "tok/s tail size helper": ("test_tps_tail_size_grid",),
    "State-row parsing (`parse_state_row`: last-entry + bounded-tail reads replace index-magic CSV access)": (
        "test_parse_state_row_grid",
        "test_used_tokens_agree_with_state_entry",
        "test_render_byte_parity_tps_rolling_read",
    ),
    "Session cost display (`$X.XX`, default on)": (
        "test_render_byte_parity_basic",
        "test_render_byte_parity_show_cost_off",
    ),
    "Effort display (`effort.level` next to model, default on)": (
        "test_render_byte_parity_effort_and_thinking",
        "test_render_byte_parity_show_cost_off",
    ),
    "UTF-8 stdout guard (Windows cp1252 defense, called first in `main()`)": (
        "test_utf8_guard_reused_in_context_stats",
        "test_utf8_guard_behavior_grid",
    ),
    "Pacman icon mapping (zone → glyph)": (
        "test_pacman_icons_equal",
        "test_pacman_icon_grid",
        "test_pricing_icon_and_recommendation_match_shared",
    ),
    "Pacman icon display (`show_pacman`, default on, next to zone label, reuses zone color)": (
        "test_render_byte_parity_basic",
        "test_render_byte_parity_show_cost_off",
    ),
    "Session ID validation (path-traversal + CSV-safety defense: rejects `/`, `\\`, `..`, "
    "null bytes, comma/newline/control chars)": (
        "test_validate_session_id_grid",
        "test_validate_csv_field_grid",
        "test_render_byte_parity_hostile_session_id",
    ),
    "External-input extraction (explicit JSON null treated as absent)": ("test_extract_grid",),
    "Render catch-all (unexpected exceptions → minimal line on stdout, traceback to stderr)": (
        "test_render_catch_all_parity",
    ),
    "project_dir trust gate (git/gh only run inside a verified-existing directory)": (
        "test_resolve_project_dir_grid",
    ),
    "State file creation mode (0600, owner-only)": ("test_state_file_creation_mode_parity",),
    "Legacy-state migration (guarded move/remove, warns on OSError, never breaks the refresh; sentinel marker skips the sweep after a clean pass, F-PERF-005)": (
        "test_legacy_migration_parity",
        "test_migrate_sentinel_prevents_repeat_sweep",
    ),
    "Named render constants (autocompact ratio, thinking tiers, zone RGB ANSI)": (
        "test_shared_render_constants_equal",
    ),
}


def _sync_table_row_texts() -> list[str]:
    """Extract the first-column text of every data row in the CLAUDE.md table."""
    lines = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    rows: list[str] = []
    in_table = False
    for line in lines:
        if line.startswith("| Logic"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.split("|")]
        if cells[1] and not set(cells[1]) <= {"-", ":", " "}:
            rows.append(cells[1])
    return rows


class TestSyncTableFullyCovered:
    """The suite covers at least every row currently listed in CLAUDE.md."""

    def test_registry_matches_table_exactly(self):
        table_rows = _sync_table_row_texts()
        assert len(table_rows) >= 25, "CLAUDE.md sync table unexpectedly shrank"
        registry_keys = set(SYNC_ROWS)
        assert set(table_rows) == registry_keys, (
            "CLAUDE.md sync table and SYNC_ROWS registry diverged.\n"
            f"In table, not covered: {sorted(set(table_rows) - registry_keys)}\n"
            f"In registry, not in table: {sorted(registry_keys - set(table_rows))}"
        )

    @pytest.mark.parametrize(
        ("row", "tests"),
        sorted(SYNC_ROWS.items()),
        ids=[row[:40] for row, _ in sorted(SYNC_ROWS.items())],
    )
    def test_registered_tests_exist(self, row, tests):
        import inspect

        module = sys.modules[__name__]
        for name in tests:
            found = hasattr(module, name) or any(
                inspect.isclass(obj) and hasattr(obj, name) for obj in vars(module).values()
            )
            assert found, f"{name} (covering sync row {row!r}) is missing"


# ---------------------------------------------------------------------------
# Shared fixtures and harnesses
# ---------------------------------------------------------------------------

COMMENT_ONLY_CONF = "# comment-only config keeps built-in defaults\n"


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Isolated HOME with a known comment-only conf so both sides see the
    same parsed defaults regardless of their differing auto-created templates."""
    home = tmp_path / "home"
    conf_dir = home / ".claude"
    conf_dir.mkdir(parents=True)
    (conf_dir / "statusline.conf").write_text(COMMENT_ONLY_CONF, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def build_payload(project_dir, **overrides):
    """A stdin payload rich enough to reach the context/state segments."""
    payload = {
        "session_id": "parity-session",
        "model": {"id": "claude-test", "display_name": "Test Model"},
        "workspace": {"current_dir": str(project_dir), "project_dir": str(project_dir)},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 10000,
                "cache_creation_input_tokens": 500,
                "cache_read_input_tokens": 200,
                "output_tokens": 900,
            },
        },
        "cost": {
            "total_cost_usd": 0.42,
            "total_lines_added": 3,
            "total_lines_removed": 1,
            "total_api_duration_ms": 42000,
        },
    }
    payload.update(overrides)
    return payload


def _make_git_repo(path: Path, dirty_files: int = 0) -> Path:
    """Create a real minimal git repo (mirrors the git-info parity setup)."""
    import subprocess as sp

    path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    sp.run(["git", "init", "-q", str(path)], check=True, env=env)
    cfg = ["-c", "user.email=t@t", "-c", "user.name=t"]
    sp.run(
        ["git", *cfg, "commit", "--allow-empty", "-q", "-m", "init"],
        cwd=path,
        check=True,
        env=env,
    )
    for i in range(dirty_files):
        (path / f"f{i}.txt").write_text("x", encoding="utf-8")
    return path


def render_standalone(payload, home, columns="200"):
    """Run scripts/statusline.py in a subprocess; returns (stdout, stderr)."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["COLUMNS"] = columns
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.rstrip("\n"), result.stderr


def render_package(payload, monkeypatch, capsys, home, columns="200"):
    """Run the package CLI entry point in-process against an isolated home."""
    state_dir = home / ".claude" / "statusline"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
    old_dir = home / ".claude-old"
    old_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(StateFile, "OLD_STATE_DIR", old_dir)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("COLUMNS", columns)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    pkg.main()
    captured = capsys.readouterr()
    return captured.out.rstrip("\n"), captured.err


# ---------------------------------------------------------------------------
# Row: Sync-table meta coverage (above) + constants rows
# ---------------------------------------------------------------------------


class TestConstantPairs:
    """Rows whose synced symbols are module-level constants/mappings."""

    def test_color_name_map_equal(self):
        assert COLOR_NAMES == sl._COLOR_NAMES

    def test_color_keys_equal(self):
        assert PKG_COLOR_KEYS == sl._COLOR_KEYS

    def test_zone_constants_equal(self):
        assert sl.ZONE_1M_P_MAX == ZONE_1M_P_MAX
        assert sl.ZONE_1M_PRICING_MAX == ZONE_1M_PRICING_MAX
        assert sl.ZONE_1M_C_MAX == ZONE_1M_C_MAX
        assert sl.ZONE_1M_D_MAX == ZONE_1M_D_MAX
        assert sl.ZONE_1M_X_MAX == ZONE_1M_X_MAX
        assert sl.ZONE_STD_DUMP_ZONE == ZONE_STD_DUMP_ZONE
        assert sl.ZONE_STD_WARN_BUFFER == ZONE_STD_WARN_BUFFER
        assert sl.ZONE_STD_HARD_LIMIT == ZONE_STD_HARD_LIMIT
        assert sl.ZONE_STD_DEAD_ZONE == ZONE_STD_DEAD_ZONE
        assert sl.LARGE_MODEL_THRESHOLD == LARGE_MODEL_THRESHOLD

    def test_model_profiles_equal(self):
        assert sl.MODEL_PROFILES == MODEL_PROFILES

    def test_compaction_constants_equal(self):
        defaults = Config()
        assert sl.COMPACTION_DROP_THRESHOLD == defaults.compaction_drop_threshold
        assert sl.COMPACT_MI_WARN_THRESHOLD == defaults.compact_mi_warn_threshold

    def test_rotation_constants_equal(self):
        assert sl.ROTATION_THRESHOLD == PKG_ROTATION_THRESHOLD
        assert sl.ROTATION_KEEP == PKG_ROTATION_KEEP

    def test_pr_cache_constants_equal(self):
        assert sl._PR_CACHE_TTL_SECONDS == _PR_CACHE_TTL_SECONDS
        assert sl._PR_CACHE_NEGATIVE_TTL_SECONDS == _PR_CACHE_NEGATIVE_TTL_SECONDS

    def test_shared_render_constants_equal(self):
        """Named render constants (Task 5.4, F-CLEAN-010) agree across both
        implementations: the script's bound autocompact ratio equals the
        package default, and the shared tier/ANSI constants are identical in
        the canonical module and its vendored copy."""
        import importlib.util

        from claude_statusline._shared import AUTOCOMPACT_RATIO
        from claude_statusline.formatters.tokens import calculate_context_usage

        assert sl._AUTOCOMPACT_RATIO == AUTOCOMPACT_RATIO == 0.225
        # The package consumer really defaults to the shared constant.
        assert calculate_context_usage.__defaults__ is not None
        assert AUTOCOMPACT_RATIO in calculate_context_usage.__defaults__

        spec = importlib.util.spec_from_file_location(
            "_vendored_shared_check", VENDORED_SHARED_PATH
        )
        assert spec is not None and spec.loader is not None
        vendored = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vendored)
        for name in (
            "AUTOCOMPACT_RATIO",
            "THINKING_K_FLOOR",
            "THINKING_K_ROUND_MIN",
            "THINKING_M_THRESHOLD",
            "ZONE_ORANGE_ANSI",
            "ZONE_AMBER_ANSI",
            "ZONE_DARK_RED_ANSI",
            "ZONE_GRAY_ANSI",
        ):
            assert getattr(sl._shared, name) == getattr(vendored, name), name

    def test_tps_tail_size_grid(self):
        assert sl._TPS_TAIL_BUFFER == pkg._TPS_TAIL_BUFFER
        for window in (-3, 0, 1, 2, 5, 7, 50):
            assert sl._tps_tail_size(window) == pkg._tps_tail_size(window)

    def test_layout_helpers_grid(self):
        assert sl._PART_SEPARATOR == _PART_SEPARATOR
        samples = [
            "",
            "plain",
            "\033[0;32mgreen\033[0m",
            "ᗧ·mixed\033[38;2;255;165;0mANSI\033[0m",
        ]
        for text in samples:
            assert sl.visible_width(text) == visible_width(text)
        parts_sets = [
            ["base"],
            ["base", " | one", " | two"],
            ["base", " | way-too-long-part-that-certainly-wraps"],
            ["base", "", " | skipped-empty", " | tail"],
            [],
        ]
        for parts in parts_sets:
            for width in (10, 40, 200):
                assert sl.fit_to_width(parts, width) == fit_to_width(parts, width), (parts, width)
        monkey_cols = os.environ.get("COLUMNS")
        try:
            os.environ["COLUMNS"] = "123"
            assert sl.get_terminal_width() == get_terminal_width() == 123
        finally:
            if monkey_cols is None:
                del os.environ["COLUMNS"]
            else:
                os.environ["COLUMNS"] = monkey_cols


# ---------------------------------------------------------------------------
# Row: Color parser / Per-property colors
# ---------------------------------------------------------------------------


class TestColorPairs:
    @pytest.mark.parametrize(
        "value",
        [
            "",
            "red",
            "RED",
            " Bright_Cyan ",
            "bright_black",
            "bold_white",
            "dim",
            "#ff5733",
            "#FF5733",
            "#f5733",
            "#gg5733",
            "#aabbccdd",
            "not-a-color",
        ],
    )
    def test_parse_color_grid(self, value):
        assert sl._parse_color(value) == parse_color(value)

    @pytest.mark.parametrize(
        "overrides",
        [
            {},
            {"green": "\033[38;2;1;2;3m"},
            {"project_name": "\033[0;36m"},
            {"blue": "\033[0;34m"},
            {"magenta": "\033[0;35m"},
            {"separator": "\033[1;90m"},
            {"blue": "\033[0;34m", "branch_name": "\033[0;93m"},
            {"mi_score": "\033[38;2;255;100;0m", "zone": "\033[0;92m"},
        ],
        ids=str,
    )
    def test_color_manager_property_fallback_chain(self, overrides):
        """ColorManager slots must resolve exactly like the standalone
        per-property chain in scripts/statusline.py:_render."""
        cm = ColorManager(enabled=True, overrides=dict(overrides))
        c = overrides

        assert cm.project_name == c.get("project_name", c.get("blue", "\033[0;36m"))
        assert cm.branch_name == c.get("branch_name", c.get("magenta", "\033[0;32m"))
        separator_default = c.get("separator", "\033[2m")
        for slot in ("tps", "delta", "cost", "model", "session"):
            assert getattr(cm, slot) == c.get(slot, separator_default), slot
        assert cm.context_length == c.get("context_length", "\033[1;97m")
        assert cm.mi_score == c.get("mi_score", "\033[0;33m")


# ---------------------------------------------------------------------------
# Rows: MI profiles / MI formula / MI colors / Zone indicator
# ---------------------------------------------------------------------------

MODEL_GRID = ["", "opus", "claude-opus-4-6", "anthropic/sonnet-4.5", "haiku-3", "unknown-x"]
UTIL_GRID = [0.0, 0.1, 0.25, 0.5, 0.64, 0.8, 0.9, 0.99, 1.0, 1.25]


class TestIntelligencePairs:
    @pytest.mark.parametrize("model_id", MODEL_GRID)
    def test_get_model_profile_grid(self, model_id):
        assert sl.get_model_profile(model_id) == get_model_profile(model_id)

    @pytest.mark.parametrize("beta", [0.0, 1.3, 1.5, 2.0])
    @pytest.mark.parametrize("util", UTIL_GRID)
    def test_mi_formula_grid(self, util, beta):
        window = 200000
        used = int(util * window)
        # Both sides treat beta_override<=0 as "use the model profile".
        effective_beta = beta if beta > 0 else get_model_profile("")
        assert sl.compute_mi(used, window, "", beta) == calculate_context_pressure(
            util, effective_beta
        )

    @pytest.mark.parametrize("util", UTIL_GRID)
    def test_mi_formula_profile_beta(self, util):
        """With beta_override=0 both sides derive beta from the model profile."""
        window = 200000
        used = int(util * window)
        for model_id in MODEL_GRID:
            expected = calculate_context_pressure(util, get_model_profile(model_id))
            assert sl.compute_mi(used, window, model_id) == expected, model_id

    def test_mi_formula_zero_window_guard(self):
        assert sl.compute_mi(1000, 0) == 1.0

    @pytest.mark.parametrize("utilization", [0.0, 0.39, 0.40, 0.79, 0.80, 0.95])
    @pytest.mark.parametrize("mi", [0.0, 0.80, 0.85, 0.899, 0.90, 0.95, 1.0])
    def test_mi_color_grid(self, mi, utilization):
        ansi_to_name = {sl.RED: "red", sl.YELLOW: "yellow", sl.GREEN: "green"}
        assert ansi_to_name[sl.get_mi_color(mi, utilization)] == get_mi_color(mi, utilization)

    ZONE_CASES = [
        (0, 0, {}),
        (10_000, 200_000, {}),
        (49_999, 200_000, {}),
        (50_000, 200_000, {}),
        (80_000, 200_000, {}),
        (140_000, 200_000, {}),
        (150_000, 200_000, {}),
        (149_999, 1_000_000, {}),
        (150_000, 1_000_000, {}),
        (199_999, 1_000_000, {}),
        (200_000, 1_000_000, {}),
        (250_000, 1_000_000, {}),
        (400_000, 1_000_000, {}),
        (450_000, 1_000_000, {}),
        (450_001, 1_000_000, {}),
        (100_000, 1_000_000, {"large_model_threshold": 900_000}),
        (90_000, 200_000, {"zone_std_dump_ratio": 0.45}),
        (30_000, 200_000, {"zone_std_warn_buffer": 40_000}),
        (130_000, 200_000, {"zone_std_hard_limit": 0.6}),
        (145_000, 200_000, {"zone_std_dead_ratio": 0.72}),
        (160_000, 1_000_000, {"zone_1m_plan_max": 170_000}),
        (220_000, 1_000_000, {"zone_pricing_max": 230_000}),
        (180_000, 1_000_000, {"zone_pricing_max": 170_000}),
        (260_000, 1_000_000, {"zone_1m_code_max": 270_000}),
        (410_000, 1_000_000, {"zone_1m_dump_max": 420_000}),
        (440_000, 1_000_000, {"zone_1m_xdump_max": 441_000}),
    ]

    @pytest.mark.parametrize(("used", "size", "overrides"), ZONE_CASES, ids=str)
    def test_context_zone_grid(self, used, size, overrides):
        script_tuple = sl.get_context_zone(used, size, overrides or None)
        info = get_context_zone(used, size, ZoneThresholds(**overrides))
        assert script_tuple == (info.zone, info.color, info.recommendation)

    @pytest.mark.parametrize(
        ("used", "size", "overrides", "expected"),
        [
            (180_000, 1_000_000, {}, "Pricing"),
            (199_999, 1_000_000, {}, "Pricing"),
            (200_000, 1_000_000, {}, "Code"),
            (180_000, 1_000_000, {"zone_pricing_max": 170_000}, "Code"),
            (220_000, 1_000_000, {"zone_pricing_max": 230_000}, "Pricing"),
            (180_000, 1_000_000, {"zone_pricing_max": 150_000}, "Code"),
        ],
        ids=str,
    )
    def test_pricing_zone_grid(self, used, size, overrides, expected):
        """The Pricing band (plan_max, pricing_max) behaves identically on both
        sides, including the zone_pricing_max override end-to-end (#195)."""
        script_tuple = sl.get_context_zone(used, size, overrides or None)
        info = get_context_zone(used, size, ZoneThresholds(**overrides))
        assert script_tuple == (info.zone, info.color, info.recommendation)
        assert script_tuple[0] == info.zone == expected
        if expected == "Pricing":
            assert script_tuple[1] == info.color == "amber"
            assert script_tuple[2] == "Pricing tier increases — consider /compact"


# ---------------------------------------------------------------------------
# Rows: Pacman icons
# ---------------------------------------------------------------------------


class TestPacmanPairs:
    def test_pacman_icons_equal(self):
        assert sl.PACMAN_ICONS == PACMAN_ICONS

    @pytest.mark.parametrize("zone", ["Plan", "Pricing", "Code", "Dump", "ExDump", "Dead", "?"])
    def test_pacman_icon_grid(self, zone):
        assert sl.get_pacman_icon(zone) == get_pacman_icon(zone)

    def test_pricing_icon_and_recommendation_match_shared(self):
        """Pricing glyph + cost-aware recommendation are single-sourced: the
        standalone bindings equal the package and the vendored shared copy."""
        assert PACMAN_ICONS["Pricing"] == sl.PACMAN_ICONS["Pricing"] == "$"
        assert shared_module._ZONE_RECOMMENDATIONS["Pricing"] == sl._ZONE_RECOMMENDATIONS["Pricing"]
        assert "compact" in sl._ZONE_RECOMMENDATIONS["Pricing"].lower()


# ---------------------------------------------------------------------------
# Rows: tok/s compute / compaction detection
# ---------------------------------------------------------------------------

TPS_SAMPLE_SETS = [
    [],
    [(100, 0)],
    [(0, 0), (0, 0)],
    [(900, 1000), (800, 2500)],
    [(900, 1000), (800, 1000)],
    [(900, 0), (800, 2500)],
    [(900, 1000), (0, 2500)],
    [(900, 1000), (800, 2500), (700, 4000), (600, 5500)],
    [(0, 0), (900, 1000), (800, 2500), (700, 4000)],
    [(500, 500)] * 12,
]


class TestThroughputPairs:
    @pytest.mark.parametrize("window", [-1, 0, 1, 2, 3, 5, 11])
    @pytest.mark.parametrize("samples", TPS_SAMPLE_SETS, ids=str)
    def test_compute_tps_grid(self, samples, window):
        assert sl.compute_tps(list(samples), window=window) == compute_tps(
            list(samples), window=window
        )

    @pytest.mark.parametrize("unit", ["tok/s", "tokens/s"])
    @pytest.mark.parametrize("precision", [-3, 0, 1, 2, 11])
    def test_format_tps_grid(self, precision, unit):
        assert sl.format_tps(42.56123, precision, unit) == format_tps(42.56123, precision, unit)

    @pytest.mark.parametrize(
        "values",
        [[], [100], [100, 40], [100, 50], [100, 51], [0, 10], [100, 0, 90], [10, 9, 8]],
        ids=str,
    )
    @pytest.mark.parametrize("threshold", [None, 0.5, 0.1, 0.9])
    def test_detect_compaction_events_grid(self, values, threshold):
        if threshold is None:
            assert sl.detect_compaction_events(values) == detect_compaction_events(values)
        else:
            assert sl.detect_compaction_events(values, threshold) == detect_compaction_events(
                values, threshold
            )


# ---------------------------------------------------------------------------
# Row: Session ID validation (+ CSV field guards)
# ---------------------------------------------------------------------------

HOSTILE_IDS = [
    "../../evil",
    "a/b",
    "a\\b",
    "..hidden",
    "sess\0id",
    "comma,id",
    "line\nbreak",
    "tab\tid",
    "\x07bell",
    "del\x7fid",
]
CSV_UNSAFE_IDS = [
    "comma,id",
    "line\nbreak",
    "tab\tid",
    "\x07bell",
    "del\x7fid",
]
NON_STRING_IDS = [123, 4.2, True, None, {"k": 1}, ["a"], ("x",)]
SAFE_IDS = ["abc", "good-session-1", "parity_✓"]


class TestValidationPairs:
    @pytest.mark.parametrize("session_id", SAFE_IDS)
    def test_validate_session_id_accepts_safe(self, session_id):
        assert sl._validate_session_id(session_id) is None
        assert _validate_session_id(session_id) is None

    @pytest.mark.parametrize("session_id", HOSTILE_IDS + NON_STRING_IDS)
    def test_validate_session_id_grid(self, session_id):
        with pytest.raises(ValueError) as sl_err:
            sl._validate_session_id(session_id)
        with pytest.raises(ValueError) as pkg_err:
            _validate_session_id(session_id)
        assert str(sl_err.value) == str(pkg_err.value)

    @pytest.mark.parametrize(
        ("field", "value"),
        [("session_id", v) for v in CSV_UNSAFE_IDS]
        + [("model_id", v) for v in CSV_UNSAFE_IDS]
        + [("model_id", v) for v in NON_STRING_IDS],
    )
    def test_validate_csv_field_grid(self, field, value):
        with pytest.raises(ValueError) as sl_err:
            sl._validate_csv_field(field, value)
        with pytest.raises(ValueError) as pkg_err:
            _validate_csv_field(field, value)
        assert str(sl_err.value) == str(pkg_err.value)

    @pytest.mark.parametrize("value", ["a/b", "..hidden", "a\\b"])
    def test_validate_csv_field_accepts_path_like(self, value):
        """Path-traversal patterns are rejected by the session-id validator,
        but they are legal content for a raw CSV string field."""
        assert sl._validate_csv_field("model_id", value) is None
        assert _validate_csv_field("model_id", value) is None

    @pytest.mark.parametrize(
        "value",
        ["ok", "a,b", "a\nb", "a\tb", "a\x7fb", "a\x00b", "", "safe/path-ish"],
    )
    def test_csv_unsafe_reason_grid(self, value):
        assert sl._csv_unsafe_reason(value) == _csv_unsafe_reason(value)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("/home/x,/y", "/home/x_/y"),
            ("a\nb", "a_b"),
            ("a\x7f", "a_"),
            ("\x00", "_"),
            ("/ok/path", "/ok/path"),
            ("", ""),
        ],
    )
    def test_sanitize_workspace_dir_grid(self, value, expected):
        assert sl._sanitize_workspace_dir(value) == expected
        assert _sanitize_workspace_dir(value) == expected

    def test_sanitize_non_string_yields_empty(self):
        assert sl._sanitize_workspace_dir(123) == ""
        assert _sanitize_workspace_dir(None) == ""


# ---------------------------------------------------------------------------
# Row: External-input extraction
# ---------------------------------------------------------------------------


class TestExtractionPair:
    @pytest.mark.parametrize(
        ("data", "key", "default"),
        [
            ({"k": None}, "k", "dflt"),
            ({}, "k", "dflt"),
            ({"k": "v"}, "k", "dflt"),
            ({"k": "v"}, "missing", None),
            (None, "k", "dflt"),
            ("not-a-dict", "k", "dflt"),
            ([1, 2], "k", 0),
        ],
        ids=str,
    )
    def test_extract_grid(self, data, key, default):
        assert sl._extract(data, key, default) == pkg._extract(data, key, default)


# ---------------------------------------------------------------------------
# Row: project_dir trust gate
# ---------------------------------------------------------------------------


class TestProjectDirGatePair:
    @pytest.mark.parametrize(
        "raw",
        [None, "", "/nonexistent/dir/xyz", "relative/nonexistent", 123],
    )
    def test_resolve_project_dir_grid(self, raw, tmp_path):
        assert sl._resolve_project_dir(raw) is None
        assert pkg._resolve_project_dir(raw) is None

    def test_resolve_project_dir_existing_agrees(self, tmp_path):
        sl_out = sl._resolve_project_dir(str(tmp_path))
        pkg_out = pkg._resolve_project_dir(str(tmp_path))
        assert sl_out is not None and pkg_out is not None
        assert Path(sl_out) == Path(pkg_out) == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Rows: Git info / PR lookup / PR cache
# ---------------------------------------------------------------------------


class TestGitInfoPair:
    def test_git_info_non_git_directory(self, tmp_path):
        assert sl.get_git_info(str(tmp_path)) == ""
        assert get_git_info(tmp_path) == ""

    def test_git_info_bogus_pointer_file(self, tmp_path):
        """A `.git` pointer file with garbage content must fail cleanly on
        both sides (worktree acceptance without a real link target)."""
        (tmp_path / ".git").write_text("gitdir: /nowhere/real\n", encoding="utf-8")
        assert sl.get_git_info(str(tmp_path)) == ""
        assert get_git_info(tmp_path) == ""

    @pytest.mark.parametrize("dirty_files", [0, 2], ids=["clean", "dirty"])
    def test_git_info_parity(self, tmp_path, dirty_files):
        import subprocess as sp

        env = os.environ.copy()
        sp.run(["git", "init", "-q", str(tmp_path)], check=True, env=env)
        cfg = ["-c", "user.email=t@t", "-c", "user.name=t"]
        sp.run(
            ["git", *cfg, "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=tmp_path,
            check=True,
            env=env,
        )
        for i in range(dirty_files):
            (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")

        sl_out = sl.get_git_info(str(tmp_path))
        pkg_out = get_git_info(tmp_path)
        assert sl_out == pkg_out
        visible = ANSI_RE.sub("", sl_out)
        if dirty_files:
            assert f"[{dirty_files}]" in visible
        else:
            assert "[" not in visible


class TestPrNumberPair:
    def test_pr_number_lookup_unavailable_gh(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sl.shutil, "which", lambda _: None)
        monkeypatch.setattr("claude_statusline.core.git.shutil.which", lambda _: None)
        assert sl.get_pr_number(str(tmp_path)) == ""
        assert _get_pr_number(tmp_path) == ""


class TestPrCachePair:
    def test_pr_cache_roundtrip_and_cross_read(self, isolated_home):
        """Both copies must read and write the same cache file format."""
        cache_dir = isolated_home / ".claude" / "statusline"
        cache_dir.mkdir(parents=True, exist_ok=True)

        sl_file = sl._pr_cache_file()
        pkg_file = _pr_cache_file()
        assert Path(sl_file) == cache_dir / "pr_number_cache.json"
        assert pkg_file == cache_dir / "pr_number_cache.json"

        sl._pr_cache_set("branch-a", "#71")
        assert sl._pr_cache_get("branch-a") == "#71"
        assert _pr_cache_get("branch-a") == "#71"

        _pr_cache_set("branch-b", "#72")
        assert _pr_cache_get("branch-b") == "#72"
        assert sl._pr_cache_get("branch-b") == "#72"

        # Expired negative entry is a miss on both sides.
        _pr_cache_set("branch-c", "", ttl=-1)
        assert _pr_cache_get("branch-c") is None
        assert sl._pr_cache_get("branch-c") is None

        # Corrupt cache file is a miss (never raises) on both sides.
        pkg_file.write_text("{not json", encoding="utf-8")
        assert _pr_cache_get("branch-a") is None
        assert sl._pr_cache_get("branch-a") is None


class TestBranchCachePair:
    """F-PERF-003: dir-keyed TTL branch cache shared by both implementations."""

    def test_branch_cache_constants_equal(self):
        import claude_statusline._shared as shared

        assert sl._BRANCH_CACHE_TTL_SECONDS == shared._BRANCH_CACHE_TTL_SECONDS == 10
        assert (
            sl._BRANCH_CACHE_NEGATIVE_TTL_SECONDS == shared._BRANCH_CACHE_NEGATIVE_TTL_SECONDS == 5
        )

    def test_branch_cache_roundtrip_and_cross_read(self, tmp_path):
        """Both copies read/write the same (autouse-redirected) cache file."""
        # The autouse conftest fixture points both implementations at ONE
        # temp file whose name carries the production name.
        assert Path(sl._branch_cache_file()) == Path(shared_module._branch_cache_file())
        assert Path(sl._branch_cache_file()).name == "branch_cache.json"

        sl._branch_cache_set("/repo-a", "main")
        assert sl._branch_cache_get("/repo-a") == "main"
        assert shared_module._branch_cache_get("/repo-a") == "main"

        shared_module._branch_cache_set("/repo-b", "feature")
        assert shared_module._branch_cache_get("/repo-b") == "feature"
        assert sl._branch_cache_get("/repo-b") == "feature"

        # Expired negative entry is a miss on both sides.
        sl._branch_cache_set("/repo-c", "", ttl=-1)
        assert sl._branch_cache_get("/repo-c") is None
        assert shared_module._branch_cache_get("/repo-c") is None

    def test_pr_number_shares_branch_cache(self, tmp_path, isolated_home, monkeypatch):
        """The PR lookup must consume the cached branch, not re-run rev-parse.

        With the branch cache warm, neither implementation issues any
        rev-parse; with it cold, exactly one runs even though both the
        git-info segment and the PR lookup need the branch (down from two).
        """
        repo = _make_git_repo(tmp_path / "shared-branch-repo")

        calls = {"rev_parse": 0}

        def counting_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                calls["rev_parse"] += 1
                return subprocess.CompletedProcess(cmd, 0, stdout="main\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

        monkeypatch.setattr("subprocess.run", counting_run)
        monkeypatch.setattr(sl.shutil, "which", lambda _: None)
        monkeypatch.setattr("claude_statusline.core.git.shutil.which", lambda _: None)

        # Warm the cache through the script side; package side must then hit
        # the same file-backed entry without spawning anything.
        sl.get_git_info(str(repo))
        sl.get_pr_number(str(repo))
        first_count = calls["rev_parse"]
        get_git_info(repo)
        _get_pr_number(repo)
        assert first_count == 1, f"expected one cold rev-parse, saw {first_count}"
        assert calls["rev_parse"] == 1, "warm-cache git/PR lookups must not rev-parse"


# ---------------------------------------------------------------------------
# Row: Config parsing (incl. tok/s config keys)
# ---------------------------------------------------------------------------

FULL_CONF = """\
autocompact=true
token_detail=false
show_delta=false
show_session=false
show_io_tokens=false
reduced_motion=true
show_mi=true
mi_curve_beta=1.7
show_tps=true
tps_precision=2
tps_unit=tokens/s
tps_window=7
show_pr=false
show_cost=false
show_effort=false
show_pacman=false
suppress_setup_hint=true
color_green=#7dcfff
color_yellow=#e0af68
color_red=#f7768e
color_project_name=bright_cyan
color_branch_name=bright_magenta
color_mi_score=#ff9e64
color_separator=dim
color_tps=#6ED7D2
color_cost=#FFF8DC
color_model=#C0C0C0
color_session=#8B8682
zone_std_dump_ratio=0.45
zone_std_warn_buffer=40000
zone_std_hard_limit=0.65
zone_std_dead_ratio=0.72
zone_pricing_max=180000
large_model_threshold=600000
compaction_drop_threshold=0.6
compact_mi_warn_threshold=0.55
"""


def write_conf(home, text):
    conf = home / ".claude" / "statusline.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(text, encoding="utf-8")
    return conf


class TestConfigParsingPair:
    def test_config_parsing_parity(self, tmp_path, monkeypatch):
        conf = write_conf(tmp_path, FULL_CONF)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        scfg = sl.read_config()
        pcfg = Config.load(conf)

        boolean_int_str_keys = [
            "autocompact",
            "token_detail",
            "show_delta",
            "show_session",
            "show_io_tokens",
            "reduced_motion",
            "show_mi",
            "show_tps",  # tok/s config
            "show_pr",
            "show_cost",
            "show_effort",
            "show_pacman",
            "suppress_setup_hint",
        ]
        for key in boolean_int_str_keys:
            assert scfg[key] == getattr(pcfg, key), key

        # Numeric/tok-s config keys
        assert scfg["mi_curve_beta"] == pcfg.mi_curve_beta
        assert scfg["tps_precision"] == pcfg.tps_precision
        assert scfg["tps_unit"] == pcfg.tps_unit
        assert scfg["tps_window"] == pcfg.tps_window

        # Colors: identical slot -> ANSI mappings
        assert scfg["colors"] == pcfg.color_overrides

        # Zone overrides
        assert scfg["zone_config"]["zone_std_dump_ratio"] == pcfg.zone_std_dump_ratio
        assert scfg["zone_config"]["zone_std_warn_buffer"] == pcfg.zone_std_warn_buffer
        assert scfg["zone_config"]["zone_std_hard_limit"] == pcfg.zone_std_hard_limit
        assert scfg["zone_config"]["zone_std_dead_ratio"] == pcfg.zone_std_dead_ratio
        assert scfg["zone_config"]["zone_pricing_max"] == pcfg.zone_pricing_max == 180_000
        assert scfg["zone_config"]["large_model_threshold"] == pcfg.large_model_threshold

        # Compaction constants
        assert scfg["compaction_drop_threshold"] == pcfg.compaction_drop_threshold
        assert scfg["compact_mi_warn_threshold"] == pcfg.compact_mi_warn_threshold

    def test_zone_1m_and_unit_overrides_agree(self, tmp_path, monkeypatch):
        """Customized config: 1M-class integer thresholds and remaining keys
        parse identically through both parsers (Task 5.3 acceptance)."""
        conf = write_conf(
            tmp_path,
            FULL_CONF
            + "zone_1m_plan_max=70000\n"
            + "zone_1m_code_max=100000\n"
            + "zone_1m_dump_max=250000\n"
            + "zone_1m_xdump_max=275000\n"
            + "color_context_length=bold_white\n"
            + "color_delta=#FFF8DC\n",
        )
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        scfg = sl.read_config()
        pcfg = Config.load(conf)

        for key in (
            "zone_1m_plan_max",
            "zone_pricing_max",
            "zone_1m_code_max",
            "zone_1m_dump_max",
            "zone_1m_xdump_max",
        ):
            assert scfg["zone_config"][key] == getattr(pcfg, key), key
        # Per-property color slots land in the same override map on both sides.
        assert scfg["colors"]["context_length"] == pcfg.color_overrides["context_length"]
        assert scfg["colors"]["delta"] == pcfg.color_overrides["delta"]
        # And the whole shared key-table contract still matches.
        assert sl._COLOR_KEYS == PKG_COLOR_KEYS

    def test_defaults_with_comment_only_conf(self, isolated_home):
        scfg = sl.read_config()
        pcfg = Config.load(isolated_home / ".claude" / "statusline.conf")
        for key in (
            "autocompact",
            "token_detail",
            "show_delta",
            "show_mi",
            "show_tps",
            "show_cost",
            "show_effort",
            "show_pacman",
            "suppress_setup_hint",
        ):
            assert scfg[key] == getattr(pcfg, key), key
        assert scfg["tps_precision"] == pcfg.tps_precision == 1
        assert scfg["tps_unit"] == pcfg.tps_unit == "tok/s"
        assert scfg["tps_window"] == pcfg.tps_window == 5
        assert scfg["colors"] == {} and pcfg.color_overrides == {}
        assert scfg["zone_config"] == {}

    @pytest.mark.parametrize(
        "bad_line",
        [
            "tps_precision=-3",
            "tps_precision=abc",
            "tps_window=0",
            "tps_window=x",
            "zone_std_dump_ratio=1.5",
            "large_model_threshold=-4",
            "compaction_drop_threshold=0",
            "mi_curve_beta=zzz",
            "color_mi_score=not-a-color",
        ],
    )
    def test_invalid_values_fall_back_identically(self, bad_line, isolated_home):
        write_conf(isolated_home, COMMENT_ONLY_CONF + bad_line + "\n")
        scfg = sl.read_config()
        pcfg = Config.load(isolated_home / ".claude" / "statusline.conf")
        key = bad_line.split("=")[0]
        if key.startswith("color_"):
            slot = PKG_COLOR_KEYS[key]
            assert slot not in scfg["colors"]
            assert slot not in pcfg.color_overrides
        elif key in (
            "zone_std_dump_ratio",
            "zone_std_warn_buffer",
            "zone_std_hard_limit",
            "zone_std_dead_ratio",
            "large_model_threshold",
        ):
            assert key not in scfg["zone_config"]
            assert getattr(pcfg, key) == 0  # 0 = use built-in default on both sides
        elif key == "compaction_drop_threshold":
            assert scfg[key] == getattr(pcfg, key)
        elif key == "mi_curve_beta":
            assert scfg[key] == pcfg.mi_curve_beta == 0.0
        else:
            assert scfg[key] == getattr(pcfg, key)


# ---------------------------------------------------------------------------
# Row: State-row parsing (Task 5.3 — parse_state_row)
# ---------------------------------------------------------------------------


class TestStateRowParsingPair:
    """parse_state_row replaces index-magic CSV access at both script read paths."""

    ROWS = [
        # (line, expected) — expected None means "row skipped by both paths"
        ("1700000000,1,2,3,4,5,6,0.5,7,8,s,m,w,9,12345\n", 4),
        ("1700000000,1,2,3,4\n", None),  # minimal 5-field row: no dur -> api 0
        ("1700000000,1,2,3,4,5\n", None),
        ("\n", None),  # blank noise row
        ("   \n", None),
        ("1700000000,1000\n", None),  # legacy 2-field row
        ("garbage\n", None),
        ("1,2,3,x,5,6,7,8,9,10,s,m,w,14,15\n", None),  # non-int numeric field
    ]

    @pytest.mark.parametrize(("line", "_"), ROWS, ids=lambda v: repr(v)[:30])
    def test_parse_state_row_grid(self, line, _):
        from claude_statusline._shared import parse_state_row as pkg_parse

        assert sl.parse_state_row(line) == pkg_parse(line)

    @pytest.mark.parametrize(
        ("line", "out", "dur"),
        [
            ("1700000000,1,2,3,4,5,6,0.5,7,8,s,m,w,9,12345\n", 4, 12345),
            ("1700000000,1,2,3,4\n", 4, 0),  # legacy row without index 14
            ("1700000000,1,2,3,4,5,6\n", 4, 0),
        ],
        ids=str,
    )
    def test_parse_state_row_tail_fields(self, line, out, dur):
        parsed = sl.parse_state_row(line)
        assert parsed is not None
        assert parsed["output_tokens"] == out
        assert parsed["api_duration_ms"] == dur

    def test_used_tokens_agree_with_state_entry(self):
        """For valid rows the parsed usage equals StateEntry.current_used_tokens."""
        line = "1700000000,1,2,300,4,50,6,0.5,7,8,s,m,w,9,12345\n"
        entry = StateEntry.from_csv_line(line)
        parsed = sl.parse_state_row(line)
        assert parsed is not None and entry is not None
        used = parsed["current_input_tokens"] + parsed["cache_creation"] + parsed["cache_read"]
        assert used == entry.current_used_tokens == 356

    def test_invalid_rows_yield_none_on_both_sides(self):
        for bad in ("a,b,c,d,e,f\n", "1,2,3\n", ""):
            assert sl.parse_state_row(bad) is None


# ---------------------------------------------------------------------------
# Row: State rotation
# ---------------------------------------------------------------------------


def seed_state_file(path: Path, n_lines: int) -> list[str]:
    lines = [f"{1700000000 + i},1,2,3,4,5,6,0.01,7,8,s,m,w,9,{i}\n" for i in range(n_lines)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return lines


class TestRotationPair:
    @pytest.mark.parametrize("n_lines", [100, PKG_ROTATION_THRESHOLD, PKG_ROTATION_THRESHOLD + 1])
    def test_maybe_rotate_keeps_recent_tail(self, tmp_path, n_lines, monkeypatch):
        state = tmp_path / "statusline.rot.state"
        original = seed_state_file(state, n_lines)

        sl.maybe_rotate_state_file(state)

        at_or_below = n_lines <= PKG_ROTATION_THRESHOLD
        expected = original if at_or_below else original[-PKG_ROTATION_KEEP:]
        assert state.read_text().splitlines(keepends=True) == expected

        # Same behavior from the package-side helper on a fresh file.
        # NOTE: StateFile("rot") so the property path matches the seeded name.
        state2_dir = tmp_path / "pkg"
        original2 = seed_state_file(state2_dir / "statusline.rot.state", n_lines)
        monkeypatch.setattr(StateFile, "STATE_DIR", state2_dir)
        sf = StateFile("rot")
        sf._maybe_rotate()
        kept2 = original2 if at_or_below else original2[-PKG_ROTATION_KEEP:]
        assert (
            state2_dir.joinpath("statusline.rot.state").read_text().splitlines(keepends=True)
            == kept2
        )

    def test_rotate_locked_via_append_cross_format(self, tmp_path, monkeypatch):
        """Package append_entry rotates past the threshold exactly like the
        standalone locked write-site (same kept-tail semantics)."""
        state_dir = tmp_path / "statedir"
        state = seed_state_file(state_dir / "statusline.pkgrot.state", PKG_ROTATION_THRESHOLD + 3)
        monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        entry_obj = StateEntry(
            timestamp=1700009999,
            total_input_tokens=1,
            total_output_tokens=2,
            current_input_tokens=3,
            current_output_tokens=4,
            cache_creation=5,
            cache_read=6,
            cost_usd=0.5,
            lines_added=7,
            lines_removed=8,
            session_id="pkgrot",
            model_id="m",
            workspace_project_dir="/w",
            context_window_size=9,
            api_duration_ms=10,
        )
        StateFile("pkgrot").append_entry(entry_obj)

        lines = state_dir.joinpath("statusline.pkgrot.state").read_text().splitlines(keepends=True)
        assert len(lines) == PKG_ROTATION_KEEP
        assert lines[-1].startswith("1700009999,")
        assert lines[:-1] == state[-PKG_ROTATION_KEEP + 1 :]

    def test_lock_unlock_noop_without_fcntl(self):
        """Both lock helpers are best-effort no-ops when fcntl is absent.

        Lock/unlock bodies are single-sourced in ``claude_statusline._shared``
        (Task 5.2): the package re-exports them via ``core.state`` and the
        standalone script binds them from its loaded shared module, so one
        patch covers both sides.
        """

        class FakeFH:
            def fileno(self):
                return 0

        import scripts.statusline as sl_mod

        import claude_statusline._shared as shared

        assert sl_mod._lock_state_file.__module__ == shared.__name__
        assert (
            __import__(
                "claude_statusline.core.state", fromlist=["_lock_state_file"]
            )._lock_state_file
            is shared._lock_state_file
        )

        saved = shared.fcntl
        shared.fcntl = None
        try:
            shared._lock_state_file(FakeFH())
            shared._unlock_state_file(FakeFH())
            sl_mod._lock_state_file(FakeFH())
            sl_mod._unlock_state_file(FakeFH())
        finally:
            shared.fcntl = saved


# ---------------------------------------------------------------------------
# Row: Legacy-state migration
# ---------------------------------------------------------------------------


class TestLegacyMigrationPair:
    @staticmethod
    def _seed(old_dir: Path, state_dir: Path):
        old_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        moved = old_dir / "statusline.old1.state"
        moved.write_text("1,2\n", encoding="utf-8")
        duplicate_target = state_dir / "statusline.dup.state"
        duplicate_target.write_text("existing\n", encoding="utf-8")
        dup_source = old_dir / "statusline.dup.state"
        dup_source.write_text("incoming\n", encoding="utf-8")
        keeper = old_dir / "unrelated.txt"
        keeper.write_text("keep\n", encoding="utf-8")
        not_a_file = old_dir / "statusline.dir.state"
        not_a_file.mkdir()
        return {p.name for p in (moved, duplicate_target, dup_source, keeper)}

    def test_legacy_migration_parity(self, tmp_path, monkeypatch):
        expected_names = self._seed(tmp_path / "old-sl", tmp_path / "state-sl")
        sl._migrate_legacy_state_files(tmp_path / "state-sl", tmp_path / "old-sl")

        expected_names_pkg = self._seed(tmp_path / "old-pkg", tmp_path / "state-pkg")
        assert expected_names_pkg == expected_names
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path / "state-pkg")
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old-pkg")
        sf = StateFile.__new__(StateFile)
        sf.session_id = None
        sf._migrate_old_files()

        sl_after = sorted(p.name for p in (tmp_path / "state-sl").iterdir())
        pkg_after = sorted(p.name for p in (tmp_path / "state-pkg").iterdir())
        assert sl_after == pkg_after
        assert "statusline.old1.state" in sl_after
        assert "statusline.dir.state" not in sl_after
        assert (tmp_path / "old-sl" / "unrelated.txt").exists()
        assert not (tmp_path / "old-sl" / "statusline.old1.state").exists()
        assert not (tmp_path / "old-sl" / "statusline.dup.state").exists()

    def test_migrate_sentinel_prevents_repeat_sweep(self, tmp_path, monkeypatch):
        """F-PERF-005: after one clean pass the sentinel skips the glob/stat
        sweep entirely — on both implementations."""

        # Package side: StateFile.__init__ runs the migration once.
        class _OldDir:
            def __init__(self):
                self.calls = 0

            def glob(self, pattern):
                self.calls += 1
                return []

        old_pkg = _OldDir()
        state_pkg = tmp_path / "state-pkg"
        state_pkg.mkdir(parents=True)
        monkeypatch.setattr(StateFile, "STATE_DIR", state_pkg)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", old_pkg)

        StateFile("sentinel-a")
        assert old_pkg.calls == 1
        assert (state_pkg / shared_module.LEGACY_MIGRATION_MARKER).exists()

        StateFile("sentinel-b")
        assert old_pkg.calls == 1, "sentinel must prevent the repeat sweep"

        # Standalone side: direct double invocation.
        state_sl = tmp_path / "state-sl"
        old_sl = tmp_path / "old-sl"
        state_sl.mkdir(parents=True)
        old_sl.mkdir(parents=True)

        import glob as glob_module

        real_glob = glob_module.glob
        calls = {"n": 0}

        def counting_glob(pattern):
            calls["n"] += 1
            return real_glob(pattern)

        monkeypatch.setattr(glob_module, "glob", counting_glob)

        sl._migrate_legacy_state_files(state_sl, old_sl)
        assert calls["n"] == 1
        assert (state_sl / shared_module.LEGACY_MIGRATION_MARKER).exists()

        sl._migrate_legacy_state_files(state_sl, old_sl)
        assert calls["n"] == 1, "sentinel must prevent the repeat sweep"


# ---------------------------------------------------------------------------
# Row: Render hot-path performance (#149 / #150 — F-PERF-001/002/003/005)
# ---------------------------------------------------------------------------


class _CountingOpen:
    """builtins.open stand-in recording every opened path and how many bytes
    each binary read returned — proves O(window) tail-read behavior."""

    def __init__(self):
        self.total_binary_bytes = 0
        self.opened_paths = []

    def __call__(self, file, mode="r", *args, **kwargs):
        self.opened_paths.append(os.fspath(file))
        fh = builtins_open(file, mode, *args, **kwargs)
        if "b" in mode and "r" in mode:
            return _CountingBinaryReader(fh, self)
        return fh


class _CountingBinaryReader:
    def __init__(self, fh, counter):
        self._fh = fh
        self._counter = counter

    def read(self, n=-1):
        data = self._fh.read(n)
        self._counter.total_binary_bytes += len(data)
        return data

    def seek(self, *args):
        return self._fh.seek(*args)

    def tell(self):
        return self._fh.tell()

    def close(self):
        return self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self._fh.close()


builtins_open = builtins.open


def _state_rows(n_lines):
    return [f"{1700000000 + i},1,2,3,4,5,6,0.01,7,8,s,m,w,9,{i}\n" for i in range(n_lines)]


class TestRotationByteGate:
    """F-PERF-002: stat().st_size gates the O(filesize) rotation scan."""

    @staticmethod
    def _write(path, rows):
        # Byte-exact write (no platform newline translation): the byte-gate
        # boundary cases assert raw sizes/contents, so a CRLF-translation
        # text-mode write would shift every row by one byte on Windows.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes("".join(rows).encode("utf-8"))

    def test_rotate_byte_gate_skips_scan_below_floor(self, tmp_path, monkeypatch):
        floor = shared_module._ROTATION_SCAN_FLOOR_BYTES
        rows = [f"{1700000000 + i},1\n" for i in range(900)]  # ~13 KB < floor
        state = tmp_path / "statusline.gate.state"
        self._write(state, rows)
        before = state.stat().st_size
        assert before < floor

        # Standalone side.
        sl.maybe_rotate_state_file(str(state))

        # Package side (fresh copy, same shape). Construct first so the
        # one-time migration/marker write is not attributed to the gate.
        state_dir = tmp_path / "pkg"
        self._write(state_dir / "statusline.gate.state", rows)
        monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()
        sf = StateFile("gate")

        counter = _CountingOpen()
        monkeypatch.setattr(builtins, "open", counter)
        sf._maybe_rotate()

        assert counter.opened_paths == [], "byte gate must skip ALL reads below the floor"
        assert state.read_bytes() == ("".join(rows)).encode()
        assert (state_dir / "statusline.gate.state").read_bytes() == state.read_bytes(), (
            "both sides byte-identical"
        )

    @pytest.mark.parametrize(
        ("rows_spec", "expect_rotation"),
        [
            ("under_floor_max_lines", False),  # 9,999 "x\n" + "x" = 19,999 B
            ("at_threshold", False),  # 10,000 "x\n" = 20,000 B, exactly THRESHOLD
            ("over_threshold", True),  # 10,001 "x\n" = 20,002 B -> rotate
        ],
    )
    def test_rotate_byte_gate_boundary_tiny_rows(
        self, tmp_path, monkeypatch, rows_spec, expect_rotation
    ):
        """The provable floor never suppresses genuine rotation: even the
        worst case (1-byte rows) rotates iff lines exceed the threshold,
        and outputs stay byte-identical between the implementations."""
        if rows_spec == "under_floor_max_lines":
            rows = ["x\n"] * (PKG_ROTATION_THRESHOLD - 1) + ["x"]
        elif rows_spec == "at_threshold":
            rows = ["x\n"] * PKG_ROTATION_THRESHOLD
        else:
            rows = ["x\n"] * (PKG_ROTATION_THRESHOLD + 1)

        # Standalone side.
        sl_state = tmp_path / "sl.state"
        self._write(sl_state, rows)
        sl.maybe_rotate_state_file(str(sl_state))
        sl_after = sl_state.read_text().splitlines(keepends=True)

        # Package side.
        pkg_dir = tmp_path / "pkg"
        self._write(pkg_dir / "statusline.pkg.state", rows)
        monkeypatch.setattr(StateFile, "STATE_DIR", pkg_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()
        StateFile("pkg")._maybe_rotate()
        pkg_after = (pkg_dir / "statusline.pkg.state").read_text().splitlines(keepends=True)

        expected_keep = PKG_ROTATION_KEEP if expect_rotation else len(rows)
        assert len(sl_after) == expected_keep
        assert sl_after == pkg_after, "rotation output must be byte-identical"
        if expect_rotation:
            assert sl_after == rows[-PKG_ROTATION_KEEP:]

    def test_rotate_scan_floor_constant_shared(self):
        assert sl._ROTATION_SCAN_FLOOR_BYTES == shared_module._ROTATION_SCAN_FLOOR_BYTES
        assert shared_module._ROTATION_SCAN_FLOOR_BYTES == 2 * PKG_ROTATION_THRESHOLD


class TestWindowedTailReads:
    """F-PERF-001: tail reads touch O(window) bytes, not O(filesize)."""

    def test_read_tail_window_bounded_bytes(self, tmp_path, monkeypatch):

        state_dir = tmp_path / "statedir"
        state_path = state_dir / "statusline.tail.state"
        seed_state_file(state_path, 4000)
        assert state_path.stat().st_size > shared_module.STATE_TAIL_WINDOW_BYTES

        monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()
        sf = StateFile("tail")

        n = 12
        counter = _CountingOpen()
        monkeypatch.setattr(builtins, "open", counter)

        entries = sf.read_tail(n)
        baseline = sf.read_history()[-n:]

        assert entries == baseline, "windowed tail must equal read_history()[-n:]"
        assert counter.total_binary_bytes <= shared_module.STATE_TAIL_WINDOW_BYTES + 16, (
            f"read {counter.total_binary_bytes} bytes — not O(window)"
        )
        assert counter.total_binary_bytes * 2 < state_path.stat().st_size

    def test_read_last_entry_window_bounded_bytes(self, tmp_path, monkeypatch):
        state_dir = tmp_path / "statedir"
        seed_state_file(state_dir / "statusline.last.state", 4000)
        monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()
        sf = StateFile("last")

        counter = _CountingOpen()
        monkeypatch.setattr(builtins, "open", counter)

        entry = sf.read_last_entry()
        assert entry is not None
        assert entry.timestamp == 1700000000 + 3999
        assert counter.total_binary_bytes <= shared_module.STATE_TAIL_WINDOW_BYTES + 16

    def test_read_tail_fallback_matches_full_read(self, tmp_path, monkeypatch):
        """A window too small to satisfy the request falls back to an exact
        full read (junk head forces the miss)."""
        from claude_statusline.core import state as state_mod

        state_dir = tmp_path / "statedir"
        state_dir.mkdir(parents=True)
        junk = ["not a csv row\n"] * 200
        good = seed_state_file(state_dir / "statusline.fb.state", 60)
        (state_dir / "statusline.fb.state").write_text(
            "".join(junk) + "".join(good), encoding="utf-8"
        )
        monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()
        sf = StateFile("fb")

        monkeypatch.setattr(state_mod, "STATE_TAIL_WINDOW_BYTES", 256)
        entries = sf.read_tail(20)
        assert entries == sf.read_history()[-20:]
        last = sf.read_last_entry()
        assert last == sf.read_history()[-1]

    def test_read_last_entry_fallback_past_blank_tail(self, tmp_path, monkeypatch):
        """A window consisting only of trailing blank lines falls back."""
        from claude_statusline.core import state as state_mod

        state_dir = tmp_path / "statedir"
        state_dir.mkdir(parents=True)
        path = state_dir / "statusline.blank.state"
        good = seed_state_file(path, 50)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n\n\n")
        monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()
        sf = StateFile("blank")

        monkeypatch.setattr(state_mod, "STATE_TAIL_WINDOW_BYTES", 64)
        entry = sf.read_last_entry()
        assert entry is not None
        assert entry.timestamp == int(good[-1].split(",")[0])

    def test_load_state_history_window_bounded_bytes(self, tmp_path, monkeypatch):
        """Standalone twin: bounded window read for delta + tok/s tail."""
        state_path = tmp_path / "history.state"
        seed_state_file(state_path, 4000)
        assert state_path.stat().st_size > sl.STATE_TAIL_WINDOW_BYTES

        counter = _CountingOpen()
        monkeypatch.setattr(builtins, "open", counter)

        has_prev, prev_tokens, samples = sl._load_state_history(str(state_path), True, 5)

        assert has_prev is True
        assert len(samples) == sl._tps_tail_size(5)
        # Delta source is the literal last row: cur_in[3]+cache_create[5]+cache_read[6].
        assert prev_tokens == 3 + 5 + 6
        last_row = _state_rows(4000)[-1].split(",")
        assert samples[-1] == (int(last_row[4]), int(last_row[14]))
        assert counter.total_binary_bytes <= sl.STATE_TAIL_WINDOW_BYTES + 16
        assert counter.total_binary_bytes * 2 < state_path.stat().st_size

    def test_load_state_history_fallback_matches_full_pass(self, tmp_path, monkeypatch):
        """Shrunk window cannot cover the tok/s tail -> exact full-read redo."""
        state_path = tmp_path / "fb.state"
        seed_state_file(state_path, 400)
        _, big_prev_tokens, big_samples = sl._load_state_history(str(state_path), True, 5)

        monkeypatch.setattr(sl, "STATE_TAIL_WINDOW_BYTES", 128)
        has_prev, prev_tokens, samples = sl._load_state_history(str(state_path), True, 5)

        assert has_prev is True
        assert (prev_tokens, samples) == (big_prev_tokens, big_samples)
        assert len(samples) == sl._tps_tail_size(5)

    def test_windowed_reads_agree_across_implementations(self, tmp_path, monkeypatch):
        """Both implementations produce identical results on fixture states
        regardless of window size (parity of the windowing itself)."""
        from claude_statusline.core import state as state_mod

        rows = _state_rows(150)
        state_dir = tmp_path / "statedir"
        state_dir.mkdir(parents=True)
        path = state_dir / "statusline.agree.state"
        path.write_text("".join(rows), encoding="utf-8")

        monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()
        sf = StateFile("agree")

        pkg_entries_big = sf.read_tail(10)
        pkg_last_big = sf.read_last_entry()
        sl_big = sl._load_state_history(str(path), True, 5)

        monkeypatch.setattr(state_mod, "STATE_TAIL_WINDOW_BYTES", 512)
        monkeypatch.setattr(sl, "STATE_TAIL_WINDOW_BYTES", 512)

        pkg_entries_small = sf.read_tail(10)
        pkg_last_small = sf.read_last_entry()
        sl_small = sl._load_state_history(str(path), True, 5)

        assert pkg_entries_small == pkg_entries_big
        assert pkg_last_small == pkg_last_big
        assert sl_small == sl_big


class TestSubprocessBudget:
    """F-PERF-003: per-render subprocess fan-out assertions."""

    @staticmethod
    def _install_counters(monkeypatch):
        """Count spawned processes via Popen only — subprocess.run delegates
        to Popen internally, so patching both would double-count."""
        counters = {"rev_parse": 0, "git": 0}
        real_popen = subprocess.Popen

        def counting_popen(cmd, *args, **kwargs):
            if cmd and cmd[0] == "git":
                counters["git"] += 1
                if "rev-parse" in cmd:
                    counters["rev_parse"] += 1
            return real_popen(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", counting_popen)
        # Keep the PR lookup offline regardless of the local gh install.
        monkeypatch.setattr(sl.shutil, "which", lambda name: None if name == "gh" else name)
        return counters

    def test_subprocess_count_render_budget(self, tmp_path, isolated_home, monkeypatch, capsys):
        """Explicit N: cold render runs exactly one rev-parse (down from two);
        second render within TTL runs zero; the capped porcelain count stays
        live on both renders."""
        repo = _make_git_repo(tmp_path / "budget-repo", dirty_files=2)
        payload = build_payload(repo)

        counters = self._install_counters(monkeypatch)

        render_package(payload, monkeypatch, capsys, isolated_home)
        first_rev = counters["rev_parse"]
        first_git_total = counters["git"]

        render_package(payload, monkeypatch, capsys, isolated_home)
        second_rev = counters["rev_parse"] - first_rev
        second_git_total = counters["git"] - first_git_total

        assert first_rev == 1, f"cold render must run exactly one rev-parse, ran {first_rev}"
        assert first_git_total == 2, "cold render: 1 rev-parse + 1 capped status count"
        assert second_rev == 0, "second render within TTL must not rev-parse"
        assert second_git_total == 1, "only the live capped status count remains"

    def test_status_changes_cap_display(self, tmp_path, isolated_home, monkeypatch):
        """Porcelain output is capped: beyond the cap both implementations
        display "[N+]" instead of an unbounded count."""
        from claude_statusline.core.git import get_git_info as pkg_git_info

        repo = _make_git_repo(tmp_path / "cap-repo", dirty_files=4)
        monkeypatch.setattr(shared_module, "_STATUS_CHANGES_CAP", 3)

        out = sl.get_git_info(str(repo))
        visible = ANSI_RE.sub("", out)
        assert "[3+]" in visible

        pkg_out = pkg_git_info(repo)
        assert pkg_out == out

        count, saturated = shared_module._count_changes_capped(repo, cap=2)
        assert (count, saturated) == (2, True)


# ---------------------------------------------------------------------------
# Row: UTF-8 stdout guard (F-BUG-010)
# ---------------------------------------------------------------------------


class FakeStream:
    """Minimal stream double exposing/rejecting ``reconfigure`` as requested."""

    def __init__(self, encoding="cp1252", with_reconfigure=True, fail=False):
        self.encoding = encoding
        self.calls = []
        if with_reconfigure:

            def _reconfigure(**kwargs):
                self.calls.append(kwargs)
                if fail:
                    raise ValueError("detached stream")
                self.encoding = kwargs.get("encoding", self.encoding)

            self.reconfigure = _reconfigure


def run_utf8_guard(guard, monkeypatch, out_stream, err_stream):
    monkeypatch.setattr("sys.stdout", out_stream)
    monkeypatch.setattr("sys.stderr", err_stream)
    guard()
    return out_stream, err_stream


class TestUtf8GuardPair:
    def test_utf8_guard_reused_in_context_stats(self):
        """F-BUG-010: cli/context_stats.py reuses the guarded implementation
        instead of carrying its own unguarded copy."""
        assert cs._ensure_utf8_stdout is pkg._ensure_utf8_stdout

    @pytest.mark.parametrize(
        "guard_fn",
        [sl._ensure_utf8_stdout, pkg._ensure_utf8_stdout, cs._ensure_utf8_stdout],
        ids=["standalone", "package-statusline", "package-context-stats"],
    )
    @pytest.mark.parametrize(
        ("kwargs", "expect_reconfigure", "expect_utf8"),
        [
            ({"with_reconfigure": False}, False, False),
            ({"encoding": "cp1252"}, True, True),
            ({"encoding": "utf-8"}, False, False),
            ({"encoding": "UTF-8"}, False, False),
            ({"encoding": "eucJP"}, True, True),
            ({"encoding": "cp1252", "fail": True}, True, False),
        ],
        ids=[
            "no-reconfigure-attr",
            "cp1252-reconfigured",
            "utf8-skipped",
            "UTF8-skipped",
            "latin-reconfigured",
            "reconfigure-error-swallowed",
        ],
    )
    def test_utf8_guard_behavior_grid(
        self, guard_fn, kwargs, expect_reconfigure, expect_utf8, monkeypatch
    ):
        out, err = run_utf8_guard(
            guard_fn,
            monkeypatch,
            FakeStream(**kwargs),
            FakeStream(**kwargs),
        )
        for stream in (out, err):
            if expect_reconfigure:
                assert stream.calls == [{"encoding": "utf-8", "errors": "replace"}]
            else:
                assert stream.calls == []
            if expect_utf8:
                assert stream.encoding == "utf-8"


# ---------------------------------------------------------------------------
# Full-render byte parity — covers the render-inline sync rows
# (context group separator, model suffix separator, session cost display,
# effort display, pacman icon display, tok/s rolling read, session-id
# validate-degrade, state creation mode).
# ---------------------------------------------------------------------------


class TestRenderParity:
    @staticmethod
    def plain(text):
        return ANSI_RE.sub("", text)

    @staticmethod
    def expected_context_group():
        """The unspaced tokens·Zone·pacman group both renders must contain."""
        used = 10000 + 500 + 200
        size = 200000
        free = max(0, size - used)
        pct = f"{(free * 100.0) / size:.1f}"
        return f"{free:,} ({pct}%)·Plan·ᗧ"

    def test_render_byte_parity_basic(self, tmp_path, monkeypatch, capsys, isolated_home):
        payload = build_payload(tmp_path)
        sl_out, _sl_err = render_standalone(payload, isolated_home)
        pkg_out, _pkg_err = render_package(payload, monkeypatch, capsys, isolated_home)
        assert pkg_out == sl_out
        # Context group rendered as one unspaced atomic group: tokens·Zone·pacman
        assert self.expected_context_group() in self.plain(sl_out)
        # Session cost shown by default
        assert "$0.42" in sl_out

    def test_render_byte_parity_narrow_width_group_atomic(
        self, tmp_path, monkeypatch, capsys, isolated_home
    ):
        payload = build_payload(tmp_path)
        sl_lines = render_standalone(payload, isolated_home, columns="60")[0].split("\n")
        pkg_lines = render_package(payload, monkeypatch, capsys, isolated_home, columns="60")[
            0
        ].split("\n")
        assert pkg_lines == sl_lines
        assert len(sl_lines) > 1, "expected a multi-line reflow at 60 columns"
        joined = "\n".join(self.plain(line) for line in sl_lines)
        assert self.expected_context_group() in joined, "context group was split across lines"

    def test_render_byte_parity_effort_and_thinking(
        self, tmp_path, monkeypatch, capsys, isolated_home
    ):
        payload = build_payload(
            tmp_path,
            effort={"level": "high"},
        )
        payload["model"]["thinking_budget"] = 12000
        sl_out, _ = render_standalone(payload, isolated_home)
        pkg_out, _ = render_package(payload, monkeypatch, capsys, isolated_home)
        assert pkg_out == sl_out
        plain = self.plain(sl_out)
        assert "Test Model·12k tokens thinking·high" in plain

    def test_render_byte_parity_hostile_session_id(
        self, tmp_path, monkeypatch, capsys, isolated_home
    ):
        payload = build_payload(tmp_path, session_id="../../evil")
        sl_out, sl_err = render_standalone(payload, isolated_home)
        pkg_out, pkg_err = render_package(payload, monkeypatch, capsys, isolated_home)
        assert pkg_out == sl_out
        assert "Invalid session_id" in sl_err
        assert "Invalid session_id" in pkg_err

    def test_render_byte_parity_tps_rolling_read(
        self, tmp_path, monkeypatch, capsys, isolated_home
    ):
        """tok/s state field + bounded-tail rolling read parity: identical
        seeded histories (legacy 2-field prefix, blanks, normal rows) must
        produce identical tok/s segments through both implementations.

        Each side gets its OWN home with an identical seeded copy, because
        every render appends a row — a shared file would let the second side
        read the first side's appended row and diverge.
        """
        sl_home = isolated_home
        pkg_home = tmp_path / "pkg-home"
        pkg_home.mkdir(parents=True)
        for home in (sl_home, pkg_home):
            (home / ".claude").mkdir(parents=True, exist_ok=True)
            conf = home / ".claude" / "statusline.conf"
            conf.write_text(COMMENT_ONLY_CONF + "show_tps=true\n", encoding="utf-8")
            state_dir = home / ".claude" / "statusline"
            state_dir.mkdir(parents=True, exist_ok=True)
            sid = "tpscheck"
            ts = 1700000000
            rows = [f"{ts},1000\n"]  # legacy 2-field prefix
            rows.append("\n")  # blank noise row
            durations = [1000, 2600, 4200, 5800, 7400, 9000]
            usages = [10000, 11000, 12500, 14000, 15500, 17000]
            for i, (dur, used_in) in enumerate(zip(durations, usages, strict=True)):
                rows.append(
                    ",".join(
                        str(x)
                        for x in [
                            ts + 10 * (i + 1),
                            1000 + i,
                            500 + i,
                            used_in,
                            700 + i,
                            300,
                            200,
                            round(0.05 * i, 2),
                            2 * i,
                            i,
                            sid,
                            "claude-test",
                            "/tmp/proj",
                            200000,
                            dur,
                        ]
                    )
                    + "\n"
                )
            (state_dir / f"statusline.{sid}.state").write_text("".join(rows), encoding="utf-8")

        payload = build_payload(tmp_path, session_id="tpscheck")
        payload["context_window"]["current_usage"]["input_tokens"] = 20000

        sl_out, sl_err = render_standalone(payload, sl_home)
        pkg_out, pkg_err = render_package(payload, monkeypatch, capsys, pkg_home)
        assert "tok/s" in sl_out, sl_err
        assert "+3,200" in ANSI_RE.sub("", sl_out), "delta segment expected on both sides"
        assert pkg_out == sl_out

    def test_render_byte_parity_show_cost_off(self, tmp_path, monkeypatch, capsys, isolated_home):
        conf = isolated_home / ".claude" / "statusline.conf"
        conf.write_text(
            COMMENT_ONLY_CONF + "show_cost=false\nshow_pacman=false\nshow_effort=false\n",
            encoding="utf-8",
        )
        payload = build_payload(tmp_path, effort={"level": "medium"})
        sl_out, _ = render_standalone(payload, isolated_home)
        pkg_out, _ = render_package(payload, monkeypatch, capsys, isolated_home)
        assert pkg_out == sl_out
        plain = self.plain(sl_out)
        assert "$" not in plain, "cost hidden"
        assert "ᗧ" not in plain, "pacman hidden"
        assert "·medium" not in plain, "effort hidden"

    def test_api_duration_state_field_index14(self, tmp_path, monkeypatch, isolated_home):
        """CSV index 14 carries api_duration_ms identically on both writers."""
        from claude_statusline.core.state import StateEntry

        entry = StateEntry(
            timestamp=1,
            total_input_tokens=2,
            total_output_tokens=3,
            current_input_tokens=4,
            current_output_tokens=5,
            cache_creation=6,
            cache_read=7,
            cost_usd=8.5,
            lines_added=9,
            lines_removed=10,
            session_id="idx",
            model_id="m",
            workspace_project_dir="/w",
            context_window_size=11,
            api_duration_ms=12345,
        )
        parts = entry.to_csv_line().split(",")
        assert parts[14] == "12345"

        state_dir = isolated_home / ".claude" / "statusline"
        conf = isolated_home / ".claude" / "statusline.conf"
        conf.write_text(COMMENT_ONLY_CONF, encoding="utf-8")
        payload = build_payload(tmp_path, session_id="idx14")
        render_standalone(payload, isolated_home)
        written = (state_dir / "statusline.idx14.state").read_text().strip().split(",")
        assert len(written) == 15
        assert written[14] == "42000"

    def test_state_file_creation_mode_parity(self, tmp_path, monkeypatch, isolated_home):
        def owner_only(path: Path) -> bool:
            mode = stat.S_IMODE(path.stat().st_mode)
            if sys.platform == "win32":
                return mode & 0o600 == 0o600
            return mode == 0o600

        payload = build_payload(tmp_path, session_id="modecheck")
        render_standalone(payload, isolated_home)
        assert owner_only(isolated_home / ".claude" / "statusline" / "statusline.modecheck.state")

        from claude_statusline.core.state import StateEntry

        state_root = tmp_path / "pkg-state"
        monkeypatch.setattr(StateFile, "STATE_DIR", state_root)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old-mode")
        (tmp_path / "old-mode").mkdir()
        StateFile("modecheck").append_entry(
            StateEntry(
                timestamp=1,
                total_input_tokens=1,
                total_output_tokens=1,
                current_input_tokens=1,
                current_output_tokens=1,
                cache_creation=1,
                cache_read=1,
                cost_usd=0.0,
                lines_added=0,
                lines_removed=0,
                session_id="modecheck",
                model_id="m",
                workspace_project_dir="/w",
                context_window_size=1,
            )
        )
        assert owner_only(state_root / "statusline.modecheck.state")


# ---------------------------------------------------------------------------
# Row: Render catch-all
# ---------------------------------------------------------------------------


class TestRenderCatchAllPair:
    PAYLOAD_BREAKER = {
        "model": {"display_name": "M"},
        "workspace": {"current_dir": "/w", "project_dir": "/w"},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": "not-a-dict-crashes-get",
        },
    }

    def test_render_catch_all_parity(self, tmp_path, monkeypatch, capsys, isolated_home):
        # Package side, in-process.
        payload = json.loads(json.dumps(self.PAYLOAD_BREAKER))
        monkeypatch.setenv("HOME", str(isolated_home))
        monkeypatch.setenv("USERPROFILE", str(isolated_home))
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        pkg.main()
        captured = capsys.readouterr()
        assert "[Claude] ~" in captured.out
        assert "Traceback" in captured.err

        # Standalone side, subprocess.
        sl_out, sl_err = render_standalone(payload, isolated_home)
        assert sl_out.endswith("[Claude] ~")
        assert "Traceback" in sl_err


def test_placeholder_import_symmetry():
    """Guard the deliberate reuse import: context_stats exposes the guarded
    implementation imported from cli.statusline (single package copy)."""
    import inspect

    source = inspect.getsource(cs)
    assert "from claude_statusline.cli.statusline import _ensure_utf8_stdout" in source


# ---------------------------------------------------------------------------
# Task 5.2/5.3 arrangement: single-sourced shared module + vendored copy
# ---------------------------------------------------------------------------


class TestSharedModuleArrangement:
    """The extracted shared module (F-DEAD-001) and its standalone contract."""

    def test_vendored_copy_byte_identical(self):
        """scripts/_statusline_shared.py must equal src/claude_statusline/_shared.py.

        The standalone script falls back to this vendored sibling when the
        package is not importable; any drift between the two copies would
        silently fork the synced logic, so equality is enforced byte-for-byte.
        """
        assert VENDORED_SHARED_PATH.exists(), "vendored copy missing from scripts/"
        assert VENDORED_SHARED_PATH.read_bytes() == SHARED_MODULE_PATH.read_bytes()

    def test_script_binds_shared_symbols(self):
        """The standalone module resolves its moved symbols from the loaded
        shared module rather than defining duplicate bodies."""
        for name in (
            "compute_tps",
            "format_tps",
            "detect_compaction_events",
            "visible_width",
            "fit_to_width",
            "get_terminal_width",
            "get_pacman_icon",
            "compute_mi",
            "get_model_profile",
            "_parse_color",
            "_validate_session_id",
            "_validate_csv_field",
            "_csv_unsafe_reason",
            "_sanitize_workspace_dir",
            "_extract",
            "_resolve_project_dir",
            "_ensure_utf8_stdout",
            "_format_thinking_info",
            "_tps_tail_size",
            "get_git_info",
        ):
            fn = getattr(sl, name)
            assert getattr(fn, "__module__", "").endswith("_shared"), name
        # Palette-aware wrappers stay script-local by design.
        assert sl.get_mi_color.__module__ == "scripts.statusline"
        assert sl._zone_ansi_color.__module__ == "scripts.statusline"

    def test_ast_duplicated_function_ratio_below_threshold(self):
        """AST recount of name-matched duplicated functions stays below 25%.

        Acceptance criterion of Task 5.2 (#143). The two remaining name matches
        are documented remainder, not duplicated logic:
          - ``main``  — per-implementation entry point / render catch-all boundary.
          - ``_render`` — the standalone dict-based renderer; its package twin
            uses ColorManager/StateFile abstractions, and its decomposition is
            owned by a later modernization task.
        """

        def normalized(node):
            body = node.body
            if (
                len(body) == 1
                and isinstance(body[0], ast_mod.Expr)
                and isinstance(body[0].value, ast_mod.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = []
            return ast_mod.dump(ast_mod.Module(body=body, type_ignores=[]))

        tree = ast_mod.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        script_fns = {
            n.name: normalized(n) for n in ast_mod.walk(tree) if isinstance(n, ast_mod.FunctionDef)
        }

        pkg_names: set[str] = set()
        pkg_bodies: dict[str, set[str]] = {}
        for p in (PROJECT_ROOT / "src").rglob("*.py"):
            t = ast_mod.parse(p.read_text(encoding="utf-8"))
            for n in ast_mod.walk(t):
                if isinstance(n, ast_mod.FunctionDef):
                    pkg_names.add(n.name)
                    pkg_bodies.setdefault(n.name, set()).add(normalized(n))

        matched = [name for name in script_fns if name in pkg_names]
        ratio = len(matched) / len(script_fns)
        assert ratio < 0.25, f"name-matched duplication {ratio:.1%} >= 25%: {sorted(matched)}"
        # The documented remainder must be exactly these orchestration boundaries.
        assert set(matched) <= {"main", "_render"}

    def test_standalone_renders_without_package(self, tmp_path):
        """End-to-end smoke: with ``claude_statusline`` made unimportable, the
        script still renders via its vendored sibling copy."""
        blocker_dir = tmp_path / "blocker"
        blocker_dir.mkdir()
        (blocker_dir / "claude_statusline.py").write_text(
            "raise ImportError('blocked for standalone smoke test')\n", encoding="utf-8"
        )
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(blocker_dir)
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        env.pop("COLUMNS", None)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
            ],
            input=json.dumps({"session_id": "no-pkg-smoke"}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert "Claude" in ANSI_RE.sub("", result.stdout)
        assert "no-pkg-smoke" in ANSI_RE.sub("", result.stdout)


# ---------------------------------------------------------------------------
# Task 5.4 (#145): orchestrator arrangement + golden render fixtures
# ---------------------------------------------------------------------------


class TestScriptRenderArrangement:
    """F-CLEAN-001/009 guards: no ``global`` statements and small orchestrators."""

    def test_script_has_no_global_statements(self):
        """The issue's own verify gate: zero ``global`` statements anywhere in
        scripts/statusline.py (palette overrides travel via _Palette)."""
        tree = ast_mod.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        offenders = [n.lineno for n in ast_mod.walk(tree) if isinstance(n, ast_mod.Global)]
        assert offenders == []

    def test_orchestrators_within_line_budget(self):
        """``main`` and the ``_render`` orchestrator each stay <= 100 lines;
        the render pipeline lives in the extracted phase helpers instead."""
        tree = ast_mod.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        sizes = {
            n.name: n.end_lineno - n.lineno + 1
            for n in ast_mod.walk(tree)
            if isinstance(n, ast_mod.FunctionDef) and n.name in ("main", "_render")
        }
        assert set(sizes) == {"main", "_render"}
        for name, lines_count in sizes.items():
            assert lines_count <= 100, f"{name} spans {lines_count} lines"

    def test_palette_overrides_do_not_mutate_module_constants(self, tmp_path, monkeypatch, capsys):
        """F-CLEAN-009: rendering with color overrides leaves the script's
        module-level palette constants untouched, so consecutive renders
        cannot leak palette state into each other (safe to render
        in-process now — previously this required a subprocess)."""
        from claude_statusline._shared import GREEN as PKG_GREEN

        home = tmp_path / "palette-home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "statusline.conf").write_text(
            COMMENT_ONLY_CONF + "color_green=#123456\n", encoding="utf-8"
        )
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setenv("COLUMNS", "200")

        sl._render(build_payload(tmp_path))
        out = capsys.readouterr().out
        assert "\033[38;2;18;52;86m" in out, "color_green override must be applied"
        assert sl.GREEN == PKG_GREEN == "\033[0;32m"


class TestRenderGoldenFixtures:
    """Byte-exact regression pins for rendered output (issue #145).

    ``fixtures/render_goldens.json`` was captured from the pre-refactor
    implementation; every case must keep rendering byte-identically through
    BOTH implementations after the phase-helper decomposition.
    """

    @staticmethod
    def _render_standalone_raw(case, home):
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        env["COLUMNS"] = case["columns"]
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input=case["stdin"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=120,
        )
        return result

    @pytest.mark.parametrize(
        "index", range(len(json.loads(GOLDEN_FIXTURES_PATH.read_text(encoding="utf-8"))))
    )
    def test_render_matches_pinned_golden(
        self, index, tmp_path, monkeypatch, capsys, isolated_home
    ):
        cases = json.loads(GOLDEN_FIXTURES_PATH.read_text(encoding="utf-8"))
        case = cases[index]
        assert case["name"]

        home = tmp_path / f"golden-home-{index}"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "statusline.conf").write_text(case["conf"], encoding="utf-8")

        result = self._render_standalone_raw(case, home)
        assert result.returncode == 0, result.stderr
        assert result.stdout == case["expected_stdout"], case["name"]
        for marker in case["stderr_markers"]:
            assert marker in result.stderr, case["name"]

        # Package side must agree byte-for-byte on every dict-representable
        # payload (the invalid-JSON case has no dict form by definition).
        try:
            payload = json.loads(case["stdin"])
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        pkg_home = tmp_path / f"golden-pkg-home-{index}"
        (pkg_home / ".claude").mkdir(parents=True)
        (pkg_home / ".claude" / "statusline.conf").write_text(case["conf"], encoding="utf-8")
        pkg_out, pkg_err = render_package(
            payload, monkeypatch, capsys, pkg_home, columns=case["columns"]
        )
        assert pkg_out == result.stdout.rstrip("\n"), case["name"]
        for marker in case["stderr_markers"]:
            assert marker in pkg_err, case["name"]
