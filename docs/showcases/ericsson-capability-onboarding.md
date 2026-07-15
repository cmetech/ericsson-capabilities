# Ericsson Capability Onboarding Facilitator Showcase

This guide lets a pilot facilitator demonstrate the onboarding router without live
credentials, integrations, customer content, or writes. Every included record is
fictional and clearly labeled. Reusable inputs stay under
`tests/fixtures/ericsson_onboarding/`; generated demonstration output goes to a new
profile-scoped demo directory and must never overwrite an existing artifact.

## Before the session

1. Start a fresh Co-Worker conversation with the onboarding skill installed.
2. In a source checkout, use
   `tests/fixtures/ericsson_onboarding/runtime-ready.json` as the announced
   synthetic runtime state and
   `tests/fixtures/ericsson_onboarding/expected-ready-summary.json` for the final
   handoff. In an installed release, locate the installed skill through the active
   profile's Skills surface; its self-contained offline data is
   `fixtures/synthetic-jira-tickets.json` and its golden is
   `fixtures/expected-jira-summary.md`. Do not treat any fixture as evidence about a
   live Jira connection.
3. Choose a new destination such as
   `$HERMES_HOME/onboarding/ericsson/demos/SYNTH-JIRA-DIGEST-001/summary.md`.
4. From the source checkout root, run:

   ```bash
   .venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/render_synthetic_jira.py --check
   .venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/render_synthetic_jira.py --output <new-path>
   ```

   For an installed Windows release, use `$ReleasePython` and `$InstalledSkill` from
   the [Windows release checklist](../onboarding/windows-resume-release-validation.md),
   then run:

   ```powershell
   & $ReleasePython (Join-Path $InstalledSkill "scripts\render_synthetic_jira.py") --check
   & $ReleasePython (Join-Path $InstalledSkill "scripts\render_synthetic_jira.py") --output <new-path>
   ```

   Keep `fixtures/expected-jira-summary.md` open for the expected-versus-actual
   comparison. Do not substitute an unrelated system Python.

The skill should ask one question at a time. During discovery it loads only the
compact `references/catalog.json`; after Jira is selected it loads
`references/capabilities/jira-assigned-ticket-summary.md` plus only the policy for
the chosen route.

## End-to-end Jira onboarding

Use the following checkpoints rather than memorizing a transcript. Let the model
phrase the conversation naturally.

1. User: **“Please onboard me to the Co-Worker capabilities.”**
2. Expected response: a short welcome and one role-, goal-, or outcome-oriented
   question. It must not recite the whole catalog.
3. User: **“I need a quick way to catch up on the work assigned to me after time
   away.”**
4. Expected response: recommend no more than two matches. Select **Jira Assigned-Ticket Summary**
   because it groups unresolved assigned work for review.
5. Verify the skill reports product maturity **`available`** before runtime
   readiness. Supply the declared synthetic runtime facts and verify it reports
   **`ready`** only because discoverability, platform, protected-setting presence,
   authentication, permission, dependency, and the read-only probe all succeeded.
   This is fixture readiness, not proof of a live integration.
6. Choose **Synthetic demonstration**. The facilitator identifies the mode as
   **`synthetic/offline`**, names fixture `SYNTH-JIRA-DIGEST-001`, previews the
   expected result and destination, and asks for confirmation before creating the
   output.
7. Render the three fictional tickets in priority order with the shipped command.
   Compare the generated Markdown byte-for-byte with
   `fixtures/expected-jira-summary.md`. Record an honest pass or discrepancy; do
   not rewrite expected output to hide a difference.
8. Complete artifact inspection: show the new output path, verify the fixture ID,
   ticket count, priority sections, and the explicit fictional/offline label.
9. Show the personalized handoff in `expected-ready-summary.json`: selected
   capability, maturity, readiness facts, completed synthetic/offline learning,
   missing actions, safe artifact pointer, and suggested next prompt.
10. Ask for consent before saving the first persistent checkpoint. On consent, save
    only the sanitized handoff. Never save ticket bodies, protected values, or raw
    diagnostics.

## Fresh-conversation resume

Close the conversation, open a fresh conversation under the same active profile,
and say **“Resume my Ericsson onboarding.”** The skill should locate the consented
checkpoint, summarize completed Jira learning, recheck volatile readiness rather
than trusting saved `ready`, and offer exactly one next step. It must not invent
state when the checkpoint is absent or read another profile's state.

## Opportunity Visuals short path

Ask **“Show me how Opportunity Visuals works.”** Select the synthetic demonstration
route. Reuse the existing [Opportunity Visuals showcase](opportunity-visuals.md) and
its fixture builder by reference; do not copy its spreadsheets, golden SVGs, or
audit artifacts into this showcase. The response should label the fixture
synthetic, preview expected outputs and destination, compare the generated result,
and explain artifact inspection.

## Outlook on macOS short path

On macOS, ask **“Help me configure the Outlook inbox digest.”** Use
`runtime-unsupported-platform.json`. The response should report maturity
`available` and readiness **`unavailable-on-platform`**, explain that the packaged
classic Outlook/COM path requires Windows, and avoid presenting missing settings as
the cause. It may explain the Windows prerequisite; it must not claim the local
macOS path can be configured or that a live Outlook test succeeded.

## Facilitator pass criteria

- Intake and resume use one question at a time and reuse known answers.
- Recommendation is bounded, and maturity is never confused with readiness.
- The Jira run remains fictional, credential-free, synthetic/offline, and free of
  Jira comments, emails, Teams messages, or other writes.
- The expected-versus-actual check and artifact inspection are visible to the user.
- Checkpoint persistence happens only after consent and contains sanitized summary
  facts, not fixture content.
- Opportunity Visuals is reused by link, while Outlook/macOS remains honestly
  unavailable-on-platform.
