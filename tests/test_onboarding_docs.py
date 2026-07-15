from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ONBOARDING_DOCS = (
    "README.md",
    "authoring.md",
    "safety-and-demonstrations.md",
    "artifacts-and-troubleshooting.md",
    "mock-sessions.md",
    "test-strategy-and-results.md",
    "windows-resume-release-validation.md",
)


def read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def test_onboarding_documentation_set_exists_and_is_indexed() -> None:
    for name in ONBOARDING_DOCS:
        assert (REPO / "docs/onboarding" / name).is_file(), name

    docs_index = read("docs/README.md")
    for name in ONBOARDING_DOCS:
        assert f"onboarding/{name}" in docs_index
    assert "onboard-ericsson-capabilities" in docs_index


def test_primary_docs_describe_the_implemented_no_toggle_contract() -> None:
    root_readme = read("README.md")
    assert "ERICSSON_ENV" not in root_readme
    assert "source of truth" in root_readme.lower()
    assert "vendored" in root_readme.lower() and "base" in root_readme
    assert ".venv/bin/python scripts/lint_manifest.py" in root_readme
    assert "python3 scripts/lint_manifest.py" not in root_readme
    configuration = read("docs/configuration.md")
    assert "Known configuration inconsistency" not in configuration
    assert "future Hermes setup-assistant skill" not in configuration
    assert "| Image Generation |" not in configuration

    context = read("docs/skill-design-context.md")
    assert "Future explain-and-configure skill" not in context
    assert "future Hermes skill" not in context
    assert "onboard-ericsson-capabilities" in context
    assert "Opportunity Visuals (available)" in context


def test_flow_status_docs_match_supported_product_decisions() -> None:
    pseudonymization = read("docs/flows/pseudonymization.md")
    assert "status: not-supported-no-port-planned" in pseudonymization
    assert "no port roadmap" in pseudonymization.lower()
    assert "privacy-vault configuration" not in pseudonymization

    reidentification = read("docs/flows/re-identification.md")
    assert "planned-not-implemented" in reidentification
    assert "mapping dependency" in reidentification.lower()
    assert "no runnable" in reidentification.lower()

    image_generation = read("docs/flows/image-generation.md")
    assert "Opportunity Visuals" in image_generation
    assert "available" in image_generation.lower()


def test_authoring_contract_is_actionable_and_complete() -> None:
    body = read("docs/onboarding/authoring.md")
    for command in (
        "build_catalog.py",
        "build_catalog.py --check",
        "validate_catalog.py",
        "node scripts/vendor-ericsson.mjs",
    ):
        assert command in body
    for responsibility in (
        "implementation",
        "manifest and runtime registration",
        "user-facing capability documentation",
        "configuration requirements",
        "natural-language trigger examples",
        "demo/test artifacts",
        "onboarding entry",
        "vendored Hermes snapshot",
    ):
        assert responsibility in body
    assert "source" in body and "base" in body and "brands/*.json" in body
    for delivery_command in (
        "node -e",
        "scripts/brand/generate.mjs $brand --write",
        "scripts/brand/generate.mjs $brand --check",
        "tests/hermes_cli/test_brand_runtime.py",
        "tests/providers",
        "git ls-tree",
        "while IFS= read -r brand",
    ):
        assert delivery_command in body
    for source_gate in (
        ".venv/bin/python scripts/lint_manifest.py sets/ericsson.json",
        ".venv/bin/pytest -q",
        "git diff --check",
        '"ok": true',
        "full source suite passes",
        "no whitespace errors",
    ):
        assert source_gate in body
    assert "Task 9 delivery prerequisite" in body
    assert "capabilities/ericsson-vendored-paths.json" in body


def test_authoring_delivery_verifies_ledger_and_source_bytes() -> None:
    body = read("docs/onboarding/authoring.md")

    # Cross-brand verification must follow the committed managed-path inventory,
    # not a hand-maintained subset that can drift as the manifest grows.
    for command in (
        "set -euo pipefail",
        "git show base:capabilities/ericsson-vendored-paths.json",
        "xargs git ls-tree -r base --",
        'xargs git ls-tree -r "$brand" --',
        "capabilities/ericsson.json",
        "capabilities/ericsson-vendored-paths.json",
    ):
        assert command in body

    # The delivery gate must compare committed source bytes with the committed
    # base snapshot for every manifest mapping and explicitly prove onboarding is
    # among those mappings.
    for command in (
        'git -C "$SOURCE_REPO" archive "$SOURCE_SHA" "$source_path"',
        'git archive base "$vendored_path"',
        'diff -qr "$VERIFY_ROOT/source/$mapping_index/$source_path"',
        'cut -f 2 "$SOURCE_MAP_FILE"',
        'diff -u "$SOURCE_DESTINATIONS_FILE" "$LEDGER_DESTINATIONS_FILE"',
        "skills/ericsson/onboard-ericsson-capabilities",
    ):
        assert command in body

    for semantic in (
        "full 40-character commit",
        "checkout-index",
        "ledger is an index, not unilateral deletion authority",
        "serialized",
        "per-path recovery",
        "Windows-native validation remains pending",
    ):
        assert semantic.lower() in body.lower()


