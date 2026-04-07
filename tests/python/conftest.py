"""Pytest configuration and fixtures for statusline tests."""

import json
import sys
from pathlib import Path

import pytest


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """On Windows, fix spurious exit code 1 from coverage/pytest-cov teardown.

    On Windows, the coverage C extension's sys.settrace tracer can cause a
    KeyboardInterrupt in pytest's cleanup_numbered_dir atexit handler. This
    happens because cleanup_numbered_dir runs before coverage's own atexit
    (LIFO order) while the tracer is still active.

    Fix: register a final atexit handler (runs first in LIFO) that clears the
    tracer so cleanup_numbered_dir executes without interference.
    """
    if sys.platform == "win32":
        import atexit

        def _clear_coverage_tracer():
            sys.settrace(None)
            sys.setprofile(None)

        atexit.register(_clear_coverage_tracer)
        # Force exit code 0 when all collected tests passed (ignoring spurious
        # failures from pytest-cov coverage teardown on Windows).
        # We check the terminal reporter's stats rather than session.testsfailed
        # because pytest-cov may have incremented testsfailed during teardown.
        terminal = session.config.pluginmanager.getplugin("terminalreporter")
        if terminal is not None:
            stats = terminal.stats
            n_failed = len(stats.get("failed", []))
            n_error = len(stats.get("error", []))
            sys.stderr.write(
                f"[conftest] exitstatus={exitstatus} testsfailed={session.testsfailed} "
                f"n_failed={n_failed} n_error={n_error} collected={session.testscollected}\n"
            )
            if n_failed == 0 and n_error == 0 and session.testscollected > 0:
                sys.stderr.write("[conftest] Forcing exit code 0 on Windows\n")
                session.exitstatus = 0

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "json"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def scripts_dir():
    """Return the scripts directory."""
    return SCRIPTS_DIR


@pytest.fixture
def fixtures_dir():
    """Return the fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def valid_full_input():
    """Load valid_full.json fixture."""
    with open(FIXTURES_DIR / "valid_full.json") as f:
        return json.load(f)


@pytest.fixture
def valid_minimal_input():
    """Load valid_minimal.json fixture."""
    with open(FIXTURES_DIR / "valid_minimal.json") as f:
        return json.load(f)


@pytest.fixture
def low_usage_input():
    """Load low_usage.json fixture."""
    with open(FIXTURES_DIR / "low_usage.json") as f:
        return json.load(f)


@pytest.fixture
def medium_usage_input():
    """Load medium_usage.json fixture."""
    with open(FIXTURES_DIR / "medium_usage.json") as f:
        return json.load(f)


@pytest.fixture
def high_usage_input():
    """Load high_usage.json fixture."""
    with open(FIXTURES_DIR / "high_usage.json") as f:
        return json.load(f)


@pytest.fixture
def sample_input():
    """Return a sample input dictionary for testing."""
    return {
        "model": {"display_name": "Claude 3.5 Sonnet"},
        "workspace": {
            "current_dir": "/home/user/myproject",
            "project_dir": "/home/user/myproject",
        },
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 10000,
                "cache_creation_input_tokens": 500,
                "cache_read_input_tokens": 200,
            },
        },
    }
