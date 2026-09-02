"""Branch tests for _shared helpers (Task 5.7 coverage hardening)."""

import json
import time

from claude_statusline import _shared


class TestZoneAnsiCode:
    """zone_ansi_code tier mapping."""

    def test_green_yellow_pass_through(self):
        assert _shared.zone_ansi_code("green", "G", "Y", "R") == "G"
        assert _shared.zone_ansi_code("yellow", "G", "Y", "R") == "Y"

    def test_fixed_rgb_tiers(self):
        assert _shared.zone_ansi_code("orange", "G", "Y", "R") == _shared.ZONE_ORANGE_ANSI
        assert _shared.zone_ansi_code("amber", "G", "Y", "R") == _shared.ZONE_AMBER_ANSI
        assert _shared.zone_ansi_code("dark_red", "G", "Y", "R") == _shared.ZONE_DARK_RED_ANSI
        assert _shared.zone_ansi_code("gray", "G", "Y", "R") == _shared.ZONE_GRAY_ANSI

    def test_amber_is_distinct_from_orange(self):
        assert _shared.ZONE_AMBER_ANSI != _shared.ZONE_ORANGE_ANSI

    def test_unknown_falls_back_to_reset(self):
        assert _shared.zone_ansi_code("magenta?", "G", "Y", "R") == "R"


class TestComputeTpsEdges:
    def test_total_ms_zero_returns_none(self):
        samples = [(100, 0), (200, 0)]
        assert _shared.compute_tps(samples) is None

    def test_no_turns_returns_none(self):
        assert _shared.compute_tps([]) is None


class TestResolveProjectDir:
    def test_non_string_and_empty_are_none(self):
        assert _shared._resolve_project_dir(None) is None
        assert _shared._resolve_project_dir("") is None

    def test_missing_dir_is_none(self):
        assert _shared._resolve_project_dir("/nonexistent/definitely-missing") is None

    def test_existing_dir_resolves(self, tmp_path):
        assert _shared._resolve_project_dir(str(tmp_path)) == str(tmp_path)


class TestFormatThinkingInfo:
    def test_none_and_zero_are_empty(self):
        assert _shared._format_thinking_info(None) == ""
        assert _shared._format_thinking_info(0) == ""

    def test_invalid_string_is_empty(self):
        assert _shared._format_thinking_info("soon") == ""

    def test_negative_is_empty(self):
        assert _shared._format_thinking_info(-5) == ""

    def test_megabyte_budget(self):
        out = _shared._format_thinking_info(2_500_000)
        assert out == "2M tokens thinking"

    def test_round_band(self):
        # 10_000..999_999 rounds to the nearest k.
        out = _shared._format_thinking_info(12_345)
        assert out.endswith("k tokens thinking")

    def test_floor_band_truncates(self):
        out = _shared._format_thinking_info(6_400)
        assert out == "6k tokens thinking"

    def test_below_floor_shows_exact(self):
        out = _shared._format_thinking_info(4_096)
        assert out == "4096 tokens thinking"


class TestStateLockGuards:
    def test_unlock_with_fcntl_none_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_shared, "fcntl", None)
        f = tmp_path / "s.state"
        f.write_text("", encoding="utf-8")
        with open(f) as fh:
            _shared._unlock_state_file(fh)  # must not raise

    def test_lock_swallows_oserror_from_fileno(self, tmp_path, monkeypatch):
        class BoomFileno:
            def fileno(self):
                raise OSError("no fd")

        # flock never runs: the OSError from fileno() is swallowed by the guard.
        _shared._lock_state_file(BoomFileno())