def test_windows_resume_guide_is_explicit_about_pending_native_acceptance() -> None:
    body = read("docs/onboarding/windows-resume-release-validation.md")
    for requirement in (
        "11 skipped",
        "pending",
        "OS dispatch",
        "--collect-only",
        "test_onboarding_state_windows.py",
        "save",
        "show",
        "complete",
        "clear",
        "icacls",
        "SYSTEM",
        "junction",
        "reparse",
        "lock timeout",
        "atomic replacement",
        "history collision",
        "concurrent",
        "interrupted write",
        "profile isolation",
        "evidence",
    ):
        assert requirement.lower() in body.lower()
    assert "do not use real enterprise data" in body.lower()
    assert "paste" in body.lower() and "secret" in body.lower()
    assert "Set-Content -Path $InputA -Encoding utf8" not in body
    assert "[System.Text.UTF8Encoding]::new($false)" in body
    assert "$SourceRepo" in body and "$ReleaseRepo" in body
    assert "$SourcePython" in body and "$ReleasePython" in body
    assert "vendoredFrom" in body
    assert '$SourcePython = Join-Path $SourceRepo ".venv\\Scripts\\python.exe"' in body
    assert '$ReleasePython = Join-Path $ReleaseRepo "venv\\Scripts\\python.exe"' in body
    assert '$ReleasePython = Join-Path $ReleaseRepo ".venv\\Scripts\\python.exe"' not in body
    for line in body.splitlines():
        if line.lstrip().startswith("& $ReleasePython"):
            assert "$Installed" in line
    for junction_check in (
        "$JunctionExit = $LASTEXITCODE",
        "if ($JunctionExit -ne 0)",
        "Test-Path -LiteralPath $Junction",
        "FileAttributes]::ReparsePoint",
        '$JunctionItem.LinkType -ne "Junction"',
        "$StateExit = $LASTEXITCODE",
        "Test-Path -LiteralPath $TargetState",
        "PENDING/INCOMPLETE",
    ):
        assert junction_check in body
    junction_lines = body.splitlines()
    state_call = next(
        index
        for index, line in enumerate(junction_lines)
        if "$InstalledStateScript --home $Junction save" in line
    )
    assert junction_lines[state_call].startswith("$StateLines = & $ReleasePython")
    assert "|" not in junction_lines[state_call]
    assert junction_lines[state_call + 1] == "$StateExit = $LASTEXITCODE"
    assert "Task 9 delivery prerequisite" in body
    assert "ericsson-vendored-paths.json" in body


def test_windows_interpreter_paths_distinguish_source_and_installed_layouts() -> None:
    body = read("docs/onboarding/windows-resume-release-validation.md")

    assert '$SourcePython = Join-Path $SourceRepo ".venv\\Scripts\\python.exe"' in body
    assert '$ReleasePython = Join-Path $ReleaseRepo "venv\\Scripts\\python.exe"' in body
    assert "release-managed `hermes-agent` checkout beneath that profile and its\n  `venv\\Scripts\\python.exe`" in body
    # The dotted venv belongs only to the explicit source-checkout assignment;
    # installed-release prose and commands must never send a tester there.
    assert body.count(".venv\\Scripts\\python.exe") == 1


def test_generic_profile_suppression_is_not_described_as_ericsson_delivery_gating() -> None:
    safety = read("docs/onboarding/safety-and-demonstrations.md")
    troubleshooting = read("docs/onboarding/artifacts-and-troubleshooting.md")
    assert "generic profile/runtime suppression" in safety
    assert "generic user/profile suppression" in troubleshooting


def test_facilitator_showcase_names_fixture_paths_and_interpreters() -> None:
    body = read("docs/showcases/ericsson-capability-onboarding.md")
    assert "tests/fixtures/ericsson_onboarding/runtime-ready.json" in body
    assert "tests/fixtures/ericsson_onboarding/expected-ready-summary.json" in body
    assert "source checkout" in body.lower()
    assert "installed skill" in body.lower()


def test_onboarding_docs_do_not_restore_obsolete_ericsson_toggle_guidance() -> None:
    checked = [
        REPO / "README.md",
        REPO / "docs/configuration.md",
        REPO / "docs/skill-design-context.md",
        *(REPO / "docs/onboarding" / name for name in ONBOARDING_DOCS),
    ]
    for path in checked:
        if path.exists():
            assert "ERICSSON_ENV" not in path.read_text(encoding="utf-8"), path


def test_ported_flow_docs_do_not_advertise_resolved_ericsson_gate_debt() -> None:
    assert "ERICSSON_ENV" not in read(
        "docs/flows/jira-assigned-tickets-summary.md"
    )


def test_flow_template_routes_authors_to_the_implemented_onboarding_contract() -> None:
    body = read("docs/flows/_template.md")
    assert "future interactive skill" not in body
    assert "onboard-ericsson-capabilities" in body
    assert "onboarding entry" in body
