# Model Intelligence (MI) Metric

> Calibrated from **MRCR v2 8-needle** long context retrieval benchmark data

## Overview

Model Intelligence (MI) estimates how well an LLM will perform at the current context fill level. Research shows that retrieval and reasoning quality degrades monotonically as context fills — but at different rates per model family. MI provides a continuous [0, 1] score that tells users when to start a new session.

## Benchmark Evidence

The MRCR v2 8-needle benchmark measures retrieval accuracy across context lengths:

| Model | 256K accuracy | 1M accuracy | Relative drop |
|-------|--------------|-------------|---------------|
| **Opus 4.6** | 91.9% | 78.3% | ~14.8% |
| **Sonnet 4.6** | 90.6% | 65.1% | ~28.1% |
| **Haiku 4.5** | (estimated) | (estimated) | ~57% |

Key insight: Even the best model loses accuracy with context length, but the rate varies dramatically per model family.

## Formula

```
MI(u) = max(0, 1 - u^β)
```

Where:
- `u = current_used_tokens / context_window_size` (utilization ratio, 0 to 1)
- `β` (beta) = curve shape, controls where degradation steepens (model-specific)
- All models drop from 1.0 to 0.0 — beta controls *when* the drop happens

### Per-Model Profiles

Calibrated from MRCR v2 benchmark data:

| Model Family | β (beta) | MI at 25% | MI at 50% | MI at 75% | MI at 100% |
|-------------|----------|-----------|-----------|-----------|------------|
| **opus** | 1.8 | 0.918 | 0.713 | 0.404 | 0.000 |
| **sonnet** | 1.5 | 0.875 | 0.646 | 0.350 | 0.000 |
| **haiku** | 1.2 | 0.811 | 0.565 | 0.292 | 0.000 |
| **default** | 1.5 | 0.875 | 0.646 | 0.350 | 0.000 |

**Model matching**: The `model_id` string is checked for "opus", "sonnet", or "haiku" (case-insensitive). Unknown models fall back to the default (sonnet) profile.

### Why β?

- **β > 1** creates convex decay — quality stays high initially, then drops faster as context fills
- **Higher β** = quality retained longer (Opus has β=1.8, Haiku has β=1.2)
- All models reach MI=0.0 at full context, but Opus stays high longer before dropping

### Example Calculations

**Opus at 50% context (β=1.8):**

```text
MI = max(0, 1 - 0.50^1.8) = 1 - 0.287 = 0.713
```

**Sonnet at 50% context (β=1.5):**

```text
MI = max(0, 1 - 0.50^1.5) = 1 - 0.354 = 0.646
```

**Haiku at 50% context (β=1.2):**

```text
MI = max(0, 1 - 0.50^1.2) = 1 - 0.435 = 0.565
```

## Color Thresholds

| MI Range | Color | Label | Interpretation |
|----------|-------|-------|----------------|
| > 0.70 | Green | Operating well | Minimal degradation |
| 0.40–0.70 | Yellow | Degrading | Consider wrapping up |
| < 0.40 | Red | Significant | Start a new session |

**Implication**: Opus enters yellow around 60% utilization, sonnet around 50%, haiku around 45%. MI values are displayed with 3 decimal places (e.g., `MI:0.995`) for precision at low utilization.

## Zone Indicators (P/C/D/X/Z)

Zone indicators provide an at-a-glance signal for session state, displayed alongside the MI score. The zones use model-size-aware thresholds — 1M context models get absolute token thresholds, while standard models use utilization ratios.

### Five States

| Zone | Color | Meaning | 1M model (>= 500k ctx) | Standard model (< 500k ctx) |
|------|-------|---------|------------------------|----------------------------|
| **P** | Green | Planning mode — safe to plan and code | < 70k tokens used | < (40% - 30k tokens) |
| **C** | Yellow | Code-only — avoid starting new plans | 70k–100k tokens | (40% - 30k) to 40% |
| **D** | Orange | Dump zone — quality declining, finish up | 100k–250k tokens | 40%–70% utilization |
| **X** | Dark red | Hard limit — start a new session | 250k–275k tokens | 70%–75% utilization |
| **Z** | Light gray | Dead zone — nothing productive here | >= 275k tokens | >= 75% utilization |

### Design Rationale

The dump zone is **graduated, not a cliff**. When users enter **D** (orange), model quality is declining but they can still finish up current work. **X** (dark red) is the clear signal to start a new session. **Z** (light gray) communicates "past the point of usefulness" without alarm.

The 100k dump zone limit for 1M models comes from [Matt Pocock (@mattpocockuk)](https://x.com/mattpocockuk). The 40% threshold for standard models was validated by Dex.

### Why Model-Size-Aware Thresholds?

A single 40% threshold doesn't work for 1M context models — 40% of 1M is 400k tokens, but empirical evidence shows quality degrades much earlier. The absolute token thresholds (70k/100k/250k) reflect real-world dump zone behavior observed in 1M context sessions.

### Example Statusline Output

```
Claude Opus 4.6 | myproject | main | 850,000 (85.0%) | MI:0.713 P
```

The zone letter appears after the MI score, colored according to the zone.

## Design Rationale

### Why not CPS + ES + PS?

The previous MI formula was `MI = 0.60×CPS + 0.25×ES + 0.15×PS`, which produced zig-zag charts because:

1. **ES (cache efficiency)** fluctuated per turn based on API caching behavior
2. **PS (productivity)** swung wildly between planning responses (low) and code generation (high)
3. At low utilization, CPS barely moved (≈0.99), so ES/PS noise dominated the visual

These components measured **model activity**, not **model intelligence**. The new formula uses only context utilization — the one signal that the benchmark proves correlates with quality degradation.

### Key Properties

- **Guaranteed monotonic decrease** — MI is a pure function of utilization
- **No per-turn noise** — no zig-zag in charts
- **Model-aware** — Opus degrades gently, Haiku more aggressively
- **No previous entry needed** — reduces file I/O when delta display is disabled
- **Benchmark-grounded** — calibrated from measured retrieval accuracy

## Configuration

```ini
# Model Intelligence (MI) score display
show_mi=false

# Override model-specific beta with a custom value
# Set to 0 (default) to use the model's built-in profile
# mi_curve_beta=0
```

The `mi_curve_beta` config overrides the model profile's beta (but not alpha). Set it to a positive value to use a custom curve shape for all models.

## Guard Clause

If `context_window_size == 0` (malformed data), MI returns 1.0 with utilization 0.0.

## Cross-Implementation Sync Points

The MI formula and zone logic are implemented in 4 languages and must be kept in sync:

| Logic | Package (`src/`) | Standalone Python | Node.js | Bash |
|-------|-----------------|-------------------|---------|------|
| MODEL_PROFILES | `intelligence.py` | `statusline.py` | `statusline.js` | `statusline-full.sh` |
| get_model_profile | `intelligence.py` | `statusline.py` | `statusline.js` | inline in awk |
| MI formula | `calculate_context_pressure()` | `compute_mi()` | `computeMI()` | `compute_mi()` |
| Color thresholds | `get_mi_color()` | `get_mi_color()` | `getMIColor()` | `get_mi_color()` |
| Zone indicator | `get_context_zone()` | `get_context_zone()` | `getContextZone()` | (not yet) |
| Zone constants | `ZONE_1M_*`, `ZONE_STD_*` | `ZONE_1M_*`, `ZONE_STD_*` | `ZONE_1M_*`, `ZONE_STD_*` | (not yet) |
