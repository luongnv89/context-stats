"""End-to-end install diagnostics for context-stats (issue #186).

``pip install context-stats`` installs the ``claude-statusline`` and
``context-stats`` entry points but cannot wire ``statusLine`` into Claude
Code's ``~/.claude/settings.json`` — that activation step lives in the README.
A user who misses it gets a silently absent status line and no signal at all
about which half of the install is missing.

``context-stats doctor`` closes that gap. It checks every link in the chain
without needing a live Claude Code payload (unlike ``explain``, which requires
stdin from an already-working status line):

1. entry points resolvable on ``PATH``
2. a sandboxed smoke render of the statusline command
3. ``~/.claude/settings.json`` — present, valid JSON, ``statusLine`` wired to a
   command that actually resolves
4. state directory and optional ``~/.claude/statusline.conf``

``--fix`` repairs step 3 in place: idempotent, key-preserving, backed up, and
refusing to clobber a *different* configured status line without ``--force``.
"""

from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from claude_statusline.core.colors import ColorManager

#: Command written into ``settings.json`` by ``--fix``. Matches the
#: ``claude-statusline`` console script declared in ``pyproject.toml``.
DEFAULT_STATUSLINE_COMMAND = "claude-statusline"

#: Console scripts the wheel installs. Both must resolve for a healthy setup.
ENTRY_POINTS = ("claude-statusline", "context-stats")

#: Seconds before the smoke render is considered hung. Generous: the render
#: shells out to git/gh, each already bounded by its own 5s timeout.
_SMOKE_TIMEOUT_SECONDS = 20

_PASS = "pass"
_WARN = "warn"
_FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    """One diagnostic line plus any remediation hints printed beneath it."""

    status: str
    message: str
    hints: tuple[str, ...] = ()


@dataclass
class DoctorReport:
    """Accumulated results, grouped under the section headings shown to users."""

    sections: list[tuple[str, list[CheckResult]]] = field(default_factory=list)

    def add(self, section: str, result: CheckResult) -> None:
        """Append ``result`` to ``section``, creating the section on first use."""
        for name, results in self.sections:
            if name == section:
                results.append(result)
                return
        self.sections.append((section, [result]))

    def counts(self) -> tuple[int, int, int]:
        """Return ``(passed, warned, failed)`` across every section."""
        passed = warned = failed = 0
        for _, results in self.sections:
            for r in results:
                if r.status == _PASS:
                    passed += 1
                elif r.status == _WARN:
                    warned += 1
                else:
                    failed += 1
        return passed, warned, failed


# ─── Paths (resolved per call so a patched HOME is always honored) ───


def settings_path() -> Path:
    """Path to Claude Code's user settings file."""
    return Path.home() / ".claude" / "settings.json"


def state_dir() -> Path:
    """Directory holding the append-only CSV state files."""
    return Path.home() / ".claude" / "statusline"


def config_path() -> Path:
    """Path to the optional statusline configuration file."""
    return Path.home() / ".claude" / "statusline.conf"


# ─── Individual checks ───


def _resolve_statusline_command() -> list[str] | None:
    """Return an argv able to run the statusline, or None if unavailable.

    Prefers the installed console script (what ``settings.json`` will name);
    falls back to ``python -m claude_statusline`` so a source checkout or a
    PATH-less install still gets a meaningful smoke test.
    """
    found = shutil.which(DEFAULT_STATUSLINE_COMMAND)
    if found:
        return [found]
    try:
        import claude_statusline  # noqa: F401
    except ImportError:  # pragma: no cover - the CLI cannot run without it
        return None
    return [sys.executable, "-m", "claude_statusline"]


def check_entry_points(report: DoctorReport) -> None:
    """Verify both console scripts resolve on PATH."""
    for name in ENTRY_POINTS:
        location = shutil.which(name)
        if location:
            report.add("Entry points", CheckResult(_PASS, f"{name} → {location}"))
        else:
            report.add(
                "Entry points",
                CheckResult(
                    _FAIL,
                    f"{name} not found on PATH",
                    (
                        "Reinstall with: pip install --force-reinstall context-stats",
                        "Then make sure pip's script directory is on your PATH "
                        "(python -m site --user-base)/bin",
                    ),
                ),
            )


