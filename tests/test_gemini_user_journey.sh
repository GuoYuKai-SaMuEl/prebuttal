#!/usr/bin/env bash
# User-journey simulation: a fresh machine with ONLY a Gemini free-tier key.
# Strips the local agent CLI from PATH so auto-detection sees api-gemini only,
# exactly like a user who installed prebuttal and set GEMINI_API_KEY.
#
# Usage: GEMINI_API_KEY=... bash tests/test_gemini_user_journey.sh
set -u

REPO=$(cd "$(dirname "$0")/.." && pwd)
CLEAN_PATH=$(echo "$PATH" | tr ':' '\n' | grep -v -i "SPB_Data" | paste -sd:)
PREBUTTAL="$REPO/.venv/Scripts/prebuttal.exe"
OUT="$REPO/demo-run/gemini-journey"
mkdir -p "$OUT"

step() { echo; echo "=== $1 ==="; }

step "1. backends — what a key-only user sees"
PATH="$CLEAN_PATH" "$PREBUTTAL" backends

step "2. dry-run on the demo paper (no calls)"
PATH="$CLEAN_PATH" "$PREBUTTAL" run examples/demo-paper --venue iclr --dry-run

step "3. FIRST REAL RUN — demo paper, bare command, auto-detection"
PATH="$CLEAN_PATH" "$PREBUTTAL" run examples/demo-paper --venue iclr \
  --out "$OUT/demo-report.md" --json "$OUT/demo-report.json" --share

step "4. Mamba (ICLR 2024, arXiv 2312.00752) — famous-paper demo"
PATH="$CLEAN_PATH" "$PREBUTTAL" run https://arxiv.org/abs/2312.00752 --venue iclr \
  --out "$OUT/mamba-report.md" --json "$OUT/mamba-report.json" --share

step "5. DPO (NeurIPS 2023, arXiv 2305.18290) — famous-paper demo"
PATH="$CLEAN_PATH" "$PREBUTTAL" run https://arxiv.org/abs/2305.18290 --venue neurips \
  --out "$OUT/dpo-report.md" --json "$OUT/dpo-report.json" --share

step "Done — reports in $OUT"
