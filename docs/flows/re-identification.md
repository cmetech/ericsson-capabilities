---
source_flow: flows/privacy_vault/Re-Identification.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: 9a65f7a5da6b89ade8fc8a17be5b84d864ab31cabf587bec868fb63608bd774e
status: not-ported
target_artifacts: [privacy-vault-plugin, privacy-vault-skill]
supporting_capabilities: [sqlite, privacy-vault]
platforms: [macos, linux, windows]
---

# Re-Identification

## What it does

Restores a file previously produced by Pseudonymization by resolving its session mapping and replacing tokens with original sensitive values.

## Original Loop24 flow

1. Receive an anonymized file path through chat/text input.
2. File De-Anonymizer derives the session from the recorded filename or accepts an explicit session key.
3. Load the token-to-original mapping from `mapping_store.db`.
4. Replace recognized `[UPPERCASE_TYPE_N]` tokens.
5. Write `<stem>_restored.<ext>` (removing `_anon` when present) and return the session, path, restored count, and type breakdown.

## Inputs and outputs

Inputs are anonymized file, protected mapping store, output directory (source default `./restored`), and optional session key. Output is a restored document containing the original sensitive information.

## Supporting capabilities and configuration

No runnable Co-Worker configuration exists. The corresponding protected
token-to-original mapping is mandatory, but the Pseudonymization/mapping dependency
that would create it is unavailable. Do not request a mapping, session key, file, or
original value as a setup step.

## Failure, safety, and privacy behavior

Fail closed when a mapping is missing, ambiguous, corrupt, or does not belong to the file. Never guess token values. Re-identification is a sensitive disclosure action: verify authorization and destination, avoid chat previews of restored content, and write to a protected artifact location. Preserve the source anonymized file.

## Co-Worker port status

`planned-not-implemented`; there is no runnable port. Re-Identification cannot be
executed independently of a reviewed protected mapping/storage implementation. This
dependency statement records the present limitation and does not infer a new roadmap
decision.

## How Co-Worker should explain it

State that no runnable mapping capability is available and refuse execution. Do not
solicit an anonymized file, session, destination, or sensitive content. Historical
safety requirements may be explained without presenting setup steps.
