#!/usr/bin/env python3
"""Prepare opportunity visual inputs; Task 2 provides inspection only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opportunity_data import DataContractError, inspect_source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prepare_opportunities.py")
    subcommands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subcommands.add_parser("inspect")
    inspect_parser.add_argument("source", type=Path)
    inspect_parser.add_argument("--sheet")
    inspect_parser.add_argument("--json-key")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            report = inspect_source(args.source, args.sheet, args.json_key)
            print(json.dumps({"ok": True, **report}, separators=(",", ":")))
            return 0
    except DataContractError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": error.code,
                        "message": str(error),
                        "details": error.details,
                    },
                },
                separators=(",", ":"),
            )
        )
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
