#!/bin/sh
set -eu

KB_DIR="${KB_DIR:-kb/harness_ai}"
UNIT="${UNIT:-chunks}"
INDEX_PATH="$KB_DIR/index/policy_fts_${UNIT}.db"

if [ ! -f "$INDEX_PATH" ]; then
    echo "RAG index not found at $INDEX_PATH; building index for $KB_DIR using unit=$UNIT"
    python policy_rag.py chunk --kb "$KB_DIR" --clean
    python policy_rag.py index --kb "$KB_DIR" --unit "$UNIT"
fi

exec gunicorn --bind "0.0.0.0:${PORT:-5000}" --workers 2 --timeout 240 app:app
