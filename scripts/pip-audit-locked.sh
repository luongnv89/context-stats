#!/usr/bin/env bash
# Audit the locked dev environment for known vulnerabilities (F-DEP-008).
#
# Single source of truth for the audit command: run by CI (.github/workflows/
# ci.yml and security-audit.yml) and safe to run locally from an activated
# venv. Exits non-zero on any known advisory NOT listed below, so a new
# High/Critical advisory fails the gate immediately.
#
# The 12 ticketed exceptions from #161 (msgpack, filelock, pip, pytest,
# requests, urllib3 and virtualenv) were cleared when the minimum supported
# Python rose to 3.10 (ADR 0001, #133/#134): their fix versions now install
# across the whole CI matrix, so no --ignore-vuln flags remain. New advisories
# may only be silenced with a filed ticket — see docs/DEVELOPMENT.md
# ("Security auditing").
set -euo pipefail

cd "$(dirname "$0")/.."

exec pip-audit -r requirements-dev.constraints.txt --progress-spinner off
