#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$root"

if [[ -n "${EASM_AGENT_PYTHON:-}" ]]; then
  python_command="$EASM_AGENT_PYTHON"
elif [[ -x .venv/bin/python ]]; then
  python_command="$root/.venv/bin/python"
elif [[ -x .venv/Scripts/python.exe ]]; then
  python_command="$root/.venv/Scripts/python.exe"
else
  python_command=python3
fi

case "${1:-}" in
  install)
    shift
    exec "$python_command" -m pip install -e '.[connected-demo]' "$@"
    ;;
  aws|aws-classic|snowflake)
    exec "$python_command" -m demo.deploy_connected_demo "$@"
    ;;
  collect)
    shift
    exec "$python_command" -m easm_agent.cli collect --agent365-registry "$@"
    ;;
  verify)
    shift
    exec "$python_command" -m demo.verify_connected_catalog "$@"
    ;;
  *)
    printf '%s\n' '사용법: bash demo/run-connected.sh {install|aws|aws-classic|snowflake|collect|verify} [옵션]' >&2
    case "${1:-}" in
      -h|--help) exit 0 ;;
      *) exit 2 ;;
    esac
    ;;
esac
