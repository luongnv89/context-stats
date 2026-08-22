#!/usr/bin/env bash
# Audit the locked dev environment for known vulnerabilities (F-DEP-008).
#
# Single source of truth for the audit command: run by CI (.github/workflows/
# ci.yml and security-audit.yml) and safe to run locally from an activated
# venv. Exits non-zero on any known advisory NOT listed below, so a new
# High/Critical advisory fails the gate immediately.
#
# Every --ignore-vuln entry MUST reference a filed ticket (#161). All current
# entries have fix versions requiring Python >= 3.10 (directly or via matrix
# conflicts with the Python 3.9 floor pins) and MUST be revisited when the
# minimum supported Python rises to 3.10+.
set -euo pipefail

cd "$(dirname "$0")/.."

exec pip-audit -r requirements-dev.constraints.txt --progress-spinner off \
	--ignore-vuln PYSEC-2026-3625 \
	--ignore-vuln PYSEC-2026-1375 \
	--ignore-vuln PYSEC-2026-1374 \
	--ignore-vuln PYSEC-2026-196 \
	--ignore-vuln PYSEC-2026-2875 \
	--ignore-vuln PYSEC-2026-2876 \
	--ignore-vuln PYSEC-2026-3721 \
	--ignore-vuln PYSEC-2026-1845 \
	--ignore-vuln PYSEC-2026-2275 \
	--ignore-vuln PYSEC-2026-142 \
	--ignore-vuln PYSEC-2026-141 \
	--ignore-vuln PYSEC-2026-2009
