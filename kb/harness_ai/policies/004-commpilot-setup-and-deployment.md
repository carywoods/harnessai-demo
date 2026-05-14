---
policy_number: "004"
displayed_number: "004"
title: "CommPilot Setup and Deployment"
source_url: "https://commpilot.net"
source_file: "harness_ai_initial_kb"
---

# CommPilot Setup and Deployment

A CommPilot deployment starts with a narrow use case and a curated knowledge base. The best first deployment answers a defined set of routine questions rather than trying to automate every communication workflow.

A typical setup requires an email account dedicated to CommPilot, approved source documents, a list of common questions, preferred escalation contacts, and clear boundaries for what the system should not answer.

HarnessAI does not recommend using an organization's primary mailbox for the initial CommPilot deployment. A separate mailbox keeps the workflow safer, easier to monitor, and easier to turn off or adjust.

Deployment options can include hosted infrastructure, self-hosted infrastructure, or a hybrid design. The Pike-style demo uses a Flask app, Markdown files, SQLite full-text search, and model calls through an OpenAI-compatible API endpoint.

A small pilot can often be assembled quickly when the source material is ready. Production use requires additional review, logging, monitoring, error handling, and human oversight rules.

The most important setup work is not the software install. The most important work is deciding what the system is allowed to answer, what source material it should trust, and when it should hand the request to a person.