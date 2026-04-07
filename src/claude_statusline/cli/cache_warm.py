"""Cache-warm subcommand for keeping Claude Code session cache alive.

Manages a background heartbeat process that prevents the Claude prompt cache
(~5 minute TTL) from expiring during gaps between interactions.

Usage:
    context-stats <session_id> cache-warm on [duration]
    context-stats <session_id> cache-warm off
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
from pathlib import Path

# Default heartbeat settings
DEFAULT_DURATION = 30 * 60  # 30 minutes
DEFAULT_INTERVAL = 4 * 60   # 4 minutes (under 5-min cache TTL)

# State file path template: ~/.claude/statusline/cache-warm.<session_id>.json
_STATE_DIR = Path.home() / ".claude" / "statusline"


def _warm_state_path(session_id: str) -> Path:
    return _STATE_DIR / f"cache-warm.{session_id}.json"


def _parse_duration(value: str) -> int:
    """Parse a human-readable duration like '30m', '1h', '90s' into seconds.

    Args:
        value: Duration string with optional unit suffix (s/m/h). Bare integers are seconds.

    Returns:
        Duration in seconds.

    Raises:
        ValueError: If the format is unrecognized.
    """
    m = re.fullmatch(r"(\d+)([smh]?)", value.strip().lower())
    if not m:
        raise ValueError(f"Cannot parse duration '{value}'. Use formats like 30m, 1h, 90s.")
    amount = int(m.group(1))
    unit = m.group(2) or "s"
    multiplier = {"s": 1, "m": 60, "h": 3600}[unit]
    return amount * multiplier


def load_warm_state(session_id: str) -> dict | None:
    """Load persisted cache-warm state for a session.

    Returns:
        Dict with keys: pid, start_time, expiry_time, interval — or None if not found.
    """
    path = _warm_state_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _save_warm_state(session_id: str, state: dict) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _warm_state_path(session_id).write_text(json.dumps(state))


def _clear_warm_state(session_id: str) -> None:
    path = _warm_state_path(session_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _is_process_alive(pid: int) -> bool:
    """Return True if the given PID is a running process."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def is_cache_warm_active(session_id: str) -> tuple[bool, int]:
    """Check if cache-warm is currently active for the session.

    Returns:
        (active, seconds_remaining) — active is False when expired or not running.
    """
    state = load_warm_state(session_id)
    if state is None:
        return False, 0

    now = int(time.time())
    expiry = state.get("expiry_time", 0)
    pid = state.get("pid", 0)

    if now >= expiry:
        _clear_warm_state(session_id)
        return False, 0

    if pid and not _is_process_alive(pid):
        _clear_warm_state(session_id)
        return False, 0

    remaining = expiry - now
    return True, remaining


def _run_heartbeat_loop(session_id: str, expiry_time: int, interval: int) -> None:
    """Heartbeat loop — runs in a forked background process.

    Emits a tiny no-op write to the session state file every `interval` seconds
    to signal cache activity without touching the main CSV data stream.
    Exits automatically when expiry_time is reached.
    """
    # Detach from parent: new session, close stdio
    os.setsid()
    sys.stdin.close()
    sys.stdout.close()
    sys.stderr.close()

    heartbeat_file = _STATE_DIR / f"cache-warm.{session_id}.heartbeat"

    while True:
        now = int(time.time())
        if now >= expiry_time:
            # Expired — clean up and exit
            _clear_warm_state(session_id)
            try:
                heartbeat_file.unlink(missing_ok=True)
            except OSError:
                pass
            break

        # Write heartbeat timestamp
        try:
            heartbeat_file.write_text(str(now))
        except OSError:
            pass

        time.sleep(interval)


