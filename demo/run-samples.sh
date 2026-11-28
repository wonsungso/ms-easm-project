#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n "${EASM_AGENT_PYTHON:-}" ]]; then
  python_command="$EASM_AGENT_PYTHON"
elif [[ -x ".venv/Scripts/python.exe" ]]; then
  python_command=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  python_command=".venv/bin/python"
else
  python_command="python"
fi
"$python_command" -m demo.samples --apply --collect "$@"
