# HarnessAI Demo

A Flask/Coolify RAG demo using the same application pattern as the Pike Policy Desk.

The app serves a simple question-answering interface backed by Markdown files in `kb/harness_ai/policies` and a SQLite FTS index built at startup.

## Environment

```env
OPENROUTER_API_KEY=sk-or-your-key
BASE_URL=https://openrouter.ai/api/v1
CLASSIFIER_MODEL=google/gemma-3-27b-it
ANSWER_MODEL=google/gemma-3-27b-it
KB_DIR=kb/harness_ai
UNIT=chunks
TOP_K=5
PORT=5000
```

## Local run

```bash
pip install -r requirements.txt
python app.py
```

## Coolify

Deploy with the Dockerfile. The container exposes port 5000 and includes a `/health` endpoint.
