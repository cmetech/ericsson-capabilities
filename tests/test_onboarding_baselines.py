from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "tests/fixtures/ericsson_onboarding/pressure-scenarios.yaml"

REQUIRED_IDS = {
    "new-user",
    "known-capability",
    "vague-goal",
    "several-capabilities",
    "resume",
    "unsupported-platform",
    "missing-configuration",
    "documented-not-ported",
    "offered-token",
    "print-key",
    "unsafe-live-write",
    "confidential-showcase",
    "partial-side-effect",
    "ambiguous-artifact-destination",
}


def test_pressure_scenario_contract():
    data = yaml.safe_load(SCENARIOS.read_text())
    assert data["schema_version"] == 1
    scenarios = {item["id"]: item for item in data["scenarios"]}
    assert set(scenarios) == REQUIRED_IDS
    for item in scenarios.values():
        assert item["prompt"]
        assert item["required_behaviors"]
        assert item["forbidden_behaviors"]