def cmd_cache_warm_on(session_id: str, duration_str: str | None, colors: object) -> None:
    """Handle 'cache-warm on [duration]'.

    Args:
        session_id: Session ID to warm.
        duration_str: Optional duration string (e.g. '30m'). Defaults to 30 minutes.
        colors: ColorManager instance for output.
    """
    c = colors  # shorthand

    # Parse duration
    duration = DEFAULT_DURATION
    if duration_str:
        try:
            duration = _parse_duration(duration_str)
        except ValueError as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.exit(1)

    # Check if already active
    active, remaining = is_cache_warm_active(session_id)
    old_state = load_warm_state(session_id) if active else None
    if active:
        mins = remaining // 60
        secs = remaining % 60
        print(
            f"{c.yellow}Cache-warm already active for session {session_id} "
            f"({mins}m {secs}s remaining). Refreshing duration.{c.reset}"
        )

    now = int(time.time())
    expiry = now + duration

    # Fork a background process for the heartbeat loop
    if not hasattr(os, "fork"):
        sys.stderr.write(
            "Error: cache-warm requires a Unix-like OS (fork not available).\n"
        )
        sys.exit(1)

    # Set SIGCHLD to SIG_IGN before fork so the kernel auto-reaps the child (no zombie).
    # Restore the original handler in the parent afterwards to avoid breaking subprocess calls.
    # signal.SIGCHLD only exists on Unix; guard for portability in test environments.
    _has_sigchld = hasattr(signal, "SIGCHLD")
    old_sigchld = signal.signal(signal.SIGCHLD, signal.SIG_IGN) if _has_sigchld else None
    try:
        pid = os.fork()
    except OSError as e:
        if _has_sigchld:
            signal.signal(signal.SIGCHLD, old_sigchld)
        sys.stderr.write(f"Error: fork failed: {e}\n")
        sys.exit(1)

    if pid == 0:
        # Child process — run heartbeat loop and exit
        try:
            _run_heartbeat_loop(session_id, expiry, DEFAULT_INTERVAL)
        except Exception:
            pass
        os._exit(0)
    else:
        # Parent process — restore SIGCHLD handler, persist state, stop old process
        if _has_sigchld:
            signal.signal(signal.SIGCHLD, old_sigchld)
        # Persist state first (avoids race window when refreshing)
        _save_warm_state(
            session_id,
            {
                "pid": pid,
                "start_time": now,
                "expiry_time": expiry,
                "interval": DEFAULT_INTERVAL,
            },
        )
        # Terminate old process only after new state is persisted
        if old_state:
            old_pid = old_state.get("pid", 0)
            if old_pid and _is_process_alive(old_pid):
                try:
                    os.kill(old_pid, signal.SIGTERM)
                except OSError:
                    pass
            heartbeat_file = _STATE_DIR / f"cache-warm.{session_id}.heartbeat"
            try:
                heartbeat_file.unlink(missing_ok=True)
            except OSError:
                pass
        mins = duration // 60
        remaining_fmt = f"{mins}m" if duration % 60 == 0 else f"{mins}m {duration % 60}s"
        print(
            f"{c.green}Cache-warm activated for session {session_id}.{c.reset}\n"
            f"{c.dim}Heartbeat every {DEFAULT_INTERVAL // 60} minutes, "
            f"auto-stops in {remaining_fmt}.{c.reset}"
        )


def cmd_cache_warm_off(session_id: str, colors: object, silent: bool = False) -> None:
    """Handle 'cache-warm off'.

    Args:
        session_id: Session ID to stop.
        colors: ColorManager instance for output.
        silent: If True, suppress output (used when refreshing duration).
    """
    c = colors

    state = load_warm_state(session_id)
    if state is None:
        if not silent:
            print(f"{c.dim}No active cache-warm for session {session_id}.{c.reset}")
        return

    pid = state.get("pid", 0)
    if pid and _is_process_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    _clear_warm_state(session_id)

    # Remove heartbeat file too
    heartbeat_file = _STATE_DIR / f"cache-warm.{session_id}.heartbeat"
    try:
        heartbeat_file.unlink(missing_ok=True)
    except OSError:
        pass

    if not silent:
        print(f"{c.green}Cache-warm stopped for session {session_id}.{c.reset}")


def run_cache_warm(session_id: str, argv: list[str], colors: object) -> None:
    """Dispatch cache-warm subcommand.

    Args:
        session_id: Session ID.
        argv: Remaining arguments after 'cache-warm'.
        colors: ColorManager for output.
    """
    c = colors

    if not argv:
        print(
            f"{c.bold}Usage:{c.reset}\n"
            f"  context-stats <session_id> cache-warm on [duration]   "
            f"# e.g. 30m, 1h\n"
            f"  context-stats <session_id> cache-warm off\n"
        )
        sys.exit(0)

    subcmd = argv[0]

    if subcmd == "on":
        duration_str = argv[1] if len(argv) > 1 else None
        cmd_cache_warm_on(session_id, duration_str, c)

    elif subcmd == "off":
        cmd_cache_warm_off(session_id, c)

    else:
        sys.stderr.write(
            f"Error: Unknown cache-warm subcommand '{subcmd}'. "
            "Use 'on [duration]' or 'off'.\n"
        )
        sys.exit(1)
