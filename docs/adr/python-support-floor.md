# ADR 0001: Python support floor

- **Status:** Accepted (2026-08-23)
- **Decides:** Modernization plan Task 3.1 (#133) — the minimum supported Python version
- **Implemented by:** Task 3.2 (#134)
- **Supersedes:** none (first written floor decision; `requires-python = ">=3.9"` predates this ADR)

## Context

The project declares `requires-python = ">=3.9"` (`pyproject.toml:11`) but nothing
records _why_, and every artifact that encodes the floor has drifted:

- **Python 3.9 is EOL.** It ended security support on **2025-10-31**
  ([Python devguide release schedule](https://devguide.python.org/versions/)).
  The declared floor is therefore an end-of-life runtime that receives no
  security fixes.
- **Classifiers stop below the dev runtime.** `pyproject.toml:33-37` classifies
  3.9–3.13 while the development venv runs Python 3.14.7 (finding F-DEP-010).
- **CI never tests 3.9's own era consistently** — the test matrix
  (`.github/workflows/ci.yml:53`) covers 3.9–3.12, so neither 3.13 nor 3.14 is a
  tested leg despite both being released.
- **The floor forces an interim dependency cap.** pre-commit ≥ 4.4 requires
  Python ≥ 3.10, so `requirements-dev.txt:15` carries `pre-commit>=3.6.0,<4.4`
  and `requirements-dev.constraints.txt:53` pins 4.3.0 (finding F-DEP-002,
  patched interims-only in Task 1.2, PR #163).
- **12 security advisories are silenced because of the floor.** Every fix
  version blocked in `scripts/pip-audit-locked.sh` (the `--ignore-vuln PYSEC-*`
  flags, ticket #161) requires Python ≥ 3.10 directly or conflicts with the
  3.9-floor pins (`requirements-dev.constraints.txt:9-16`). These are pip-audit
  findings from Task 1.1's locked-environment audit.
- **User impact is negligible.** PyPI download stats for `context-stats`
  (~1.2k downloads/month as of 2026-08-23) show no evidence base justifying an
  EOL runtime.

## Decision

**Require Python >= 3.10.**

`requires-python` becomes `">=3.10"`, dropping 3.9 from all supported-version
artifacts. This is the minimal step that unblocks everything the current floor
holds back:

| Unblocked by >=3.10                                            | Artifact                                   |
| -------------------------------------------------------------- | ------------------------------------------ |
| pre-commit 4.x installs without a cap                          | `requirements-dev.txt`                     |
| 12 silenced PYSEC advisories become actionable                 | `scripts/pip-audit-locked.sh`, constraints |
| Constraint regeneration moves to a supported resolution target | docs procedure                             |
| Classifier set can name the dev runtime again (3.14)           | `pyproject.toml`                           |

### Why not stay on 3.9

An unsupported runtime cannot be a security floor: pip-audit exceptions against
it have no fix path, and CI legs on 3.9 exercise an interpreter nobody can ship
fixes for.

### Why not >=3.11 (or higher) now

3.11 would buy longer runway (EOL 2027-10-31 vs 2026-10-31 for 3.10) but is a
bigger compatibility step than the plan task authorizes, and every in-repo
reference point already anticipates exactly 3.10 ("the minimum supported Python
rises to 3.10+", `docs/DEVELOPMENT.md:88`). The incremental benefit over 3.10
does not justify skipping ahead mid-phase.

### Known trade-off: 3.10's own horizon

Python 3.10 enters its final months — full support ends 2026-10-01 and EOL is
**2026-10-31** ([devguide](https://devguide.python.org/versions/)). Raising the
floor to 3.10 is accepted as a deliberate intermediate step, not a resting
point. **Revisit this ADR when 3.10 reaches EOL (or at Phase 5 of the
modernization plan, whichever comes first)** with >=3.11 as the expected next
floor.

## Artifacts Task 3.2 (#134) must update

Verified against the working tree at `5678d52` (2026-08-23). Line numbers are
current as of this writing.

### Code / packaging

| Artifact            | Change                                                                |
| ------------------- | --------------------------------------------------------------------- |
| `pyproject.toml:11` | `requires-python = ">=3.9"` → `">=3.10"`                              |
| `pyproject.toml:33` | Drop the `Programming Language :: Python :: 3.9` classifier           |
| `pyproject.toml:37` | Add the `:: 3.14` classifier after `:: 3.13` (closes F-DEP-010 drift) |
| `pyproject.toml:75` | `[tool.ruff] target-version = "py39"` → `"py310"`                     |
| `pyproject.toml:96` | `[tool.mypy] python_version = "3.9"` → `"3.10"`                       |

### CI

| Artifact                       | Change                                                                                    |
| ------------------------------ | ----------------------------------------------------------------------------------------- |
| `.github/workflows/ci.yml:53`  | `python-test` matrix: drop `'3.9'`; add `'3.13'` (and `'3.14'` if setup-python offers it) |
| `.github/workflows/ci.yml:145` | `e2e-install-pip` matrix: same drop/add as above                                          |

(`python-lint`, `integration-test`, `e2e-exec`, `pre-commit`, and
`dependency-scan` jobs pin `3.11` — unaffected.)

### Dev dependencies & security exceptions

| Artifact                            | Change                                                                                                                                                                                                                                                |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `requirements-dev.txt:15`           | Remove the `<4.4` upper cap from `pre-commit>=3.6.0,<4.4`; delete the F-DEP-002 cap comment (:12-14)                                                                                                                                                  |
| `requirements-dev.constraints.txt`  | Regenerate at the **3.10 floor** per `docs/DEVELOPMENT.md` ("Regenerating the dev-dependency constraints file"); bump the `pre-commit==4.3.0` pin past 4.4 and delete its marker-free-pin comment (:47-52); rewrite the header comments (:4-5, :9-16) |
| `scripts/pip-audit-locked.sh:18-29` | Delete each `--ignore-vuln PYSEC-*` flag whose fix now installs (verify per-advisory during regeneration); update the header comment and close out #161 items                                                                                         |

### Documentation

| Artifact                                                                                                | Change                                                                                                         |
| ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `README.md:309`                                                                                         | "Python 3.9+" → "Python 3.10+"                                                                                 |
| `CONTRIBUTING.md:11`                                                                                    | "**Python 3.9+**" → "**Python 3.10+**"                                                                         |
| `docs/DEVELOPMENT.md:6`                                                                                 | Requirements list: "Python 3.9+" → "Python 3.10+"                                                              |
| `docs/DEVELOPMENT.md:70,:74`                                                                            | Constraints-regeneration text: resolve/verify at the 3.10 floor across the new matrix                          |
| `docs/DEVELOPMENT.md:72`                                                                                | Version-capped-floor-dependencies section (F-DEP-002): mark the pre-commit example resolved by this ADR / #134 |
| `docs/DEVELOPMENT.md:88`                                                                                | Exception policy: note the #161 advisories became actionable and were handled                                  |
| `docs/installation.md`, `docs/troubleshooting.md`, `docs/docs.html`, `docs/index.html`, `docs/llms.txt` | Update any remaining "3.9"/"Python 3.9+" mentions surfaced by `rg -n "3\.9"` during implementation             |

Not touched: `CHANGELOG.md:76` (historical release note), generated
`docs/changelog.html`.

## Consequences

- Users on Python 3.9 can no longer install new releases; pip resolves to the
  last 3.9-compatible version via `Requires-Python` metadata.
- All four CI matrix legs run currently supported interpreters again.
- The 12-silenced-advisory backlog (#161) becomes burnable work in #134.
- Tooling floors rise together (ruff `py310`, mypy `3.10`), enabling pyupgrade
  cleanups opportunistically — not in scope for #134.
- A follow-up floor decision (>=3.11) is scheduled before/around 2026-10-31;
  tracked via this ADR's Status line.

## References

- [Python devguide — status of Python versions](https://devguide.python.org/versions/)
- Issue #133 (this decision), epic tracker #109
- Issue #161 — silenced pip-audit advisories blocked by the 3.9 floor
- PR #163 / issue #120 — interim pre-commit <4.4 cap (Task 1.2, F-DEP-002)
- Findings F-DEP-002, F-DEP-010 (modernization audit; task text preserved in #133)
- [PyPI downloads for context-stats](https://pypistats.org/packages/context-stats) (~1.2k/month, Aug 2026)