def _user_base() -> str | None:
    """Real per-user install prefix, resolved before HOME is sandboxed.

    ``site.getuserbase()`` is memoized against the current HOME, so it must be
    read in this process rather than inside the sandboxed child.
    """
    try:
        return site.getuserbase()
    except Exception:  # pragma: no cover - defensive; getuserbase is total
        return None


def _smoke_payload(project_dir: Path) -> str:
    """Minimal stdin payload matching Claude Code's current statusline schema."""
    return json.dumps(
        {
            "hook_event_name": "Status",
            "session_id": "context-stats-doctor",
            "model": {"display_name": "Claude", "id": "claude-sonnet-4-20250514"},
            "workspace": {
                "current_dir": str(project_dir),
                "project_dir": str(project_dir),
            },
            "context_window": {
                "context_window_size": 200000,
                "total_input_tokens": 1000,
                "total_output_tokens": 500,
                "current_usage": {
                    "input_tokens": 10000,
                    "output_tokens": 900,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 200,
                },
            },
            "cost": {
                "total_cost_usd": 0.01,
                "total_api_duration_ms": 1200,
                "total_lines_added": 10,
                "total_lines_removed": 2,
            },
        }
    )


def check_smoke_render(report: DoctorReport) -> None:
    """Render a synthetic payload in a sandboxed HOME and assert it is real output.

    The render catch-all in ``cli/statusline.py`` emits ``[Claude] ~`` for any
    unexpected exception, so "produced output" alone proves nothing. A working
    statusline echoes the project directory name; the fallback never does.
    """
    argv = _resolve_statusline_command()
    if argv is None:
        report.add(
            "Statusline render",
            CheckResult(_FAIL, "no runnable statusline command found", ()),
        )
        return

    with tempfile.TemporaryDirectory() as sandbox:
        project_dir = Path(sandbox) / "doctor-smoke-project"
        project_dir.mkdir()
        env = dict(os.environ, HOME=sandbox, USERPROFILE=sandbox)
        # HOME is redirected so the smoke render cannot touch real state — but
        # `pip install --user` resolves site-packages *from* HOME, so a naive
        # override makes the console script fail to import its own package and
        # the check reports a false negative. Pin the real user base so module
        # resolution survives the sandbox.
        user_base = _user_base()
        if user_base:
            env.setdefault("PYTHONUSERBASE", user_base)
        try:
            proc = subprocess.run(
                argv,
                input=_smoke_payload(project_dir),
                capture_output=True,
                text=True,
                timeout=_SMOKE_TIMEOUT_SECONDS,
                env=env,
                cwd=sandbox,
            )
        except subprocess.TimeoutExpired:
            report.add(
                "Statusline render",
                CheckResult(
                    _FAIL,
                    f"statusline timed out after {_SMOKE_TIMEOUT_SECONDS}s",
                    ("A hung git or gh subprocess is the usual cause.",),
                ),
            )
            return
        except OSError as e:
            report.add("Statusline render", CheckResult(_FAIL, f"could not run {argv[0]}: {e}"))
            return

    label = " ".join(argv)
    if proc.returncode != 0:
        report.add(
            "Statusline render",
            CheckResult(
                _FAIL,
                f"{label} exited {proc.returncode}",
                tuple(line for line in proc.stderr.strip().splitlines()[:5] if line),
            ),
        )
        return
    if "doctor-smoke-project" not in proc.stdout:
        report.add(
            "Statusline render",
            CheckResult(
                _FAIL,
                f"{label} produced no usable status line (crash fallback)",
                (f"Output was: {proc.stdout.strip()[:120] or '(empty)'}",),
            ),
        )
        return
    report.add("Statusline render", CheckResult(_PASS, f"{label} renders a status line"))


def _read_settings(path: Path) -> tuple[dict | None, str | None]:
    """Return ``(settings, error)``; ``({}, None)`` when the file is absent."""
    if not path.exists():
        return {}, None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"cannot read {path}: {e}"
    if not raw.strip():
        return {}, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"{path} is not valid JSON: {e}"
    if not isinstance(data, dict):
        return None, f"{path} must contain a JSON object, got {type(data).__name__}"
    return data, None


