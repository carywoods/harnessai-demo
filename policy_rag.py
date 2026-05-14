#!/usr/bin/env python3
"""
policy_rag.py

Generic Markdown-backed RAG utility for HarnessAI-style demo apps.

The knowledge base format is:

  kb/<name>/policies/*.md

Each Markdown file may include YAML-like frontmatter with:
  policy_number
  displayed_number
  title
  source_url
  source_file

The script can chunk those Markdown files, build a SQLite FTS5 index, search it,
and support the Flask app's model-based language handling and answer generation.
"""

import argparse
import json
import os
import re
import sqlite3
import textwrap
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------


def clean_text(value: str) -> str:
    if value is None:
        return ""

    replacements = [
        ("\u2019", "'"),
        ("\u2018", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u00a0", " "),
        ("\u2013", "-"),
        ("\u2014", "-"),
        ("\ufffd", ""),
        ("\x92", "'"),
        ("\x93", '"'),
        ("\x94", '"'),
    ]

    for old, new in replacements:
        value = value.replace(old, new)

    return value


def slugify(value: str, max_len: int = 90) -> str:
    value = clean_text(value).lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")[:max_len] or "untitled"


def save_run(kb_dir: Path, prefix: str, payload: dict):
    runs_dir = kb_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_path = runs_dir / f"{prefix}-{timestamp}.json"
    run_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return run_path


def extract_frontmatter_and_body(text: str):
    text = clean_text(text)

    if not text.startswith("---"):
        return {}, text.strip()

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text.strip()

    raw_meta = parts[1].strip()
    body = parts[2].strip()
    meta = {}

    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")

    return meta, body


# ---------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------


def split_markdown_into_chunks(meta: dict, body: str, max_chars: int = 2200, overlap: int = 250):
    body = clean_text(body).strip()
    if not body:
        return []

    chunks = []
    title = meta.get("title", "")
    policy_number = meta.get("policy_number", "")

    sections = []
    current_title = title
    current_lines = []

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
                current_lines = []
            current_title = stripped.lstrip("#").strip() or title
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))

    if not sections:
        sections = [(title, body)]

    for section_title, section_text in sections:
        section_text = section_text.strip()
        if not section_text:
            continue

        if len(section_text) <= max_chars:
            chunks.append({
                "section_number": policy_number,
                "section_title": section_title or title,
                "text": section_text,
            })
            continue

        start = 0
        part = 1
        while start < len(section_text):
            end = min(start + max_chars, len(section_text))
            window = section_text[start:end].strip()

            if end < len(section_text):
                sentence_end = max(window.rfind(". "), window.rfind("\n\n"))
                if sentence_end > max_chars * 0.55:
                    window = window[:sentence_end + 1].strip()
                    end = start + sentence_end + 1

            chunks.append({
                "section_number": policy_number,
                "section_title": f"{section_title or title} - Part {part}",
                "text": window,
            })

            part += 1
            next_start = end - overlap
            if next_start <= start:
                next_start = end
            start = next_start

    return chunks


# Backward-compatible name used by the Pike app pattern.
def split_policy_into_chunks(policy_meta: dict, body: str, max_chars: int = 2200, overlap: int = 250):
    return split_markdown_into_chunks(policy_meta, body, max_chars=max_chars, overlap=overlap)


# ---------------------------------------------------------------------
# Search normalization and language support
# ---------------------------------------------------------------------


def normalize_search_query(query: str) -> str:
    query = clean_text(query).lower()
    query = re.sub(r"[^a-z0-9.\s]+", " ", query)

    stopwords = {
        "what", "is", "are", "was", "were", "be", "been", "being",
        "the", "a", "an", "of", "on", "for", "to", "and", "or",
        "in", "at", "by", "with", "from", "as", "that", "this",
        "these", "those", "does", "do", "did", "about", "tell",
        "me", "explain", "policy", "policies", "company", "service",
        "services", "system", "systems", "ai", "harnessai", "harness",
    }

    terms = [term for term in query.split() if term not in stopwords and len(term) > 1]
    return " ".join(terms)