class TestPrCacheBranches:
    def test_get_rejects_non_dict_cache_file(self, tmp_path):
        cache = tmp_path / "pr_cache.json"
        cache.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        assert _shared._pr_cache_get("k", cache_file=str(cache)) is None

    def test_get_rejects_expired_entry(self, tmp_path):
        cache = tmp_path / "pr_cache.json"
        past = time.time() - 1000
        cache.write_text(json.dumps({"k": {"pr": 7, "exp": past}}), encoding="utf-8")
        assert _shared._pr_cache_get("k", cache_file=str(cache)) is None

    def test_get_corrupt_json_returns_none(self, tmp_path):
        cache = tmp_path / "pr_cache.json"
        cache.write_text("{not json", encoding="utf-8")
        assert _shared._pr_cache_get("k", cache_file=str(cache)) is None

    def test_set_survives_unwritable_dir(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("file in the way", encoding="utf-8")
        cache = str(blocker / "nested" / "pr_cache.json")
        _shared._pr_cache_set("k", 42, cache_file=cache)  # OSError swallowed

    def test_set_then_read_roundtrip(self, tmp_path):
        cache = tmp_path / "pr_cache.json"
        _shared._pr_cache_set("owner/repo", 99, cache_file=str(cache))
        assert _shared._pr_cache_get("owner/repo", cache_file=str(cache)) == "99"


class TestRendererBranches:
    """GraphRenderer branch coverage (Task 5.7)."""

    def _renderer(self):
        from claude_statusline.core.colors import ColorManager
        from claude_statusline.graphs.renderer import GraphDimensions, GraphRenderer

        return GraphRenderer(
            colors=ColorManager(enabled=False),
            dimensions=GraphDimensions(
                term_width=120, term_height=40, graph_width=105, graph_height=13
            ),
        )

    def _entry(self, i=0):
        from claude_statusline.core.state import StateEntry

        return StateEntry(
            timestamp=1710288000 + i * 300,
            total_input_tokens=50_000,
            total_output_tokens=5_000,
            current_input_tokens=10_000 + i,
            current_output_tokens=2_000,
            cache_creation=5_000,
            cache_read=15_000,
            cost_usd=0.05,
            lines_added=1,
            lines_removed=1,
            session_id="s",
            model_id="claude-opus-4-6",
            workspace_project_dir="/w",
            context_window_size=200_000,
        )

    def _summary(self, entries, **kwargs):
        r = self._renderer()
        r.begin_buffering()
        r.render_summary(entries, [100] * max(0, len(entries) - 1), **kwargs)
        return r.get_buffer()

    def test_summary_cache_warm_active(self):
        out = self._summary([self._entry()], cache_warm_status=(True, 125))
        assert "Cache Warm:" in out
        assert "active (2m 5s remaining)" in out

    def test_summary_cache_warm_active_seconds_only(self):
        out = self._summary([self._entry()], cache_warm_status=(True, 45))
        assert "45s remaining" in out

    def test_summary_cache_warm_inactive(self):
        out = self._summary([self._entry()], cache_warm_status=(False, 0))
        assert "inactive" in out

    def test_render_timeseries_empty_data_is_noop(self):
        r = self._renderer()
        r.begin_buffering()
        r.render_timeseries([], [], title="t", color="")
        assert r.get_buffer() == ""

    def test_build_grid_empty_data_returns_blank_rows(self):
        r = self._renderer()
        rows = r._build_grid([], 0, 0, 0, width=40, height=8)
        assert len(rows) == 8 and all(set(row) == {" "} for row in rows)

    def test_build_grid_zero_value_range_centers(self):
        r = self._renderer()
        rows = r._build_grid([5, 5], 5, 5, 0, width=40, height=8)
        assert any(row.strip() for row in rows)

    def test_get_buffer_without_buffering_is_empty(self):
        assert self._renderer().get_buffer() == ""

    def test_emit_prints_when_not_buffering(self, capsys):
        r = self._renderer()
        r._emit("hello")
        assert "hello" in capsys.readouterr().out


class TestMiscSmallModules:
    def test_main_module_runs_cli_main(self, monkeypatch):
        import runpy

        import claude_statusline.cli.statusline as sl

        called = []
        monkeypatch.setattr(sl, "main", lambda: called.append(1))
        monkeypatch.setattr("sys.argv", ["claude-statusline"])
        runpy.run_module("claude_statusline.__main__", run_name="__main__")
        assert called == [1]