def _command_resolves(command: str) -> bool:
    """True when a configured statusLine command can actually be executed."""
    expanded = os.path.expanduser(command)
    # Settings may hold a bare name, an absolute path, or a path with args.
    head = expanded.split()[0] if expanded.split() else ""
    if not head:
        return False
    if shutil.which(head):
        return True
    candidate = Path(head)
    return candidate.is_file() and os.access(candidate, os.X_OK)


def check_settings(report: DoctorReport) -> None:
    """The check that catches issue #186: statusLine missing from settings.json."""
    path = settings_path()
    settings, error = _read_settings(path)
    if error is not None:
        report.add(
            "Claude Code settings",
            CheckResult(
                _FAIL, error, ("Repair the file by hand; doctor --fix will not touch it.",)
            ),
        )
        return

    assert settings is not None  # narrowed by the error branch above
    if not path.exists():
        report.add("Claude Code settings", CheckResult(_WARN, f"{path} does not exist yet"))
    else:
        report.add("Claude Code settings", CheckResult(_PASS, f"{path} is valid JSON"))

    block = settings.get("statusLine")
    if not isinstance(block, dict) or not block.get("command"):
        report.add(
            "Claude Code settings",
            CheckResult(
                _FAIL,
                "statusLine is not configured — the status line will never run",
                (
                    "Fix automatically: context-stats doctor --fix",
                    'Or add: "statusLine": {"type": "command", '
                    f'"command": "{DEFAULT_STATUSLINE_COMMAND}"}}',
                    "Restart Claude Code afterwards.",
                ),
            ),
        )
        return

    command = str(block.get("command"))
    kind = block.get("type")
    if kind != "command":
        report.add(
            "Claude Code settings",
            CheckResult(
                _FAIL,
                f'statusLine.type is {kind!r}, expected "command"',
                ("Fix automatically: context-stats doctor --fix --force",),
            ),
        )
        return

    if not _command_resolves(command):
        report.add(
            "Claude Code settings",
            CheckResult(
                _FAIL,
                f"statusLine.command does not resolve: {command}",
                ("Fix automatically: context-stats doctor --fix --force",),
            ),
        )
        return

    report.add("Claude Code settings", CheckResult(_PASS, f"statusLine.command = {command}"))
    if DEFAULT_STATUSLINE_COMMAND not in command:
        report.add(
            "Claude Code settings",
            CheckResult(
                _WARN,
                "statusLine points at a different status line, not context-stats",
                ("Point it at context-stats with: context-stats doctor --fix --force",),
            ),
        )


def check_runtime_state(report: DoctorReport) -> None:
    """State directory and optional config file — advisory, never fatal."""
    directory = state_dir()
    if directory.is_dir():
        sessions = len(list(directory.glob("statusline.*.state")))
        report.add(
            "Runtime state",
            CheckResult(_PASS, f"{directory} exists ({sessions} session file(s))"),
        )
    else:
        report.add(
            "Runtime state",
            CheckResult(
                _WARN,
                f"{directory} not created yet",
                ("Normal on a fresh install — the first session creates it.",),
            ),
        )

    conf = config_path()
    if conf.is_file():
        report.add("Runtime state", CheckResult(_PASS, f"{conf} found"))
    else:
        report.add(
            "Runtime state",
            CheckResult(_WARN, f"{conf} not found (built-in defaults apply)"),
        )


# ─── --fix ───


def _backup_settings(path: Path) -> Path:
    """Copy ``path`` beside itself with a timestamped suffix, returning the copy."""
    backup = path.with_name(f"{path.name}.bak.{time.strftime('%Y%m%d-%H%M%S')}")
    n = 1
    while backup.exists():
        backup = backup.with_name(f"{backup.name}.{n}")
        n += 1
    shutil.copy2(path, backup)
    return backup


