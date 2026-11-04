#!/bin/zsh
set -e
PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$PROJECT_DIR"
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import PySide6.QtWidgets, paramiko, libarchive' >/dev/null 2>&1; then
    .venv/bin/python -m pip install -e .
fi
export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -m soovee_commander "$@"
