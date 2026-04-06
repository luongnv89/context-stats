"""Pytest configuration and fixtures for statusline tests."""

import json
import sys
from pathlib import Path

import pytest


def pytest_sessionfinish(session, exitstatus):
    """Disable coverage tracer before atexit handlers run on Windows.

    On Windows, the coverage C extension's sys.settrace tracer can cause a
    KeyboardInterrupt in pytest's cleanup_numbered_dir atexit handler, making
    the process exit with code 1 even when all tests pass. Clearing the tracer
    here prevents that race between coverage cleanup and atexit callbacks.
    """
    if sys.platform == "win32":
        sys.settrace(None)
        sys.setprofile(None)

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
