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

No API key is required, but the corresponding mapping is mandatory. It should share a local privacy-vault implementation with Pseudonymization. See [privacy-vault configuration](../configuration.md#privacy-vault).

## Failure, safety, and privacy behavior

Fail closed when a mapping is missing, ambiguous, corrupt, or does not belong to the file. Never guess token values. Re-identification is a sensitive disclosure action: verify authorization and destination, avoid chat previews of restored content, and write to a protected artifact location. Preserve the source anonymized file.

## Hermes port status and target shape

Not ported and should not be implemented separately from the mapping/storage design. A local plugin should provide session lookup and restore; a skill should enforce authorization, explain consequences, and guide secure cleanup.

## How Hermes should explain and configure it

Ask which anonymized file/session, why restoration is needed, who may receive it, and where it may be written. Validate mapping existence without revealing originals. Require explicit confirmation immediately before restoration and report only counts/path unless the user asks to inspect the protected artifact.
