#!/usr/bin/env bash
# Explicitly paid demonstration on the supplied 500-review checkpoint.
# Run only after configuration is frozen; preserves all output and call evidence.
set -euo pipefail
if [[ "${1:-}" != "--execute-paid" ]]; then
  echo "No calls made. Pass --execute-paid to run the bounded recovery demonstration."
  exit 2
fi
run_dir="${2:-runs/recovery}"
cache_file="${3:-data/recovery-cache.sqlite3}"
if [[ -e "$run_dir" || -e "$cache_file" ]]; then
  echo "Use fresh run/cache paths so this demonstration cannot overwrite previous evidence."
  exit 2
fi
echo "Initial phase: deliberately stop after saving 50 completed original reviews."
spotify-pipeline run --execute-paid \
  --input data/source/checkpoint_500.csv --out "$run_dir" --db "$cache_file" \
  --budget 1.50 --workers 1 --phase initial --stop-after 50
echo "Process exited after saved progress. Resume with the same input and configuration."
spotify-pipeline run --execute-paid \
  --input data/source/checkpoint_500.csv --out "$run_dir" --db "$cache_file" \
  --budget 1.50 --workers 1 --phase resume --verify-count 10
echo "Inspect checkpoints and resumed call IDs; completed IDs must not be billed again."
