## v1.19.0 — 2026-04-16

### Features

- **Compaction event detection** — Detect `/compact` events (>50% context drop) and annotate graphs with `▼` markers so users can see exactly when compaction occurred (#62, #65)
- **MI quality flagging at compaction** — Flag the MI score at compaction time to warn users of potentially lossy summaries (#65)
- **Actionable zone recommendations** — Zone indicators now include brief recommendations so users know what action to take in each zone (#63)
- **Landing page** — Static GitHub Pages landing page highlighting the cache keep-warm feature (#66)

### Fixes

- **1M zone thresholds recalibrated** — Updated `ZONE_1M_*` constants to match observed context degradation patterns, reducing false-alarm window by 25-120k tokens (#64)
- **Landing page timeline arrows** — Made cache-warm timeline arrows visible
- **Zone percentage thresholds** — Corrected zone percentages in landing page to match code

### Documentation

- Added anonymized 30-day example report
- Updated README messaging to three-level analytics framework
- Fresh logo for ContextStats rebrand

**Full Changelog**: https://github.com/luongnv89/context-stats/compare/v1.18.0...v1.19.0
