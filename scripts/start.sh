#!/usr/bin/env bash
# 从源码目录直接启动 docmask（不安装）。
# 用法：
#   ./scripts/start.sh --help
#   ./scripts/start.sh run ./docs -o ./redacted_output
#   ./scripts/start.sh ui

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m docmask "$@"
