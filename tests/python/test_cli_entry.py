"""In-process tests for the context_stats CLI entry point (issue #137, F-TEST-002).

Exercises parse_args/_normalize_argv argument-fallback paths and every
subcommand-dispatch branch of main() without spawning subprocesses: argv is
monkeypatched, the state dir lives under tmp_path, and subcommand workers are
stubbed so dispatch itself is what's under test.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from claude_statusline import __version__
from claude_statusline.cli import context_stats as cs
from claude_statusline.core.state import StateEntry, StateFile


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Isolate state dirs and HOME under tmp_path so Config/StateFile never
    touch the developer's real ~/.claude."""
    state_dir = tmp_path / "state"
    old_dir = tmp_path / "old"
    monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
    monkeypatch.setattr(StateFile, "OLD_STATE_DIR", old_dir)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


def _entry(**overrides) -> StateEntry:
    defaults: dict = {
        "timestamp": 1710288000,
        "total_input_tokens": 100,
        "total_output_tokens": 200,
        "current_input_tokens": 300,
        "current_output_tokens": 400,
        "cache_creation": 500,
        "cache_read": 600,
        "cost_usd": 0.01,
        "lines_added": 10,
        "lines_removed": 5,
        "session_id": "sess-cli",
        "model_id": "claude-test",
        "workspace_project_dir": "/tmp/proj",
        "context_window_size": 200000,
        "api_duration_ms": 1500,
    }
    defaults.update(overrides)
    return StateEntry(**defaults)


def _write_state(entries, session="sess-cli"):
    sf = StateFile(session)
    sf.file_path.write_text("".join(e.to_csv_line() + "\n" for e in entries))
    return sf


def _run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["context-stats", *argv])
    cs.main()


# ---------------------------------------------------------------------------
# _normalize_argv — positional/action disambiguation fallbacks
# ---------------------------------------------------------------------------


class TestNormalizeArgv:
    def test_no_arguments_defaults_to_latest_graph(self):
        assert cs._normalize_argv([]) == ("graph", None, [])

    def test_flags_only_keeps_flags_with_latest_session(self):
        action, sid, remaining = cs._normalize_argv(["--no-watch", "--no-color"])
        assert (action, sid) == ("graph", None)
        assert remaining == ["--no-watch", "--no-color"]

    def test_action_first_has_no_session_id(self):
        action, sid, remaining = cs._normalize_argv(["export", "--output", "x.md"])
        assert action == "export"
        assert sid is None
        assert remaining == ["--output", "x.md"]

    def test_explain_uses_dash_placeholder(self):
        action, sid, _ = cs._normalize_argv(["explain"])
        assert (action, sid) == ("explain", "-")

    def test_single_unknown_positional_is_session_id(self):
        action, sid, remaining = cs._normalize_argv(["abc123"])
        assert (action, sid) == ("graph", "abc123")
        assert remaining == []

    def test_session_then_action(self):
        action, sid, remaining = cs._normalize_argv(["abc123", "export", "-o", "f.md"])
        assert action == "export"
        assert sid == "abc123"
        assert remaining == ["-o", "f.md"]

    def test_unknown_action_exits(self, capsys):
        with pytest.raises(SystemExit) as ei:
            cs._normalize_argv(["abc123", "bogus"])
        assert ei.value.code == 1
        assert "Unknown action 'bogus'" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# parse_args — version/help exits, session validation, graph parsing
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_version_flag_exits_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["context-stats", "--version"])
        with pytest.raises(SystemExit) as ei:
            cs.parse_args()
        assert ei.value.code == 0
        assert f"context-stats {__version__}" in capsys.readouterr().out

    def test_short_version_flag(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["context-stats", "-V"])
        with pytest.raises(SystemExit):
            cs.parse_args()
        assert __version__ in capsys.readouterr().out

    @pytest.mark.parametrize("help_argv", [[], ["--help"], ["-h"]])
    def test_help_paths_exit_zero(self, monkeypatch, capsys, help_argv):
        monkeypatch.setattr(sys, "argv", ["context-stats", *help_argv])
        with pytest.raises(SystemExit) as ei:
            cs.parse_args()
        assert ei.value.code == 0
        assert "Context Stats Visualizer" in capsys.readouterr().out

    def test_graph_action_parsed(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["context-stats", "abc", "graph", "--type", "tps"])
        args = cs.parse_args()
        assert args.action == "graph"
        assert args.session_id == "abc"
        assert args.type == "tps"

    def test_graph_help_flag_prints_and_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["context-stats", "graph", "--help"])
        with pytest.raises(SystemExit) as ei:
            cs.parse_args()
        assert ei.value.code == 0
        assert "context-stats graph" in capsys.readouterr().out

    def test_invalid_session_id_rejected(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["context-stats", "../evil", "graph"])
        with pytest.raises(SystemExit) as ei:
            cs.parse_args()
        assert ei.value.code == 1
        assert "Error:" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "argv,action,sid",
        [
            (["export"], "export", None),
            (["abc", "export"], "export", "abc"),
            (["explain"], "explain", "-"),
            (["report"], "report", None),
            (["sessions"], "sessions", None),
            (["abc", "cache-warm", "on"], "cache-warm", "abc"),
        ],
    )
    def test_non_graph_actions_return_minimal_namespace(self, monkeypatch, argv, action, sid):
        monkeypatch.setattr(sys, "argv", ["context-stats", *argv])
        args = cs.parse_args()
        assert args.action == action
        assert args.session_id == sid


