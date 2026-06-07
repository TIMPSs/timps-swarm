#!/usr/bin/env bash
# IR containment script — generated 20260606_062820
# Classification: unknown  Severity: sev3
# *** REVIEW EVERY LINE BEFORE EXECUTING — DRY-RUN BY DEFAULT ***
set -euo pipefail
DRY_RUN=${DRY_RUN:-1}
run() { if [ "$DRY_RUN" = "1" ]; then echo "[dry-run] $*"; else eval "$@"; fi; }
