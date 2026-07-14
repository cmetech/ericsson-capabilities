---
source_flow: flows/how-to/CI File Auditor.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: 9d067c265538ebe500cf590fd96ad1d567518529efbcab1a5c16e1f569c3ebeb
status: not-ported
target_artifacts: [ericsson-gitlab-plugin, ci-file-audit-workflow]
supporting_capabilities: [gitlab, hermes-agent]
platforms: [macos, linux, windows]
---

# CI File Auditor

## What it does

Audits one or more GitLab projects for CI/CD security problems, missing engineering practices, and coverage of a defined company-policy checklist. It combines repository/pipeline evidence with two structured analysis passes rather than returning a generic code review.

Use it for “audit these projects' GitLab CI,” “find unsafe variables or pipeline practices,” or “check CI policy coverage.” It is not a runtime penetration test and does not prove that a deployed system is secure.

## Original Loop24 flow

1. Read a file containing GitLab project URLs (the source includes `flows/gitrepo.csv`).
2. Loop over each row/project.
3. The CI/CD Collector resolves the project and gathers project metadata, branch information, recent pipeline statistics (default lookback 10 days), `.gitlab-ci.yml` content with includes resolved, and project/group CI variable metadata.
4. One LLM pass emits strict JSON findings in `security`, `best_practices`, and `other`, including rule IDs, severity, evidence, and recommendations.
5. A second LLM pass evaluates every named policy as `covered` or `not_covered`. The source policy set includes port scanning, vulnerability scanning, container security, and automated vulnerability assessment.
6. Results are displayed per project and the loop aggregates completion.

The collector defaults to the `RECENT` branch mode. GitLab variables are inspected as metadata such as name/type/masked/protected/scope; secret values must not be exposed to the model.

## Inputs and outputs

Inputs are a project list, branch selection (`ALL`, `RECENT`, or exact branch), lookback window, GitLab authentication, and optional mTLS certificate paths. Outputs are project/pipeline evidence plus two machine-readable audit reports. The port should save raw evidence and findings as separate run artifacts so users can distinguish observation from interpretation.

## Supporting capabilities and configuration

The source requires a GitLab PAT and may require mTLS. See [configuration](../configuration.md#gitlab-planned-hermes-capability). The current Ericsson capability set has no GitLab tools, so this flow cannot run end to end.

## Failure, safety, and privacy behavior

Use read-only GitLab access where possible. Never retrieve CI variable values. A project denied by permissions must be recorded separately rather than silently treated as compliant. Included CI files can be missing or cyclical; preserve collector warnings. Large project sets need bounded concurrency and per-project status.

## Hermes port status and target shape

Create reusable read-only GitLab tools for project resolution, CI files/includes, pipeline metrics, branches, and variable metadata. A deterministic workflow should iterate projects, store evidence, run two prompt nodes with validated JSON schemas, and assemble a report. The LLM nodes become Hermes prompt work; they are not plugins.

## How Hermes should explain and configure it

Ask which projects, desired branch scope, lookback period, and whether the user wants general findings, policy coverage, or both. Confirm GitLab readiness with identity/project/default-branch reads before collecting CI evidence. Explain clearly that the flow is not ported yet and can only be planned or performed manually with existing tools.
