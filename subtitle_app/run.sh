#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
    python3 -m venv "$PROJECT_DIR/.venv"
fi
if ! "$VENV_PYTHON" -c 'import streamlit, docx, lxml, fastapi, uvicorn, openai' 2>/dev/null; then
    "$VENV_PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
fi
cd "$PROJECT_DIR"
printf '正在启动双语字幕工具，访问地址见下方输出。按 Ctrl+C 停止。\n'
exec "$VENV_PYTHON" -m streamlit run "$PROJECT_DIR/streamlit_app.py" --server.headless true "$@"
