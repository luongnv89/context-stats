"""Tests that MI always reflects context length: more free context = better MI.

This suite verifies the monotonicity property across all model profiles,
beta parameters, and zone alignment.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_statusline.core.state import StateEntry
from claude_statusline.graphs.intelligence import (
    calculate_context_pressure,
    calculate_intelligence,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _make_entry(
    current_input=0,
    context_window_size=200000,
    model_id="test-model",
) -> StateEntry:
    """Helper to create a StateEntry with sane defaults."""
    return StateEntry(
        timestamp=1000000,
        total_input_tokens=0,
        total_output_tokens=0,
        current_input_tokens=current_input,
        current_output_tokens=0,
        cache_creation=0,
        cache_read=0,
        cost_usd=0.0,
        lines_added=0,
        lines_removed=0,
        session_id="test",
        model_id=model_id,
        workspace_project_dir="/test",
        context_window_size=context_window_size,
    )


@pytest.fixture
def vectors():
    with open(FIXTURES_DIR / "mi_monotonicity_vectors.json") as f:
        return json.load(f)


# --- MI formula monotonicity (calculate_context_pressure) ---


class TestMIFormulaMonotonicity:
    """MI must strictly decrease as utilization increases."""

    def test_mi_decreases_with_utilization(self, vectors):
        steps = vectors["utilization_steps"]
        cw = vectors["context_window"]

        prev_mi = None
        for step in steps:
            u = step["used"] / cw
            mi = calculate_context_pressure(u)
            if prev_mi is not None:
                assert mi <= prev_mi, (
                    f"MI must decrease: at {step['pct']}% (MI={mi:.4f}) > "
                    f"previous (MI={prev_mi:.4f})"
                )
            prev_mi = mi

    def test_mi_strictly_decreases_for_nonzero_steps(self, vectors):
        steps = vectors["utilization_steps"]
        cw = vectors["context_window"]

        nonzero_steps = [s for s in steps if s["used"] > 0]
        prev_mi = None
        for step in nonzero_steps:
            u = step["used"] / cw
            mi = calculate_context_pressure(u)
            if prev_mi is not None:
                assert mi < prev_mi, (
                    f"MI must strictly decrease: at {step['pct']}% (MI={mi:.4f}) >= "
                    f"previous (MI={prev_mi:.4f})"
                )
            prev_mi = mi

    @pytest.mark.parametrize("beta", [1.0, 1.5, 2.0, 3.0])
    def test_mi_monotonic_for_all_beta(self, beta):
        prev_mi = None
        for pct in range(0, 101, 5):
            u = pct / 100.0
            mi = calculate_context_pressure(u, beta=beta)
            if prev_mi is not None:
                assert mi <= prev_mi, (
                    f"MI not monotonic at {pct}% with beta={beta}: {mi:.4f} > {prev_mi:.4f}"
                )
            prev_mi = mi

    def test_mi_boundary_values(self):
        assert calculate_context_pressure(0.0) == 1.0
        assert calculate_context_pressure(1.0) == 0.0


# --- Per-model MI monotonicity ---


class TestPerModelMonotonicity:
    """MI must decrease for every model profile."""

    def test_mi_decreases_for_all_models(self, vectors):
        steps = vectors["utilization_steps"]
        cw = vectors["context_window"]

        for scenario in vectors["model_scenarios"]:
            model_id = scenario["model_id"]
            prev_mi = None
            for step in steps:
                used = step["used"]
                cur = _make_entry(current_input=used, model_id=model_id)
                score = calculate_intelligence(cur, cw, model_id)

                if prev_mi is not None:
                    assert score.mi <= prev_mi + 1e-9, (
                        f"MI not monotonic for {scenario['description']} "
                        f"at {step['pct']}%: MI={score.mi:.4f} > prev={prev_mi:.4f}"
                    )
                prev_mi = score.mi

    @pytest.mark.parametrize("model_family", ["opus", "sonnet", "haiku"])
    def test_mi_monotonic_at_1pct_resolution(self, model_family):
        cw = 200000
        model_id = f"claude-{model_family}-test"
        prev_mi = None

        for pct in range(0, 101):
            used = int(pct / 100.0 * cw)
            cur = _make_entry(current_input=used, model_id=model_id)
            score = calculate_intelligence(cur, cw, model_id)

            if prev_mi is not None:
                assert score.mi <= prev_mi + 1e-9, (
                    f"MI increased at {pct}% for {model_family}: {score.mi:.6f} > {prev_mi:.6f}"
                )
            prev_mi = score.mi

    @pytest.mark.parametrize("beta", [1.0, 1.5, 2.0, 3.0])
    def test_mi_decreases_for_all_beta_overrides(self, beta):
        cw = 200000
        prev_mi = None

        for pct in range(0, 101, 5):
            used = int(pct / 100.0 * cw)
            cur = _make_entry(current_input=used)
            score = calculate_intelligence(cur, cw, "claude-opus-4-6", beta_override=beta)

            if prev_mi is not None:
                assert score.mi <= prev_mi + 1e-9, (
                    f"MI not monotonic at {pct}% with beta_override={beta}: "
                    f"{score.mi:.4f} > {prev_mi:.4f}"
                )
            prev_mi = score.mi


# --- Fine-grained resolution ---


class TestMIFineGrained:
    def test_mi_formula_monotonic_at_1pct_resolution(self):
        prev_mi = None
        for pct in range(0, 101):
            u = pct / 100.0
            mi = calculate_context_pressure(u)
            if prev_mi is not None:
                assert mi <= prev_mi + 1e-9, f"MI increased at {pct}%: {mi:.6f} > {prev_mi:.6f}"
            prev_mi = mi


# --- MI reflects context zones ---


class TestMIReflectsZones:
    def test_smart_zone_has_higher_mi_than_dumb_zone(self):
        cw = 200000
        smart = _make_entry(current_input=int(0.20 * cw))
        dumb = _make_entry(current_input=int(0.60 * cw))

        s_score = calculate_intelligence(smart, cw, "claude-sonnet-4-6")
        d_score = calculate_intelligence(dumb, cw, "claude-sonnet-4-6")

        assert s_score.mi > d_score.mi

    def test_dumb_zone_has_higher_mi_than_wrap_up_zone(self):
        cw = 200000
        dumb = _make_entry(current_input=int(0.60 * cw))
        wrap = _make_entry(current_input=int(0.90 * cw))

        d_score = calculate_intelligence(dumb, cw, "claude-sonnet-4-6")
        w_score = calculate_intelligence(wrap, cw, "claude-sonnet-4-6")

        assert d_score.mi > w_score.mi

    def test_empty_context_has_highest_mi(self):
        cw = 200000
        empty = _make_entry(current_input=0)
        score = calculate_intelligence(empty, cw, "claude-opus-4-6")
        assert score.mi == 1.0

    def test_full_context_is_zero_for_all_models(self):
        """All models reach MI=0.0 at full context."""
        cw = 200000
        for model in ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"]:
            full = _make_entry(current_input=cw, model_id=model)
            score = calculate_intelligence(full, cw, model)
            assert score.mi == 0.0, f"{model} should be 0.0 at full context"

    def test_opus_higher_mi_than_sonnet_at_same_utilization(self):
        cw = 200000
        used = int(0.7 * cw)
        opus = _make_entry(current_input=used)
        sonnet = _make_entry(current_input=used)

        o_score = calculate_intelligence(opus, cw, "claude-opus-4-6")
        s_score = calculate_intelligence(sonnet, cw, "claude-sonnet-4-6")

        assert o_score.mi > s_score.mi

    def test_mi_spread_covers_meaningful_range(self):
        """For sonnet, MI spread from 0% to 100% should be 0.50."""
        cw = 200000
        empty = _make_entry(current_input=0)
        full = _make_entry(current_input=cw)

        mi_empty = calculate_intelligence(empty, cw, "claude-sonnet-4-6").mi
        mi_full = calculate_intelligence(full, cw, "claude-sonnet-4-6").mi

        spread = mi_empty - mi_full
        assert spread >= 0.5, (
            f"MI spread too small: {mi_empty:.4f} - {mi_full:.4f} = {spread:.4f} < 0.5"
        )
