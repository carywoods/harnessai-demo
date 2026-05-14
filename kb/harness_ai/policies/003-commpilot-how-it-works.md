---
policy_number: "003"
displayed_number: "003"
title: "CommPilot How It Works"
source_url: "https://commpilot.net"
source_file: "harness_ai_initial_kb"
---

# CommPilot How It Works

CommPilot uses a simple pipeline. It receives an email, identifies what the sender is asking, searches a curated knowledge base for relevant information, and generates a grounded response.

The knowledge base is built from Markdown files. Each file contains information about an organization's policies, procedures, services, contacts, common questions, or approved public guidance. Those files are split into searchable chunks and indexed with SQLite full-text search.

When a question arrives in another language, CommPilot can use model-based language handling to detect the language, translate the search meaning into English for retrieval, and then answer in the user's language. This is especially important when the knowledge base itself is written in English.

CommPilot can use separate models for separate jobs. A smaller or cheaper model can classify and translate the question. A stronger model can generate the final answer. For the Pike demo, Gemma 3 27B is currently used for both classification and answering because it performs better on Haitian Creole.

CommPilot works best when the knowledge base contains clear, approved source material. It should not invent policies, make legal decisions, or answer questions that require confidential records unless a human-approved workflow is added.