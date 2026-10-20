#!/usr/bin/env bash
# Record this wrapper with tools/record_command.py after configuration is frozen.
# The helper interrupts only the process it starts, then resumes the same run.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$script_dir/.."
exec "${PYTHON_BIN:-python3}" "$script_dir/recovery_demo.py" "$@"