def likely_language_from_text(text: str) -> str:
    lowered = clean_text(text).lower()

    spanish_markers = ["¿", "¡", "puede", "qué", "como", "cómo", "hablar", "escuela", "política", "servicio"]
    french_markers = ["est-ce", "peut", "quoi", "comment", "parler", "école", "politique", "service"]
    creole_markers = ["èske", "kapab", "kisa", "ki jan", "pale", "lekòl", "politik", "sèvis"]

    if any(marker in lowered for marker in spanish_markers):
        return "Spanish"
    if any(marker in lowered for marker in french_markers):
        return "French"
    if any(marker in lowered for marker in creole_markers):
        return "Haitian Creole"
    if re.fullmatch(r"[a-zA-Z0-9\s.,?!'\"():;-]+", text.strip()):
        return "English"
    return "Unknown"


# ---------------------------------------------------------------------
# OpenAI-compatible model calls
# ---------------------------------------------------------------------


def api_key_for_base_url(base_url: str) -> str:
    return (
        os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("MODEL_API_KEY")
        or "local-not-needed"
    )


def call_openai_compatible_model(
    base_url: str,
    model: str,
    messages: list,
    temperature: float = 0.2,
    timeout: int = 180,
):
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key_for_base_url(base_url)}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            result = json.loads(raw)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP error from model endpoint: {e.code}\n{error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach model endpoint: {e}") from e
    except TimeoutError as e:
        raise RuntimeError(f"Timed out waiting for model endpoint after {timeout} seconds.") from e

    try:
        return result["choices"][0]["message"]["content"]
    except KeyError as e:
        raise RuntimeError("Unexpected model response format:\n" + json.dumps(result, indent=2)) from e


def model_detect_and_translate_query(
    query: str,
    base_url: str,
    model: str,
    timeout: int,
    temperature: float = 0.0,
):
    system_prompt = """
You detect the language of a user question and translate it into English for knowledge-base retrieval.

Return only valid JSON with these exact keys:
detected_language
english_query
confidence

Supported detected_language values:
English
Spanish
French
Haitian Creole
Unknown

Do not answer the user's question.
Do not add commentary.
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Question:\n{query}"},
    ]

    raw = call_openai_compatible_model(
        base_url=base_url,
        model=model,
        messages=messages,
        temperature=temperature,
        timeout=timeout,
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {
                "detected_language": likely_language_from_text(query),
                "english_query": query,
                "confidence": "low",
                "raw": raw,
            }
        data = json.loads(match.group(0))

    detected = data.get("detected_language", likely_language_from_text(query))
    english_query = data.get("english_query", query)
    confidence = data.get("confidence", "unknown")

    if not str(english_query).strip():
        english_query = query

    return {
        "detected_language": detected,
        "english_query": english_query,
        "confidence": confidence,
        "raw": raw,
    }


# ---------------------------------------------------------------------
# Build commands
# ---------------------------------------------------------------------


def chunk_command(args):
    kb_dir = Path(args.kb)
    policies_dir = kb_dir / "policies"
    chunks_dir = kb_dir / "chunks"
    metadata_dir = kb_dir / "metadata"

    if not policies_dir.exists():
        raise SystemExit(f"Policy directory not found: {policies_dir}")

    policy_files = sorted(policies_dir.glob("*.md"))
    if not policy_files:
        raise SystemExit(f"No policy Markdown files found in: {policies_dir}")

    chunks_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    if args.clean:
        for old_file in chunks_dir.glob("*.json"):
            old_file.unlink()

    all_chunks = []
    chunk_count = 0

    for policy_path in policy_files:
        raw = policy_path.read_text(encoding="utf-8", errors="replace")
        meta, body = extract_frontmatter_and_body(raw)

        policy_number = meta.get("policy_number", policy_path.stem.split("-")[0])
        title = meta.get("title", policy_path.stem)
        source_url = meta.get("source_url", "")

        chunks = split_markdown_into_chunks(meta, body, max_chars=args.max_chars, overlap=args.overlap)

        for idx, chunk in enumerate(chunks, start=1):
            chunk_count += 1
            section_number = chunk.get("section_number") or policy_number
            section_title = chunk.get("section_title") or title
            chunk_id = f"{policy_number}-{idx:04d}-{slugify(section_title, 50)}"
            filename = f"{slugify(chunk_id, 120)}.json"

            chunk_payload = {
                "chunk_id": chunk_id,
                "policy_number": policy_number,
                "policy_title": title,
                "section_number": section_number,
                "section_title": section_title,
                "source_url": source_url,
                "policy_filename": policy_path.name,
                "text": chunk["text"],
            }

            (chunks_dir / filename).write_text(
                json.dumps(chunk_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            all_chunks.append(filename)

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "policy_file_count": len(policy_files),
        "chunk_count": chunk_count,
        "chunks_dir": str(chunks_dir),
        "files": all_chunks,
    }

    manifest_path = metadata_dir / "chunks_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Read {len(policy_files)} policy files.")
    print(f"Wrote {chunk_count} chunks to: {chunks_dir}")
    print(f"Wrote chunk manifest to: {manifest_path}")


def index_command(args):
    kb_dir = Path(args.kb)
    unit = args.unit
    index_dir = kb_dir / "index"
    db_path = index_dir / f"policy_fts_{unit}.db"
    index_dir.mkdir(parents=True, exist_ok=True)

    records = []

    if unit == "policies":
        source_dir = kb_dir / "policies"
        if not source_dir.exists():
            raise SystemExit(f"Policy directory not found: {source_dir}")

        for path in sorted(source_dir.glob("*.md")):
            raw = path.read_text(encoding="utf-8", errors="replace")
            meta, body = extract_frontmatter_and_body(raw)
            records.append({
                "unit": "policy",
                "filename": path.name,
                "policy_number": meta.get("policy_number", path.stem.split("-")[0]),
                "policy_title": meta.get("title", path.stem),
                "section_number": meta.get("policy_number", path.stem.split("-")[0]),
                "section_title": meta.get("title", path.stem),
                "source_url": meta.get("source_url", ""),
                "text": body,
            })

    elif unit == "chunks":
        source_dir = kb_dir / "chunks"
        if not source_dir.exists():
            raise SystemExit(f"Chunk directory not found: {source_dir}. Run the chunk command first.")

        for path in sorted(source_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            records.append({
                "unit": "chunk",
                "filename": path.name,
                "policy_number": data.get("policy_number", ""),
                "policy_title": data.get("policy_title", ""),
                "section_number": data.get("section_number", ""),
                "section_title": data.get("section_title", ""),
                "source_url": data.get("source_url", ""),
                "text": data.get("text", ""),
            })
    else:
        raise SystemExit("Invalid unit. Use --unit policies or --unit chunks.")

    if not records:
        raise SystemExit(f"No records found for unit: {unit}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS records")
    cur.execute("DROP TABLE IF EXISTS record_fts")
    cur.execute(
        """
        CREATE TABLE records (
            id INTEGER PRIMARY KEY,
            unit TEXT,
            filename TEXT NOT NULL,
            policy_number TEXT,
            policy_title TEXT,
            section_number TEXT,
            section_title TEXT,
            source_url TEXT,
            text TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE record_fts USING fts5(
            policy_number,
            policy_title,
            section_number,
            section_title,
            text,
            content='records',
            content_rowid='id'
        )
        """
    )

    for record in records:
        cur.execute(
            """
            INSERT INTO records (
                unit, filename, policy_number, policy_title, section_number,
                section_title, source_url, text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["unit"], record["filename"], record["policy_number"],
                record["policy_title"], record["section_number"], record["section_title"],
                record["source_url"], record["text"],
            ),
        )

    cur.execute(
        """
        INSERT INTO record_fts(rowid, policy_number, policy_title, section_number, section_title, text)
        SELECT id, policy_number, policy_title, section_number, section_title, text
        FROM records
        """
    )

    conn.commit()
    conn.close()

    latest_pointer = index_dir / "latest_index.json"
    latest_pointer.write_text(
        json.dumps({
            "unit": unit,
            "db_path": str(db_path),
            "record_count": len(records),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }, indent=2),
        encoding="utf-8",
    )

    print(f"Indexed {len(records)} {unit}.")
    print(f"Database written to: {db_path}")
    print(f"Latest index pointer written to: {latest_pointer}")


# ---------------------------------------------------------------------
# Search and answer helpers
# ---------------------------------------------------------------------


def resolve_db_path(kb_dir: Path, unit: str):
    db_path = kb_dir / "index" / f"policy_fts_{unit}.db"
    if not db_path.exists():
        raise SystemExit(f"Index not found: {db_path}. Run index --unit {unit} first.")
    return db_path


def run_fts_query(cur, query: str, top_k: int):
    cur.execute(
        """
        SELECT
            records.unit,
            records.filename,
            records.policy_number,
            records.policy_title,
            records.section_number,
            records.section_title,
            records.source_url,
            records.text,
            snippet(record_fts, 4, '[', ']', '...', 48) AS snippet,
            bm25(record_fts) AS rank
        FROM record_fts
        JOIN records ON records.id = record_fts.rowid
        WHERE record_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, top_k),
    )
    return [dict(row) for row in cur.fetchall()]


def search_index(kb_dir: Path, query: str, top_k: int = 5, unit: str = "chunks"):
    db_path = resolve_db_path(kb_dir, unit)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    safe_query = normalize_search_query(query)
    if not safe_query:
        safe_query = " ".join(re.findall(r"[A-Za-z0-9.]+", clean_text(query)))

    rows = []
    if safe_query:
        try:
            rows = run_fts_query(cur, safe_query, top_k)
        except sqlite3.OperationalError:
            rows = []

    if not rows and safe_query:
        terms = safe_query.split()
        if len(terms) > 1:
            try:
                rows = run_fts_query(cur, " OR ".join(terms), top_k)
            except sqlite3.OperationalError:
                rows = []

    if not rows and safe_query:
        terms = safe_query.split()
        try:
            rows = run_fts_query(cur, " OR ".join([f'"{term}"' for term in terms]), top_k)
        except sqlite3.OperationalError:
            rows = []

    conn.close()
    return rows


def build_context_blocks(kb_dir: Path, query: str, top_k: int, max_chars: int, unit: str):
    results = search_index(kb_dir, query, top_k, unit)
    context_blocks = []

    for row in results:
        text = row.get("text", "")[:max_chars].strip()
        context_blocks.append({
            "unit": row.get("unit", ""),
            "filename": row.get("filename", ""),
            "policy_number": row.get("policy_number", ""),
            "policy_title": row.get("policy_title", ""),
            "section_number": row.get("section_number", ""),
            "section_title": row.get("section_title", ""),
            "source_url": row.get("source_url", ""),
            "snippet": row.get("snippet", ""),
            "excerpt": text,
        })

    return context_blocks


def build_policy_answer_prompt(
    original_question: str,
    retrieval_question: str,
    context_blocks: list,
    output_language: str = "English",
):
    context_text_parts = []
    for idx, block in enumerate(context_blocks, start=1):
        label = block.get("policy_number") or block.get("filename") or f"Source {idx}"
        title = block.get("policy_title") or block.get("section_title") or "Untitled"
        excerpt = block.get("excerpt", "")
        context_text_parts.append(
            f"[Source {idx}: {label} - {title}]\n{excerpt}"
        )

    context_text = "\n\n".join(context_text_parts)

    system_prompt = f"""
You are the HarnessAI information desk. Answer using only the provided knowledge-base context.

Rules:
- Answer the user's question directly and practically.
- If the context does not contain enough information, say so plainly.
- Do not invent prices, guarantees, customer claims, compliance claims, or features.
- Do not provide legal, medical, financial, emergency, or confidential-record advice.
- If the question is out of scope, explain the boundary and suggest a human follow-up.
- Write the final answer in {output_language}.
""".strip()

    user_prompt = f"""
Original question:
{original_question}

Retrieval question:
{retrieval_question}

Knowledge-base context:
{context_text}

Answer in {output_language}.
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def search_command(args):
    rows = search_index(Path(args.kb), args.query, args.top_k, args.unit)
    print(json.dumps(rows, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Generic Markdown RAG utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chunk_parser = subparsers.add_parser("chunk")
    chunk_parser.add_argument("--kb", required=True)
    chunk_parser.add_argument("--clean", action="store_true")
    chunk_parser.add_argument("--max-chars", type=int, default=2200)
    chunk_parser.add_argument("--overlap", type=int, default=250)
    chunk_parser.set_defaults(func=chunk_command)

    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("--kb", required=True)
    index_parser.add_argument("--unit", choices=["policies", "chunks"], default="chunks")
    index_parser.set_defaults(func=index_command)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--kb", required=True)
    search_parser.add_argument("--unit", choices=["policies", "chunks"], default="chunks")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--top-k", type=int, default=5)
    search_parser.set_defaults(func=search_command)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