def _write_settings(path: Path, settings: dict) -> None:
    """Write ``settings`` as pretty JSON via a temp file + atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def apply_fix(report: DoctorReport, force: bool, command: str = DEFAULT_STATUSLINE_COMMAND) -> None:
    """Wire ``statusLine`` into settings.json, preserving every other key.

    Idempotent: an already-correct block is left untouched and no backup is
    taken. A *different* configured status line is preserved unless ``force``
    is set, so ``--fix`` can never silently displace another tool.
    """
    path = settings_path()
    settings, error = _read_settings(path)
    if error is not None:
        report.add("Repair", CheckResult(_FAIL, f"refusing to write: {error}"))
        return

    assert settings is not None
    desired = {"type": "command", "command": command}
    existing = settings.get("statusLine")

    if existing == desired:
        report.add("Repair", CheckResult(_PASS, "statusLine already configured — nothing to do"))
        return

    if existing is not None and not force:
        report.add(
            "Repair",
            CheckResult(
                _FAIL,
                f"statusLine already set to {json.dumps(existing)} — left untouched",
                ("Overwrite it with: context-stats doctor --fix --force",),
            ),
        )
        return

    if path.exists():
        try:
            backup = _backup_settings(path)
        except OSError as e:
            report.add("Repair", CheckResult(_FAIL, f"could not back up {path}: {e}"))
            return
        report.add("Repair", CheckResult(_PASS, f"backed up settings to {backup}"))

    settings["statusLine"] = desired
    try:
        _write_settings(path, settings)
    except OSError as e:
        report.add("Repair", CheckResult(_FAIL, f"could not write {path}: {e}"))
        return

    report.add("Repair", CheckResult(_PASS, f'statusLine set to "{command}" in {path}'))
    report.add("Repair", CheckResult(_WARN, "Restart Claude Code to activate the status line."))


# ─── Rendering + entry point ───


def _status_glyph(status: str, colors: ColorManager) -> str:
    if status == _PASS:
        return f"{colors.green}✓{colors.reset}"
    if status == _WARN:
        return f"{colors.yellow}!{colors.reset}"
    return f"{colors.red}✗{colors.reset}"


def render_report(report: DoctorReport, colors: ColorManager) -> None:
    """Print every section, then a summary line."""
    print(f"{colors.bold}context-stats doctor{colors.reset}")
    print("─" * 60)
    for name, results in report.sections:
        print()
        print(f"{colors.bold}{name}{colors.reset}")
        for result in results:
            print(f"  {_status_glyph(result.status, colors)} {result.message}")
            for hint in result.hints:
                print(f"      {colors.dim}{hint}{colors.reset}")

    passed, warned, failed = report.counts()
    print()
    print("─" * 60)
    if failed:
        print(
            f"{colors.red}{failed} check(s) failed{colors.reset} — "
            f"{passed} passed, {warned} warning(s)"
        )
    else:
        print(
            f"{colors.green}All checks passed{colors.reset} — {passed} passed, {warned} warning(s)"
        )


_DOCTOR_HELP = """Usage: context-stats doctor [--fix] [--force] [--no-color]

Diagnose the context-stats installation end to end: entry points on PATH, a
sandboxed statusline render, the statusLine wiring in ~/.claude/settings.json,
and the runtime state directory.

OPTIONS:
    --fix        Write the statusLine block into ~/.claude/settings.json
                 (idempotent, other keys preserved, existing file backed up)
    --force      With --fix, replace a statusLine that is already set to
                 something else
    --no-color   Disable color output
    --help, -h   Show this help

Exit status is 0 when every check passes and 1 when any check fails."""


def run_doctor(argv: list[str], colors: ColorManager) -> int:
    """Run the diagnostics (and optional repair); return a process exit code."""
    fix = force = False
    for arg in argv:
        if arg == "--fix":
            fix = True
        elif arg == "--force":
            force = True
        elif arg == "--no-color":
            continue
        elif arg in ("--help", "-h"):
            print(_DOCTOR_HELP)
            return 0
        else:
            sys.stderr.write(f"Error: Unknown flag for doctor: '{arg}'\n")
            sys.stderr.write("Run 'context-stats doctor --help' for usage.\n")
            return 1

    if force and not fix:
        sys.stderr.write("Error: --force requires --fix\n")
        return 1

    report = DoctorReport()
    check_entry_points(report)
    check_smoke_render(report)
    if fix:
        apply_fix(report, force=force)
    check_settings(report)
    check_runtime_state(report)

    render_report(report, colors)
    _, _, failed = report.counts()
    return 1 if failed else 0
