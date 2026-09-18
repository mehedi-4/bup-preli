#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ -f "$DIR/.venv/bin/activate" ]; then
    source "$DIR/.venv/bin/activate"
fi

echo "Starting GridWise LLM Service on http://0.0.0.0:8000 ..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
