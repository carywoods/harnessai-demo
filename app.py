"""
Flask web server for the HarnessAI RAG demo.

This app uses the same deployment pattern as the Pike Policy Desk:
- Flask UI
- SQLite FTS retrieval over Markdown-derived chunks
- OpenAI-compatible model endpoint
- Coolify Docker deployment
"""

from flask import Flask, request, jsonify, render_template
import os
from pathlib import Path
from datetime import datetime

from policy_rag import (
    normalize_search_query,
    likely_language_from_text,
    model_detect_and_translate_query,
    build_context_blocks,
    build_policy_answer_prompt,
    call_openai_compatible_model,
    save_run
)

app = Flask(__name__)

KB_DIR = Path(os.environ.get("KB_DIR", "kb/harness_ai"))
BASE_URL = os.environ.get("BASE_URL", "http://192.168.1.11:11434/v1")
UNIT = os.environ.get("UNIT", "chunks")
TOP_K = int(os.environ.get("TOP_K", 5))

LEGACY_DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gpt-oss:20b")
CLASSIFIER_MODEL = os.environ.get("CLASSIFIER_MODEL", LEGACY_DEFAULT_MODEL)
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", LEGACY_DEFAULT_MODEL)
DEFAULT_MODEL = ANSWER_MODEL

@app.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'service': 'harnessai-rag-demo',
        'kb_dir': str(KB_DIR),
        'unit': UNIT,
        'classifier_model': CLASSIFIER_MODEL,
        'answer_model': ANSWER_MODEL
    })

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
def search():
    data = request.json
    query = data.get('query', '')
    top_k = data.get('top_k', TOP_K)
    unit = data.get('unit', UNIT)

    if not query:
        return jsonify({'error': 'Query is required'}), 400

    try:
        context_blocks = build_context_blocks(
            kb_dir=KB_DIR,
            query=query,
            top_k=top_k,
            max_chars=2200,
            unit=unit
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({
        'query': query,
        'normalized_query': normalize_search_query(query),
        'results': context_blocks
    })

@app.route('/api/answer', methods=['POST'])
def answer():
    data = request.json
    query = data.get('query', '')
    language = data.get('language', 'auto')
    no_model_language = data.get('no_model_language', False)
    answer_model = data.get('model', ANSWER_MODEL)
    classifier_model = data.get('classifier_model', CLASSIFIER_MODEL)
    base_url = data.get('base_url', BASE_URL)
    top_k = data.get('top_k', TOP_K)
    unit = data.get('unit', UNIT)
    temperature = data.get('temperature', 0.2)
    timeout = data.get('timeout', 180)

    if not query:
        return jsonify({'error': 'Query is required'}), 400

    original_query = query
    detected_language = language
    retrieval_query = original_query
    translation_info = None

    if language == "auto":
        if no_model_language:
            detected_language = likely_language_from_text(original_query)
            retrieval_query = original_query
            translation_info = {
                "detected_language": detected_language,
                "english_query": retrieval_query,
                "confidence": "heuristic",
            }
        else:
            try:
                translation_info = model_detect_and_translate_query(
                    query=original_query,
                    base_url=base_url,
                    model=classifier_model,
                    timeout=timeout,
                    temperature=0.0,
                )
                detected_language = translation_info.get("detected_language", "Unknown")
                retrieval_query = translation_info.get("english_query", original_query)
            except Exception:
                detected_language = likely_language_from_text(original_query)
                retrieval_query = original_query

    elif language.lower() in {"english", "en"}:
        detected_language = "English"
        retrieval_query = original_query

    else:
        detected_language = language
        if not no_model_language:
            try:
                translation_info = model_detect_and_translate_query(
                    query=original_query,
                    base_url=base_url,
                    model=classifier_model,
                    timeout=timeout,
                    temperature=0.0,
                )
                retrieval_query = translation_info.get("english_query", original_query)
            except Exception:
                retrieval_query = original_query

    if detected_language == "Unknown":
        detected_language = "English"

    try:
        context_blocks = build_context_blocks(
            kb_dir=KB_DIR,
            query=retrieval_query,
            top_k=top_k,
            max_chars=2200,
            unit=unit,
        )
    except Exception as e:
        return jsonify({'error': f"Retrieval failed: {e}"}), 500

    if not context_blocks:
        return jsonify({
            'error': 'No matching HarnessAI context found.',
            'retrieval_query': retrieval_query,
            'detected_language': detected_language
        }), 404

    messages = build_policy_answer_prompt(
        original_question=original_query,
        retrieval_question=retrieval_query,
        context_blocks=context_blocks,
        output_language=detected_language,
    )

    try:
        answer_text = call_openai_compatible_model(
            base_url=base_url,
            model=answer_model,
            messages=messages,
            temperature=temperature,
            timeout=timeout,
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    try:
        save_run(
            kb_dir=KB_DIR,
            prefix="answer_web",
            payload={
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "original_query": original_query,
                "detected_language": detected_language,
                "retrieval_query": retrieval_query,
                "normalized_retrieval_query": normalize_search_query(retrieval_query),
                "translation_info": translation_info,
                "classifier_model": classifier_model,
                "answer_model": answer_model,
                "base_url": base_url,
                "unit": unit,
                "top_k": top_k,
                "temperature": temperature,
                "context": context_blocks,
                "answer": answer_text,
            },
        )
    except Exception as e:
        print(f"Error saving run: {e}")

    return jsonify({
        'answer': answer_text,
        'context': context_blocks,
        'detected_language': detected_language,
        'retrieval_query': retrieval_query,
        'classifier_model': classifier_model,
        'answer_model': answer_model
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
