"""Tests for Model Intelligence (MI) score computation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_statusline.core.state import StateEntry
from claude_statusline.graphs.intelligence import (
    _ZONE_RECOMMENDATIONS,
    MI_GREEN_THRESHOLD,
    MI_YELLOW_THRESHOLD,
    MODEL_PROFILES,
    ZONE_1M_C_MAX,
    ZONE_1M_D_MAX,
    ZONE_1M_P_MAX,
    ZONE_1M_X_MAX,
    calculate_context_pressure,
    calculate_intelligence,
    format_mi_score,
    get_context_zone,
    get_mi_color,
    get_model_profile,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _make_entry(
    current_input=0,
    cache_creation=0,
    cache_read=0,
    total_output=0,
    lines_added=0,
    lines_removed=0,
    context_window_size=200000,
    model_id="test-model",
) -> StateEntry:
    """Helper to create a StateEntry with sane defaults."""
    return StateEntry(
        timestamp=1000000,
        total_input_tokens=0,
        total_output_tokens=total_output,
        current_input_tokens=current_input,
        current_output_tokens=0,
        cache_creation=cache_creation,
        cache_read=cache_read,
        cost_usd=0.0,
        lines_added=lines_added,
        lines_removed=lines_removed,
        session_id="test",
        model_id=model_id,
        workspace_project_dir="/test",
        context_window_size=context_window_size,
    )


# --- Model profile tests ---


class TestModelProfile:
    def test_opus_detected(self):
        assert get_model_profile("claude-opus-4-6[1m]") == MODEL_PROFILES["opus"]

    def test_sonnet_detected(self):
        assert get_model_profile("claude-sonnet-4-6") == MODEL_PROFILES["sonnet"]

    def test_haiku_detected(self):
        assert get_model_profile("claude-haiku-4-5-20251001") == MODEL_PROFILES["haiku"]

    def test_unknown_falls_back_to_default(self):
        assert get_model_profile("unknown-model-xyz") == MODEL_PROFILES["default"]

    def test_case_insensitive(self):
        assert get_model_profile("Claude-OPUS-4-6") == MODEL_PROFILES["opus"]

    def test_empty_string_returns_default(self):
        assert get_model_profile("") == MODEL_PROFILES["default"]

    def test_all_profiles_are_positive(self):
        for name, beta in MODEL_PROFILES.items():
            assert beta > 0, f"Profile {name} beta must be positive"

    def test_opus_retains_quality_longest(self):
        """Higher beta = quality retained longer. Opus should have highest beta."""
        assert MODEL_PROFILES["opus"] > MODEL_PROFILES["sonnet"]
        assert MODEL_PROFILES["sonnet"] > MODEL_PROFILES["haiku"]


# --- MI formula tests ---


class TestContextPressure:
    def test_empty_context(self):
        assert calculate_context_pressure(0.0) == 1.0

    def test_full_context(self):
        # MI = 1 - 1^beta = 0 for any beta
        assert calculate_context_pressure(1.0) == 0.0

    def test_half_context_default(self):
        mi = calculate_context_pressure(0.5)
        assert 0.64 < mi < 0.66  # 1 - 0.5^1.5 ≈ 0.646

    def test_custom_beta_linear(self):
        mi = calculate_context_pressure(0.5, beta=1.0)
        assert mi == pytest.approx(0.5, abs=0.01)

    def test_custom_beta_quadratic(self):
        mi = calculate_context_pressure(0.5, beta=2.0)
        assert mi == pytest.approx(0.75, abs=0.01)

    def test_over_capacity_clamped(self):
        mi = calculate_context_pressure(1.5)
        assert mi == 0.0

    def test_negative_utilization(self):
        assert calculate_context_pressure(-0.1) == 1.0


# --- Guard clause ---


class TestGuardClause:
    def test_zero_context_window(self):
        entry = _make_entry(current_input=50000)
        score = calculate_intelligence(entry, context_window_size=0)
        assert score.mi == 1.0
        assert score.utilization == 0.0


# --- Composite MI tests ---


class TestComposite:
    def test_fresh_opus_session(self):
        cur = _make_entry(current_input=10000, model_id="claude-opus-4-6")
        score = calculate_intelligence(cur, 200000, "claude-opus-4-6")
        assert score.mi > 0.98

    def test_full_context_always_zero(self):
        """All models reach MI=0.0 at full context (alpha=1.0 for all)."""
        for model in ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"]:
            cur = _make_entry(current_input=200000, model_id=model)
            score = calculate_intelligence(cur, 200000, model)
            assert score.mi == 0.0, f"{model} at full context should be 0.0"

    def test_opus_retains_longer_than_sonnet(self):
        """Opus should have higher MI than sonnet at same utilization."""
        cur_o = _make_entry(current_input=100000, model_id="claude-opus-4-6")
        cur_s = _make_entry(current_input=100000, model_id="claude-sonnet-4-6")
        o = calculate_intelligence(cur_o, 200000, "claude-opus-4-6")
        s = calculate_intelligence(cur_s, 200000, "claude-sonnet-4-6")
        assert o.mi > s.mi

    def test_beta_override(self):
        cur = _make_entry(current_input=100000, model_id="claude-opus-4-6")
        score = calculate_intelligence(cur, 200000, "claude-opus-4-6", beta_override=1.0)
        # MI = 1 - 0.5^1.0 = 0.5
        assert score.mi == pytest.approx(0.5, abs=0.01)

    def test_bounds(self):
        """MI should always be in [0, 1]."""
        for u in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
            used = int(u * 200000)
            cur = _make_entry(current_input=used)
            score = calculate_intelligence(cur, 200000, "claude-sonnet-4-6")
            assert 0.0 <= score.mi <= 1.0, f"MI out of bounds at u={u}: {score.mi}"

    def test_uses_entry_model_id_if_not_provided(self):
        cur = _make_entry(current_input=100000, model_id="claude-opus-4-6")
        score = calculate_intelligence(cur, 200000)
        opus_expected = calculate_intelligence(cur, 200000, "claude-opus-4-6")
        assert score.mi == pytest.approx(opus_expected.mi, abs=0.001)


# --- Color tests ---


class TestColor:
    def test_green_high_mi_low_util(self):
        assert get_mi_color(0.95, 0.10) == "green"

    def test_yellow_mi_below_green(self):
        assert get_mi_color(0.85, 0.10) == "yellow"

    def test_yellow_context_in_warning_zone(self):
        """MI is green but context 40-80% forces yellow."""
        assert get_mi_color(0.95, 0.50) == "yellow"

    def test_red_mi_critically_low(self):
        assert get_mi_color(0.75, 0.10) == "red"

    def test_red_context_nearly_full(self):
        """MI is decent but context >80% forces red."""
        assert get_mi_color(0.95, 0.85) == "red"

    def test_boundary_green_threshold(self):
        assert get_mi_color(MI_GREEN_THRESHOLD, 0.0) == "green"
        assert get_mi_color(MI_GREEN_THRESHOLD - 0.001, 0.0) == "yellow"

    def test_boundary_yellow_threshold(self):
        assert get_mi_color(MI_YELLOW_THRESHOLD + 0.001, 0.0) == "yellow"
        assert get_mi_color(MI_YELLOW_THRESHOLD, 0.0) == "red"

    def test_context_overrides_mi(self):
        """Context utilization can override MI-based color."""
        # MI says green, but context 80%+ forces red
        assert get_mi_color(0.95, 0.80) == "red"
        # MI says green, but context 40%+ forces yellow
        assert get_mi_color(0.95, 0.40) == "yellow"

    def test_default_utilization(self):
        """When utilization not provided, only MI matters."""
        assert get_mi_color(0.95) == "green"
        assert get_mi_color(0.85) == "yellow"
        assert get_mi_color(0.75) == "red"


# --- Format tests ---


class TestFormat:
    def test_three_decimals(self):
        assert format_mi_score(0.823) == "0.823"

    def test_zero(self):
        assert format_mi_score(0.0) == "0.000"

    def test_one(self):
        assert format_mi_score(1.0) == "1.000"

    def test_rounding(self):
        assert format_mi_score(0.82449) == "0.824"
        assert format_mi_score(0.82451) == "0.825"


# --- Shared test vectors ---


class TestSharedVectors:
    """Test against shared vectors for cross-implementation parity."""

    @pytest.fixture
    def vectors(self):
        with open(FIXTURES_DIR / "mi_test_vectors.json") as f:
            return json.load(f)

    def test_all_vectors(self, vectors):
        for vec in vectors:
            inp = vec["input"]
            exp = vec["expected"]

            cur = _make_entry(
                current_input=inp["current_used"],
                model_id=inp["model_id"],
                context_window_size=inp["context_window"],
            )

            beta_override = inp["beta_override"] if inp["beta_override"] is not None else 0.0

            score = calculate_intelligence(
                cur, inp["context_window"], inp["model_id"], beta_override
            )

            assert score.mi == pytest.approx(exp["mi"], abs=0.01), (
                f"MI mismatch for '{vec['description']}': got {score.mi:.4f}, expected {exp['mi']}"
            )
            assert score.utilization == pytest.approx(exp["utilization"], abs=0.01), (
                f"Utilization mismatch for '{vec['description']}': "
                f"got {score.utilization:.4f}, expected {exp['utilization']}"
            )


# --- Context zone tests ---


class TestContextZone:
    """Test the five-state context zone indicator (P/C/D/X/Z)."""

    # --- 1M model tests (context_window >= 500k) ---

    def test_1m_planning_zone(self):
        """1M model, 100k used → P (green). New threshold: < 150k."""
        zone = get_context_zone(100_000, 1_000_000)
        assert zone.zone == "Plan"
        assert zone.color == "green"

    def test_1m_code_only_zone(self):
        """1M model, 200k used → C (yellow). New range: 150k–250k."""
        zone = get_context_zone(200_000, 1_000_000)
        assert zone.zone == "Code"
        assert zone.color == "yellow"

    def test_1m_dump_zone(self):
        """1M model, 300k used → D (orange). New range: 250k–400k."""
        zone = get_context_zone(300_000, 1_000_000)
        assert zone.zone == "Dump"
        assert zone.color == "orange"

    def test_1m_hard_limit(self):
        """1M model, 420k used → X (dark_red). New range: 400k–450k."""
        zone = get_context_zone(420_000, 1_000_000)
        assert zone.zone == "ExDump"
        assert zone.color == "dark_red"

    def test_1m_dead_zone(self):
        """1M model, 460k used → Z (gray). New threshold: >= 450k."""
        zone = get_context_zone(460_000, 1_000_000)
        assert zone.zone == "Dead"
        assert zone.color == "gray"

    # --- 1M boundary tests ---

    def test_1m_p_c_boundary(self):
        """Boundary: exactly 150k → C (not P)."""
        zone = get_context_zone(ZONE_1M_P_MAX, 1_000_000)
        assert zone.zone == "Code"
        zone_below = get_context_zone(ZONE_1M_P_MAX - 1, 1_000_000)
        assert zone_below.zone == "Plan"

    def test_1m_c_d_boundary(self):
        """Boundary: exactly 250k → D (not C)."""
        zone = get_context_zone(ZONE_1M_C_MAX, 1_000_000)
        assert zone.zone == "Dump"
        zone_below = get_context_zone(ZONE_1M_C_MAX - 1, 1_000_000)
        assert zone_below.zone == "Code"

    def test_1m_d_x_boundary(self):
        """Boundary: exactly 400k → X."""
        zone = get_context_zone(ZONE_1M_D_MAX, 1_000_000)
        assert zone.zone == "ExDump"
        zone_below = get_context_zone(ZONE_1M_D_MAX - 1, 1_000_000)
        assert zone_below.zone == "Dump"

    def test_1m_x_z_boundary(self):
        """Boundary: exactly 450k → Z (past X). X is 400k–450k range."""
        zone = get_context_zone(ZONE_1M_X_MAX, 1_000_000)
        assert zone.zone == "Dead"
        zone_below = get_context_zone(ZONE_1M_X_MAX - 1, 1_000_000)
        assert zone_below.zone == "ExDump"
        # A token count just past D boundary is within X range
        zone_just_past_d = get_context_zone(ZONE_1M_D_MAX + 1, 1_000_000)
        assert zone_just_past_d.zone == "ExDump"

    # --- Standard model tests (< 500k context) ---

    def test_std_200k_planning_zone(self):
        """200k model, 20k used → P (green). dump_zone=80k, warn_start=50k."""
        zone = get_context_zone(20_000, 200_000)
        assert zone.zone == "Plan"
        assert zone.color == "green"

    def test_std_200k_code_only_zone(self):
        """200k model, 60k used → C (yellow). Between 50k and 80k."""
        zone = get_context_zone(60_000, 200_000)
        assert zone.zone == "Code"
        assert zone.color == "yellow"

    def test_std_200k_dump_zone(self):
        """200k model, 100k used (50%) → D (orange). Between 40% and 70%."""
        zone = get_context_zone(100_000, 200_000)
        assert zone.zone == "Dump"
        assert zone.color == "orange"

    def test_std_200k_hard_limit(self):
        """200k model, 140k used (70%) → X (dark_red)."""
        zone = get_context_zone(140_000, 200_000)
        assert zone.zone == "ExDump"
        assert zone.color == "dark_red"

    def test_std_200k_dead_zone(self):
        """200k model, 150k used (75%) → Z (gray)."""
        zone = get_context_zone(150_000, 200_000)
        assert zone.zone == "Dead"
        assert zone.color == "gray"

    # --- Guard clause ---

    def test_zero_context_window(self):
        """context_window=0 → P (green)."""
        zone = get_context_zone(50_000, 0)
        assert zone.zone == "Plan"
        assert zone.color == "green"

    # --- Use cases from issue (updated for recalibrated 1M thresholds) ---

    def test_use_case_1(self):
        """UC1: 1M model, 100k used → P (< 150k threshold)."""
        assert get_context_zone(100_000, 1_000_000).zone == "Plan"

    def test_use_case_2(self):
        """UC2: 1M model, 200k used → C (150k–250k range)."""
        assert get_context_zone(200_000, 1_000_000).zone == "Code"

    def test_use_case_3(self):
        """UC3: 1M model, 300k used → D (250k–400k range)."""
        assert get_context_zone(300_000, 1_000_000).zone == "Dump"

    def test_use_case_4(self):
        """UC4: 1M model, 420k used → X (400k–450k range)."""
        assert get_context_zone(420_000, 1_000_000).zone == "ExDump"

    def test_use_case_5(self):
        """UC5: 1M model, 460k used → Z (>= 450k threshold)."""
        assert get_context_zone(460_000, 1_000_000).zone == "Dead"

    def test_use_case_6(self):
        """UC6: 200k model, 50% used → D."""
        assert get_context_zone(100_000, 200_000).zone == "Dump"

    def test_use_case_7(self):
        """UC7: 200k model, 75% used → Z."""
        assert get_context_zone(150_000, 200_000).zone == "Dead"

    # --- Large model threshold ---

    def test_500k_context_is_large_model(self):
        """500k context window is treated as 1M-class."""
        zone = get_context_zone(50_000, 500_000)
        assert zone.zone == "Plan"  # Uses 1M thresholds

    def test_499k_context_is_standard(self):
        """499k context window is treated as standard."""
        zone = get_context_zone(50_000, 499_000)
        assert zone.zone == "Plan"  # Uses standard thresholds


class TestConfigurableZoneThresholds:
    """Test configurable zone threshold overrides."""

    # --- 1M model overrides ---

    def test_1m_custom_plan_max(self):
        """Custom zone_1m_plan_max shifts P→C boundary."""
        # Default: 200k → Plan (< 150k P_MAX is for 150k, so 200k → Code with default).
        # With plan_max=210k → still Plan.
        zone = get_context_zone(200_000, 1_000_000, zone_1m_plan_max=210_000)
        assert zone.zone == "Plan"
        # Default: 200k → Code (150k–250k range)
        zone_default = get_context_zone(200_000, 1_000_000)
        assert zone_default.zone == "Code"

    def test_1m_custom_code_max(self):
        """Custom zone_1m_code_max shifts C→D boundary."""
        # 180k is within default C range (150k–250k). With code_max=160k → Dump.
        zone = get_context_zone(180_000, 1_000_000, zone_1m_code_max=160_000)
        assert zone.zone == "Dump"
        # Default would be Code
        zone_default = get_context_zone(180_000, 1_000_000)
        assert zone_default.zone == "Code"

    def test_1m_custom_dump_max(self):
        """Custom zone_1m_dump_max shifts D→X boundary."""
        # 350k is within default D range (250k–400k). With dump_max=300k → ExDump.
        zone = get_context_zone(350_000, 1_000_000, zone_1m_dump_max=300_000)
        assert zone.zone == "ExDump"
        # Default would be Dump
        zone_default = get_context_zone(350_000, 1_000_000)
        assert zone_default.zone == "Dump"

    def test_1m_custom_xdump_max(self):
        """Custom zone_1m_xdump_max shifts X→Z boundary."""
        # 430k is within default X range (400k–450k). With xdump_max=420k → Dead.
        zone = get_context_zone(430_000, 1_000_000, zone_1m_xdump_max=420_000)
        assert zone.zone == "Dead"
        # Default would be ExDump
        zone_default = get_context_zone(430_000, 1_000_000)
        assert zone_default.zone == "ExDump"

    # --- Standard model overrides ---

    def test_std_custom_dump_ratio(self):
        """Custom zone_std_dump_ratio shifts dump zone start."""
        # 200k model, 50% dump ratio → dump at 100k. With 0.30 → dump at 60k.
        zone = get_context_zone(70_000, 200_000, zone_std_dump_ratio=0.30)
        assert zone.zone == "Dump"
        # Default 0.40 → 80k dump zone, warn_start=50k, 70k → Code
        zone_default = get_context_zone(70_000, 200_000)
        assert zone_default.zone == "Code"

    def test_std_custom_hard_limit(self):
        """Custom zone_std_hard_limit shifts hard limit."""
        zone = get_context_zone(110_000, 200_000, zone_std_hard_limit=0.50)
        assert zone.zone == "ExDump"
        # Default 0.70 → 140k hard limit, 110k → Dump
        zone_default = get_context_zone(110_000, 200_000)
        assert zone_default.zone == "Dump"

    def test_std_custom_dead_ratio(self):
        """Custom zone_std_dead_ratio shifts dead zone start."""
        # Default: dead at 75% (150k). With 0.72 → dead at 144k.
        zone = get_context_zone(145_000, 200_000, zone_std_dead_ratio=0.72)
        assert zone.zone == "Dead"
        # Default: 145k is between hard_limit (140k) and dead (150k) → ExDump
        zone_default = get_context_zone(145_000, 200_000)
        assert zone_default.zone == "ExDump"

    # --- Large model threshold override ---

    def test_custom_large_model_threshold(self):
        """Custom large_model_threshold changes which model set is used."""
        # 400k context. Default threshold=500k → standard model.
        # With threshold=300k → treated as 1M model.
        zone = get_context_zone(100_000, 400_000, large_model_threshold=300_000)
        assert zone.zone == "Plan"  # Uses 1M thresholds (< 150k)
        zone2 = get_context_zone(200_000, 400_000, large_model_threshold=300_000)
        assert zone2.zone == "Code"  # 1M: 150k–250k

    # --- Zero override = use default ---

    def test_zero_override_uses_default(self):
        """Override of 0 falls back to module-level default."""
        # 200k is in the Code zone (150k–250k) with default thresholds.
        zone = get_context_zone(200_000, 1_000_000, zone_1m_plan_max=0)
        assert zone.zone == "Code"  # Same as default (150k boundary)


class TestZoneRecommendations:
    """Test that every ZoneInfo includes the correct recommendation string."""

    def test_plan_recommendation(self):
        """Plan zone has actionable recommendation."""
        zone = get_context_zone(100_000, 1_000_000)
        assert zone.zone == "Plan"
        assert zone.recommendation == _ZONE_RECOMMENDATIONS["Plan"]
        assert "plan" in zone.recommendation.lower()

    def test_code_recommendation(self):
        """Code zone recommendation advises against new tasks."""
        zone = get_context_zone(200_000, 1_000_000)
        assert zone.zone == "Code"
        assert zone.recommendation == _ZONE_RECOMMENDATIONS["Code"]
        assert "task" in zone.recommendation.lower()

    def test_dump_recommendation(self):
        """Dump zone recommendation mentions /compact or subagent."""
        zone = get_context_zone(300_000, 1_000_000)
        assert zone.zone == "Dump"
        assert zone.recommendation == _ZONE_RECOMMENDATIONS["Dump"]
        assert "compact" in zone.recommendation.lower()

    def test_exdump_recommendation(self):
        """ExDump zone recommendation urges immediate /compact."""
        zone = get_context_zone(420_000, 1_000_000)
        assert zone.zone == "ExDump"
        assert zone.recommendation == _ZONE_RECOMMENDATIONS["ExDump"]
        assert "compact" in zone.recommendation.lower()

    def test_dead_recommendation(self):
        """Dead zone recommendation urges /clear."""
        zone = get_context_zone(460_000, 1_000_000)
        assert zone.zone == "Dead"
        assert zone.recommendation == _ZONE_RECOMMENDATIONS["Dead"]
        assert "clear" in zone.recommendation.lower()

    def test_standard_model_plan_has_recommendation(self):
        """Standard-model Plan zone also has a recommendation."""
        zone = get_context_zone(20_000, 200_000)
        assert zone.zone == "Plan"
        assert zone.recommendation == _ZONE_RECOMMENDATIONS["Plan"]

    def test_standard_model_dead_has_recommendation(self):
        """Standard-model Dead zone also has a recommendation."""
        zone = get_context_zone(150_000, 200_000)
        assert zone.zone == "Dead"
        assert zone.recommendation == _ZONE_RECOMMENDATIONS["Dead"]

    def test_zero_context_has_recommendation(self):
        """Guard clause (zero context window) returns a recommendation."""
        zone = get_context_zone(0, 0)
        assert zone.recommendation == _ZONE_RECOMMENDATIONS["Plan"]

    def test_all_zones_have_non_empty_recommendations(self):
        """All five zones produce non-empty recommendation strings."""
        # Sample one token value per zone for 1M model
        test_cases = [
            (100_000, 1_000_000, "Plan"),
            (200_000, 1_000_000, "Code"),
            (300_000, 1_000_000, "Dump"),
            (420_000, 1_000_000, "ExDump"),
            (460_000, 1_000_000, "Dead"),
        ]
        for used, window, expected_zone in test_cases:
            zone = get_context_zone(used, window)
            assert zone.zone == expected_zone
            assert zone.recommendation, f"Zone {expected_zone} has empty recommendation"
            assert len(zone.recommendation) > 5, f"Zone {expected_zone} recommendation too short"

    def test_recommendations_match_zone_map(self):
        """Recommendation strings in ZoneInfo match the module-level map."""
        for used, window, expected_zone in [
            (100_000, 1_000_000, "Plan"),
            (200_000, 1_000_000, "Code"),
            (300_000, 1_000_000, "Dump"),
            (420_000, 1_000_000, "ExDump"),
            (460_000, 1_000_000, "Dead"),
        ]:
            zone = get_context_zone(used, window)
            assert zone.recommendation == _ZONE_RECOMMENDATIONS[expected_zone]


class TestZone1MRecalibration:
    """Verify recalibrated 1M thresholds match observed context rot boundary."""

    def test_280k_is_still_dump_not_dead(self):
        """280k tokens: old thresholds → Dead, new thresholds → Dump.
        The Claude Code team observes rot at 300-400k, so 280k should not be Dead.
        """
        zone = get_context_zone(280_000, 1_000_000)
        assert zone.zone == "Dump", (
            f"280k should be Dump zone, not {zone.zone}. "
            "Observed rot starts at 300-400k per Thariq's article."
        )

    def test_350k_is_still_dump_not_dead(self):
        """350k tokens: at the observed rot boundary, should be Dump (not Dead)."""
        zone = get_context_zone(350_000, 1_000_000)
        assert zone.zone == "Dump"

    def test_410k_enters_exdump(self):
        """410k: past the 400k rot onset threshold, should be ExDump."""
        zone = get_context_zone(410_000, 1_000_000)
        assert zone.zone == "ExDump"

    def test_460k_is_dead(self):
        """460k: well past rot onset, Dead zone."""
        zone = get_context_zone(460_000, 1_000_000)
        assert zone.zone == "Dead"

    def test_old_dead_threshold_now_dump(self):
        """275k was old Dead threshold. Under new thresholds it should be Dump."""
        zone = get_context_zone(275_000, 1_000_000)
        assert zone.zone == "Dump", (
            f"275k should be Dump with recalibrated thresholds, got {zone.zone}"
        )
