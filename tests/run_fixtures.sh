#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python main.py --pdf_dir "$ROOT/tests/fixtures" --out_csv "$ROOT/tests/out.csv" --dry_run "$@"
