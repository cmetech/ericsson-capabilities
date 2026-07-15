---
source_flow: flows/privacy_vault/Pseudonymization.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: acdb5491fc76ee74bcc13ea7d87d85ea7cf12d3b102d4a8cc4b5276a694554e7
status: not-supported-no-port-planned
target_artifacts: []
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

## Historical dependencies

The source used Presidio, spaCy, optional transformer models, document libraries,
and SQLite. These are historical facts, not Co-Worker setup guidance; no supported
implementation exists to configure.

## Failure, safety, and privacy behavior

Pseudonymization is not proof of anonymization. False negatives can leak PII; false positives can damage content. Preview detected categories/counts, use synthetic tests, restrict mapping-database permissions, define retention, and never upload the mapping alongside anonymized content. PDF overlays may leave underlying text recoverable and must not be marketed as secure redaction without dedicated verification.

## Hermes port status

This legacy flow will not be ported. It remains documented only so Co-Worker can
answer historical questions accurately. There is no port roadmap, configuration
recipe, demonstration, or runnable implementation.

## How Co-Worker should explain it

State that the capability is unsupported and must not be run through Co-Worker.
Do not solicit files, sensitive values, or configuration for a nonexistent port.
