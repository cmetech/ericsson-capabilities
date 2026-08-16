#!/usr/bin/env python3
"""Copy shared/ericsson_common/ into each consuming connector as _common/.

Run after editing anything under shared/ericsson_common/.  tests/
test_shared_sync.py fails if a copy drifts, so this is not optional.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANONICAL = REPO / "shared" / "ericsson_common"
PLUGINS = REPO / "plugins"
CONSUMERS = [
    "ericsson-jira",
    "ericsson-gitlab",
    "ericsson-confluence",
    "ericsson-arm",
]


def sync() -> int:
    if not CANONICAL.is_dir():
        print(f"error: no canonical source at {CANONICAL}", file=sys.stderr)
        return 1
    for plugin in CONSUMERS:
        target = PLUGINS / plugin / "_common"
        if not (PLUGINS / plugin).is_dir():
            print(f"error: no such plugin: {plugin}", file=sys.stderr)
            return 1
        # Remove first so deletions in the canonical source propagate.
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            CANONICAL,
            target,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                "*.pyc",
                "*.pyo",
            ),
        )
        print(f"synced -> {target.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(sync())
