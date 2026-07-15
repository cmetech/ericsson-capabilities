import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests/model_behavior"))

from run_onboarding_evaluation import build_command, prepare_hermes_home


def test_build_command_and_isolated_home(tmp_path):
    command = build_command(
        "otto",
        "otto",
        "auto",
        "Please onboard me to the Co-Worker capabilities.",
    )

    assert command == [
        "otto",
        "chat",
        "-q",
        "Please onboard me to the Co-Worker capabilities.",
        "--provider",
        "otto",
        "-m",
        "auto",
        "--quiet",
    ]

    home = prepare_hermes_home(tmp_path / "hermes-home", "otto", "auto")
    assert (home / "config.yaml").is_file()
    assert not list(home.rglob(".env"))
    assert not list(home.rglob("auth.json"))
