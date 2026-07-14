---
source_flow: flows/privacy_vault/Pseudonymization.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: acdb5491fc76ee74bcc13ea7d87d85ea7cf12d3b102d4a8cc4b5276a694554e7
status: not-ported
target_artifacts: [privacy-vault-plugin, privacy-vault-skill]
supporting_capabilities: [presidio, spacy, optional-transformer, sqlite]
platforms: [macos, linux, windows]
---

# Pseudonymization

## What it does

Detects sensitive entities in a local document, replaces them with stable tokens such as `[PERSON_1]`, writes an anonymized copy, and stores the reversible token mapping under a session key.

## Original Loop24 flow

1. Receive a local file path from chat.
2. File Anonymizer uses spaCy plus optional BERT NER and Presidio recognizers.
3. Merge overlapping detections and add telecom patterns for identifiers including IMEI, IMSI, MSISDN, SIP URI, MAC address, coordinates, and site IDs.
4. Replace spans right-to-left, write `<stem>_anon.<ext>`, and persist session/filename/token/original mappings in SQLite.
5. Return session key, output path, entity count, and per-type breakdown to chat/API.

Supported source formats are TXT, Markdown, JSON, CSV, XML, DOCX, and PDF. PDF uses visual overlay behavior; DOCX handling can alter run-level formatting.

## Inputs and outputs

Inputs are file, output directory (source default `./anonymized`), and optional session key. Outputs are the anonymized file, session identifier, statistics, and a highly sensitive mapping record needed for reversal.

## Supporting capabilities and configuration

No API key is needed. See [privacy-vault configuration](../configuration.md#privacy-vault) for NLP models, local dependencies, storage, and offline-download implications.

## Failure, safety, and privacy behavior

Pseudonymization is not proof of anonymization. False negatives can leak PII; false positives can damage content. Preview detected categories/counts, use synthetic tests, restrict mapping-database permissions, define retention, and never upload the mapping alongside anonymized content. PDF overlays may leave underlying text recoverable and must not be marketed as secure redaction without dedicated verification.

## Hermes port status and target shape

Not ported. Use a local privacy plugin for deterministic file/mapping operations and a skill for explanation, review, retention, and safe handoff. Store mappings under protected per-brand state, not beside plugin source.

## How Hermes should explain and configure it

Ask file type, intended recipient/use, entity categories, reversibility need, retention, and whether local model downloads are allowed. Explain residual-risk and mapping sensitivity. Validate on a copy, show statistics without echoing originals, and tell the user where both output and protected mapping live.
