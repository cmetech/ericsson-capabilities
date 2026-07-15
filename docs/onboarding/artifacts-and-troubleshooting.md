# Artifacts and Troubleshooting

Use this guide to explain what a capability produced, validate it safely, and recover
without hiding a partial effect or overwriting prior work.

## Artifact walkthrough

Before writing, identify the output type, whether it is synthetic, preview, draft,
generated local content, or live-system state, and the exact destination. Ask one
question if the destination is ambiguous. Choose a new path by default and never
overwrite an existing artifact without confirmation.

After a run:

1. State the actual path or live-system location.
2. Compare the result with the expected count, sections, filters, warnings, or other
   declared outcome.
3. Explain exclusions, partial completion, and fallback formats.
4. Point to supporting metadata such as a render manifest, workflow run state, or
   audit file when that capability creates one.
5. Explain how to rerun to a new destination and how to preserve the original.

An artifact pointer may be saved in a consented onboarding checkpoint only when it
is a safe local pointer. Do not save artifact contents, URLs, network/device paths,
alternate data streams, credentials, raw email or ticket content, or sensitive
diagnostics.

## Failure taxonomy

Classify the failure before proposing a fix:

- **not packaged or not discoverable:** reconcile the manifest, vendored snapshot,
  profile, and runtime registration;
- **generic user/profile suppression:** distinguish an explicit generic profile
  control from Ericsson packaging and product maturity; Ericsson has no
  disabled-by-default delivery declaration;
- **unsupported platform:** report `unavailable-on-platform` and the documented
  requirement;
- **missing configuration:** name the required setting but never its value;
- **authentication rejected or expired:** restart only the approved sign-in flow;
- **permission denied:** identify the resource and documented permission without
  guessing an access process;
- **dependency/server unavailable:** identify the package, process, application,
  executable, network, or TLS boundary;
- **invalid input:** preserve the user's source and ask for one missing correction;
- **source-system failure:** retain a redacted error and avoid speculative writes;
- **workflow-state failure:** use the workflow controller and run artifacts; never
  edit state JSON directly;
- **partial or uncertain side effect:** inspect first, do not blindly retry, and get
  fresh scoped approval for a remaining write;
- **artifact collision or ambiguity:** choose or confirm a new destination.

## Resume records

With consent, one active journey is stored per profile under
`$HERMES_HOME/onboarding/ericsson/current.json`; completed checkpoints move to
timestamped files in `history/`. The schema stores capability IDs, maturity,
last-known readiness facts, completed learning, pending actions, safe artifact
pointers, a next prompt, and timestamps. It rejects secret-shaped fields/values and
sensitive source content.

On resume, compare catalog versions and recheck volatile discovery, platform,
dependency, authentication, permission, and safe-probe facts. Never trust saved
`ready` as current evidence. `clear` forgets only the active checkpoint; `complete`
archives it without replacing an existing history name.

Persistence fails closed on unsafe paths. macOS/Linux reject symbolic-link path
components and use restrictive descriptor-relative operations. Windows rejects
reparse points, uses private ACLs and bounded interprocess locking, and performs
same-volume atomic replacement. A partial-effect error names only safe relative
recovery locations; inspect those locations before retrying.

For facilitator examples, see [mock sessions](mock-sessions.md). For Windows native
acceptance and evidence collection, use the
[release validation checklist](windows-resume-release-validation.md).
