---
policy_number: "005"
displayed_number: "005"
title: "Multilingual Support"
source_url: "https://harnessai.net"
source_file: "harness_ai_initial_kb"
---

# Multilingual Support

HarnessAI systems can support multilingual question answering when the model and workflow are configured for it. The basic pattern is to detect the user's language, translate the search meaning into the language of the knowledge base, retrieve relevant source material, and answer in the user's language.

This matters because many organizations have English source documents but serve people who ask questions in Spanish, French, Haitian Creole, or other languages.

Rule-based language detection can be faster and cheaper, but it is less accurate for multilingual questions. Model-based language handling is usually better when the question needs translation before retrieval.

The Pike demo currently supports English, Spanish, French, and Haitian Creole as demonstration languages. Haitian Creole requires stronger model-based language handling than simple rule-based detection.

HarnessAI treats multilingual support as a practical access feature. It can help organizations answer routine questions more consistently across language communities, but translated answers should still be reviewed carefully for public or sensitive use cases.