# ---------------------------------------------------------------------------
# render_once — insufficient-data and header/activity branches
# ---------------------------------------------------------------------------


class TestRenderOnceEdges:
    def test_insufficient_data_raises_insufficient_data_error(self, isolated):
        """Rendering is transport-free: too-few-points raises with the message."""
        sf = _write_state([_entry()])
        with pytest.raises(cs.InsufficientDataError) as ei:
            cs.render_once(sf, "delta", _FakeRenderer(), _Colors())
        assert "Need at least 2 data points" in str(ei.value)

    def test_insufficient_message_carries_entry_count(self, isolated):
        """The exception message explains how many entries were found."""
        sf = _write_state([_entry()])
        with pytest.raises(cs.InsufficientDataError) as ei:
            cs.render_once(sf, "delta", _FakeRenderer(), _Colors())
        assert "Found: 1 entry." in str(ei.value)

    def test_header_without_project_dir_uses_session_label(self, isolated, tmp_path):
        entries = [
            _entry(workspace_project_dir="", timestamp=1),
            _entry(workspace_project_dir="", timestamp=2),
        ]
        sf = _write_state(entries)
        renderer = _FakeRenderer(buffer="S")
        result = cs.render_once(sf, "delta", renderer, _Colors(), config=_Config())
        assert "(Session: sess-cli)" in result
        assert "S" in result

    def test_active_session_shows_waiting_text(self, isolated):
        now_ts = int(cs.time.time())
        entries = [
            _entry(timestamp=now_ts - 5),
            _entry(timestamp=now_ts - 2),
        ]
        sf = _write_state(entries)
        result = cs.render_once(sf, "delta", _FakeRenderer(buffer=""), _Colors(), config=_Config())
        # Last entry within is_active's 30s window → rotating waiting text shown.
        assert "Working..." in result  # reduced_motion=True static text

    def test_compaction_events_render_mi_markers(self, isolated):
        entries = [
            _entry(current_input_tokens=190_000, timestamp=1),
            _entry(current_input_tokens=10_000, timestamp=2),
            _entry(current_input_tokens=12_000, timestamp=3),
        ]
        sf = _write_state(entries)
        renderer = _FakeRenderer(buffer="")
        result = cs.render_once(sf, "delta", renderer, _Colors(), config=_Config())
        assert isinstance(result, str)


