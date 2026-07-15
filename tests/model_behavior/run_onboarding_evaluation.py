#!/usr/bin/env python3
"""Run Ericsson onboarding scenarios in isolated Hermes homes."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

SYNTHETIC_SECRET = "synthetic-secret-value"
REDACTION = "[REDACTED]"
SENSITIVE_FILE_NAMES = {
    ".env",
    "auth.json",
    "credentials.json",
    "credential-pool.json",
    "credential_pool.json",
    "tokens.json",
}
PASSTHROUGH_ENV = {
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "WINDIR",
}


def build_command(
    agent_command: str,
    provider: str,
    model: str,
    prompt: str,
    skill_name: str | None = None,
) -> list[str]:
    """Build one non-interactive Hermes chat invocation."""
    command = shlex.split(agent_command)
    if not command:
        raise ValueError("agent command must not be empty")
    if skill_name:
        command.extend(["--skills", skill_name])
    command.extend(
        [
            "chat",
            "-q",
            prompt,
            "--provider",
            provider,
            "-m",
            model,
            "--quiet",
        ]
    )
    return command


def _ignored_sensitive_files(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name.lower() in SENSITIVE_FILE_NAMES}


def prepare_hermes_home(
    home: Path,
    provider: str,
    model: str,
    skill_source: Path | None = None,
) -> Path:
    """Create a home containing only model config and an optional source skill."""
    home.mkdir(parents=True, exist_ok=False)
    config = {"model": {"default": model, "provider": provider}}
    (home / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    if skill_source is not None:
        source = skill_source.resolve()
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise ValueError(f"skill source must be a skill directory: {source}")
        destination = home / "skills" / "ericsson" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, ignore=_ignored_sensitive_files)

    return home


def _isolated_environment(home: Path) -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if name in PASSTHROUGH_ENV
    }
    environment.update(
        {
            "HERMES_HOME": str(home),
            "HOME": str(home),
            "NO_COLOR": "1",
        }
    )
    return environment


def _redact(value: str) -> str:
    return value.replace(SYNTHETIC_SECRET, REDACTION)


def _load_scenarios(path: Path, selected_ids: list[str]) -> list[dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenarios = document.get("scenarios", [])
    by_id = {scenario["id"]: scenario for scenario in scenarios}
    unknown = sorted(set(selected_ids) - set(by_id))
    if unknown:
        raise ValueError(f"unknown scenario id(s): {', '.join(unknown)}")
    return [by_id[scenario_id] for scenario_id in selected_ids] if selected_ids else scenarios


def _evaluate_scenario(
    scenario: dict[str, Any],
    *,
    agent_command: str,
    provider: str,
    model: str,
    skill_source: Path | None,
) -> dict[str, Any]:
    skill_name = skill_source.resolve().name if skill_source is not None else None
    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="ericsson-onboarding-") as temporary:
        home = prepare_hermes_home(
            Path(temporary) / "home", provider, model, skill_source
        )
        command = build_command(
            agent_command, provider, model, scenario["prompt"], skill_name
        )
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                cwd=home,
                env=_isolated_environment(home),
                text=True,
            )
            exit_code: int | None = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except OSError as error:
            exit_code = None
            stdout = ""
            stderr = f"{type(error).__name__}: {error}"

    return {
        "scenario_id": scenario["id"],
        "model": model,
        "configuration": {
            "agent_command": agent_command,
            "provider": provider,
            "skill_name": skill_name,
            "isolated_home": True,
        },
        "exit_code": exit_code,
        "stdout": _redact(stdout),
        "stderr": _redact(stderr),
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-command", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--scenario-id", action="append", default=[])
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skill-source", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    scenarios = _load_scenarios(args.scenarios, args.scenario_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        for scenario in scenarios:
            result = _evaluate_scenario(
                scenario,
                agent_command=args.agent_command,
                provider=args.provider,
                model=args.model,
                skill_source=args.skill_source,
            )
            output.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