class _FakeRenderer:
    """Minimal GraphRenderer double for render_once tests."""

    def __init__(self, buffer: str = "") -> None:
        self._buffer = buffer

    def begin_buffering(self) -> None:
        pass

    def get_buffer(self) -> str:
        return self._buffer

    def render_timeseries(self, *args, **kwargs) -> None:
        pass

    def render_summary(self, *args, **kwargs) -> None:
        pass

    def render_footer(self, *args, **kwargs) -> None:
        pass


class _Colors:
    bold = magenta = dim = cyan = yellow = green = blue = red = reset = ""


class _Config:
    reduced_motion = True
    compaction_drop_threshold = 0.5
    compact_mi_warn_threshold = 0.3
    mi_curve_beta = 1.0


# ---------------------------------------------------------------------------
# watch mode + waiting messages
# ---------------------------------------------------------------------------


class TestWatchMode:
    def test_one_watch_iteration_without_state_file(self, isolated, monkeypatch, capsys):
        """Empty state dir → waiting message branch; sleep raises to stop the loop."""
        monkeypatch.setattr(cs.time, "sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt()))
        sf = StateFile(None)
        renderer = _FakeRenderer()
        with pytest.raises(KeyboardInterrupt):
            cs.run_watch_mode(sf, "delta", 2, renderer, _Colors(), config=_Config())
        out = capsys.readouterr().out
        assert "LIVE" in out
        assert "no data has been recorded yet" in out

    def test_one_watch_iteration_with_state_file(self, isolated, monkeypatch, capsys):
        entries = [_entry(timestamp=1), _entry(timestamp=2)]
        _write_state(entries)
        monkeypatch.setattr(cs.time, "sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt()))
        sf = StateFile("sess-cli")
        renderer = _FakeRenderer(buffer="GRAPH")
        with pytest.raises(KeyboardInterrupt):
            cs.run_watch_mode(sf, "delta", 2, renderer, _Colors(), config=_Config())
        assert "LIVE" in capsys.readouterr().out


class TestWaitingMessages:
    def test_format_waiting_message_with_session(self):
        msg = cs._format_waiting_message(_Colors(), "sess-9")
        assert "(Session: sess-9)" in msg
        assert "Waiting for session data" in msg

    def test_format_waiting_message_without_session(self):
        msg = cs._format_waiting_message(_Colors(), None)
        assert "Context Stats" in msg
        assert "(Session:" not in msg

    def test_show_waiting_message_prints(self, capsys):
        cs.show_waiting_message(_Colors(), "sess-x", message="custom wait")
        assert "custom wait" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# sessions action — run_sessions listing branches
# ---------------------------------------------------------------------------


class TestRunSessions:
    def test_no_recent_sessions_prints_tip(self, isolated, capsys):
        cs.run_sessions(5, _Colors())
        out = capsys.readouterr().out
        assert "No sessions found" in out
        assert "--minutes N" in out

    def test_lists_recent_session_with_metadata(self, isolated, capsys):
        entry = _entry(current_input_tokens=300_000, cache_creation=500_000, cache_read=400_000)
        _write_state([entry], session="recent1")
        cs.run_sessions(5, _Colors())
        out = capsys.readouterr().out
        assert "recent1" in out
        assert "/tmp/proj".split("/")[-1] in out  # project folder name
        assert "claude-test" in out
        assert "tokens" in out

    def test_token_display_million_and_kilo_branches(self, isolated, capsys):
        big = _entry(
            current_input_tokens=900_000,
            cache_creation=200_000,
            cache_read=100_000,  # current_used = 1.2M
        )
        mid = _entry(current_input_tokens=1500)  # current_used = 2600 → K format
        small = _entry(
            current_input_tokens=10, cache_creation=0, cache_read=0
        )  # current_used = 10 → plain count
        _write_state([big], session="bigses")
        _write_state([mid], session="midses")
        _write_state([small], session="smallses")
        cs.run_sessions(60, _Colors())
        out = capsys.readouterr().out
        assert "1.2M tokens" in out
        assert "3K tokens" in out
        assert "10 tokens" in out


# ---------------------------------------------------------------------------
# main() — explain / export / cache-warm / report / sessions dispatch
# ---------------------------------------------------------------------------


class TestMainDispatch:
    def test_explain_valid_json_calls_run_explain(self, isolated, monkeypatch, capsys):
        recorded = {}
        from claude_statusline.cli import explain as explain_mod

        monkeypatch.setattr(
            explain_mod,
            "run_explain",
            lambda data, no_color: recorded.update(data=data, nc=no_color),
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"model":{"display_name":"Opus"}}'))
        _run_main(monkeypatch, ["explain"])
        assert recorded["data"] == {"model": {"display_name": "Opus"}}
        assert recorded["nc"] is False

    def test_explain_invalid_json_errors(self, isolated, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO("{not json"))
        with pytest.raises(SystemExit) as ei:
            _run_main(monkeypatch, ["explain"])
        assert ei.value.code == 1
        assert "invalid JSON on stdin" in capsys.readouterr().err

    def test_export_dispatch_passes_argv(self, isolated, monkeypatch):
        recorded = {}
        from claude_statusline.cli import export as export_mod

        monkeypatch.setattr(export_mod, "run_export", lambda argv: recorded.update(argv=argv))
        _run_main(monkeypatch, ["abc", "export", "--output", "r.md"])
        assert recorded["argv"] == ["abc", "--output", "r.md"]

    def test_cache_warm_requires_resolvable_session(self, isolated, monkeypatch, capsys):
        with pytest.raises(SystemExit) as ei:
            _run_main(monkeypatch, ["cache-warm", "on"])
        assert ei.value.code == 1
        assert "No session data found" in capsys.readouterr().err

    def test_cache_warm_dispatch_with_latest_session(self, isolated, monkeypatch):
        _write_state([_entry()], session="warmme")
        recorded = {}
        from claude_statusline.cli import cache_warm as cw_mod

        monkeypatch.setattr(
            cw_mod,
            "run_cache_warm",
            lambda sid, remaining, colors: recorded.update(sid=sid, remaining=remaining),
        )
        _run_main(monkeypatch, ["cache-warm", "on"])
        assert recorded["sid"] == "warmme"
        assert recorded["remaining"] == ["on"]

    def test_report_dispatch(self, isolated, monkeypatch):
        recorded = {}
        from claude_statusline.cli import report as report_mod

        monkeypatch.setattr(
            report_mod, "run_report", lambda remaining: recorded.update(rem=remaining)
        )
        _run_main(monkeypatch, ["report", "--since-days", "7"])
        assert recorded["rem"] == ["--since-days", "7"]

    def test_sessions_rejects_session_id(self, isolated, monkeypatch, capsys):
        with pytest.raises(SystemExit) as ei:
            _run_main(monkeypatch, ["abc", "sessions"])
        assert ei.value.code == 1
        assert "does not accept a session_id" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "argv,err_fragment",
        [
            (["sessions", "--minutes"], "requires a value"),
            (["sessions", "--minutes", "abc"], "Invalid value for --minutes"),
            (["sessions", "--minutes", "0"], "must be a positive integer"),
            (["sessions", "--bogus"], "Unknown flag for sessions"),
            (["sessions", "extra-positional"], "Unexpected argument for sessions"),
        ],
    )
    def test_sessions_argument_errors(self, isolated, monkeypatch, capsys, argv, err_fragment):
        with pytest.raises(SystemExit) as ei:
            _run_main(monkeypatch, argv)
        assert ei.value.code == 1
        assert err_fragment in capsys.readouterr().err

    def test_sessions_accepts_minutes_flag(self, isolated, monkeypatch):
        recorded = {}
        monkeypatch.setattr(cs, "run_sessions", lambda minutes, colors: recorded.update(m=minutes))
        _run_main(monkeypatch, ["sessions", "--minutes", "30"])
        assert recorded["m"] == 30

    def test_sessions_ignores_no_color_flag(self, isolated, monkeypatch):
        recorded = {}
        monkeypatch.setattr(cs, "run_sessions", lambda minutes, colors: recorded.update(m=minutes))
        _run_main(monkeypatch, ["sessions", "--no-color"])
        assert recorded["m"] == 5  # default window preserved


class TestSetupHint:
    """Issue #188: the CLI volunteers that the status line is unwired.

    The hint is stderr-only, never raises, never changes the exit code, and
    is silent when wired, when settings.json is missing/unreadable/malformed,
    or when suppressed via the conf key or the env var.
    """

    HINT = (
        "! statusLine is not wired into ~/.claude/settings.json — "
        "the status line will never run. Fix: context-stats doctor --fix"
    )

    @staticmethod
    def _write_settings(home, data):
        path = home / ".claude" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    @staticmethod
    def _write_conf(home, text):
        path = home / ".claude" / "statusline.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _invoke(monkeypatch, argv):
        """Run main(), returning the SystemExit code (or None)."""
        try:
            _run_main(monkeypatch, argv)
            return None
        except SystemExit as e:
            return e.code

    def test_unwired_emits_exactly_one_hint_line(self, isolated, monkeypatch, capsys):
        """AC#1: valid settings.json without statusLine -> hint on stderr only."""
        self._write_settings(isolated, {"theme": "dark"})
        code = self._invoke(monkeypatch, ["graph", "--no-watch"])
        captured = capsys.readouterr()
        assert code == 0  # exit code untouched
        assert captured.err == self.HINT + "\n"  # exactly one line
        assert "No session data found." in captured.out  # stdout unchanged

    def test_wired_is_silent(self, isolated, monkeypatch, capsys):
        """AC#2: valid statusLine wiring -> no hint, stdout unaffected."""
        self._write_settings(
            isolated, {"statusLine": {"type": "command", "command": "claude-statusline"}}
        )
        code = self._invoke(monkeypatch, ["graph", "--no-watch"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        assert "No session data found." in captured.out

    def test_missing_settings_is_silent(self, isolated, monkeypatch, capsys):
        """No settings.json -> silent (doctor diagnoses that on its own terms)."""
        code = self._invoke(monkeypatch, ["graph", "--no-watch"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""

    def test_malformed_settings_is_silent(self, isolated, monkeypatch, capsys):
        self._write_settings(isolated, "{not json")
        code = self._invoke(monkeypatch, ["graph", "--no-watch"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""

    def test_unreadable_settings_is_silent(self, isolated, monkeypatch, capsys):
        self._write_settings(isolated, {"theme": "dark"})
        real_read_text = Path.read_text

        def unreadable(self_, *a, **k):
            if self_.name == "settings.json":
                raise OSError("permission denied")
            return real_read_text(self_, *a, **k)

        monkeypatch.setattr(Path, "read_text", unreadable)
        code = self._invoke(monkeypatch, ["graph", "--no-watch"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""

    def test_suppress_via_config_key(self, isolated, monkeypatch, capsys):
        """AC#5: suppress_setup_hint=true in statusline.conf silences the hint."""
        self._write_settings(isolated, {"theme": "dark"})
        self._write_conf(isolated, "suppress_setup_hint=true\n")
        self._invoke(monkeypatch, ["graph", "--no-watch"])
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize("value", ["1", "true"])
    def test_suppress_via_env_var(self, isolated, monkeypatch, capsys, value):
        """AC#5: CONTEXT_STATS_SUPPRESS_SETUP_HINT env var silences the hint."""
        self._write_settings(isolated, {"theme": "dark"})
        monkeypatch.setenv("CONTEXT_STATS_SUPPRESS_SETUP_HINT", value)
        self._invoke(monkeypatch, ["graph", "--no-watch"])
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize("argv", [["--help"], ["-h"], [], ["--version"], ["-V"], ["graph", "--help"]])
    def test_no_hint_on_help_and_version(self, isolated, monkeypatch, capsys, argv):
        """parse_args exits before the hint hook, so help/version never hint."""
        self._write_settings(isolated, {"theme": "dark"})
        with pytest.raises(SystemExit):
            _run_main(monkeypatch, argv)
        assert capsys.readouterr().err == ""

    def test_hint_preserves_stdout_for_every_action(self, isolated, monkeypatch, capsys):
        """AC#3: graph/export/report each emit the hint on stderr with a
        byte-identical stdout to the wired state."""
        from claude_statusline.cli import export as export_mod
        from claude_statusline.cli import report as report_mod

        monkeypatch.setattr(export_mod, "run_export", lambda argv: sys.stdout.write("EXPORT\n"))
        monkeypatch.setattr(
            report_mod, "run_report", lambda remaining: sys.stdout.write("REPORT\n")
        )

        for argv in (["graph", "--no-watch"], ["export"], ["report"]):
            outs = []
            for wired in (False, True):
                settings = (
                    {"statusLine": {"type": "command", "command": "claude-statusline"}}
                    if wired
                    else {"theme": "dark"}
                )
                self._write_settings(isolated, settings)
                code = self._invoke(monkeypatch, argv)
                captured = capsys.readouterr()
                assert code in (None, 0)
                outs.append(captured.out)
                assert captured.err == ("" if wired else self.HINT + "\n"), argv
            assert outs[0] == outs[1], f"stdout differs between wired/unwired for {argv}"

    def test_hint_never_raises_when_home_is_broken(self, isolated, monkeypatch, capsys):
        """AC#4: even a raising HOME/settings-path stays silent, never crashes."""
        from claude_statusline.cli import export as export_mod

        monkeypatch.setattr(export_mod, "run_export", lambda argv: None)

        def boom():
            raise OSError("home gone")

        monkeypatch.setattr(Path, "home", staticmethod(boom))
        _run_main(monkeypatch, ["export"])  # must not raise
        assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# main() — graph default flow (waiting message / insufficient data exits)
# ---------------------------------------------------------------------------


class TestMainGraphFlow:
    def test_graph_no_state_no_watch_shows_waiting_for_named_session(
        self, isolated, monkeypatch, capsys
    ):
        with pytest.raises(SystemExit) as ei:
            _run_main(monkeypatch, ["ghost-sess", "graph", "--no-watch"])
        assert ei.value.code == 0
        out = capsys.readouterr().out
        assert "(Session: ghost-sess)" in out

    def test_graph_no_state_no_watch_without_session(self, isolated, monkeypatch, capsys):
        with pytest.raises(SystemExit) as ei:
            _run_main(monkeypatch, ["graph", "--no-watch"])
        assert ei.value.code == 0
        out = capsys.readouterr().out
        assert "No session data found." in out

    def test_graph_existing_file_insufficient_data_exits_nonzero(
        self, isolated, monkeypatch, capsys
    ):
        _write_state([_entry()])
        with pytest.raises(SystemExit) as ei:
            _run_main(monkeypatch, ["sess-cli", "graph", "--no-watch"])
        assert ei.value.code == 1
        assert "Need at least 2 data points" in capsys.readouterr().out

    def test_graph_full_render_success_path(self, isolated, monkeypatch, capsys):
        """Two valid entries + --no-watch renders once and exits 0."""
        entries = [
            _entry(timestamp=1710288000),
            _entry(timestamp=1710288060, current_input_tokens=350),
        ]
        _write_state(entries)
        _run_main(monkeypatch, ["sess-cli", "graph", "--no-watch"])
        assert capsys.readouterr().out  # rendered output reached stdout
