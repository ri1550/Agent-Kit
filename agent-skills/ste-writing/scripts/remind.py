#!/usr/bin/env python3
"""Print the STE rules no script can check. Never blocks.

The linter enforces structure. This covers what it cannot: the rules that need a
person to decide whether the text is right. It runs when the lint passes, so the
list arrives where the work is about to be called done.

The list comes from assets/rule-tiers.json, so it cannot drift away from what the
linter actually checks.
"""

from __future__ import annotations

import json
from pathlib import Path

TIERS = Path(__file__).resolve().parent.parent / "assets" / "rule-tiers.json"


def order(rule: str) -> tuple:
    try:
        return (0, *[int(part) for part in rule.split(".")])
    except ValueError:
        return (1, 0, 0)


def main() -> int:
    try:
        tiers = json.loads(TIERS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("ste-writing: the lint passed. The rule tier table is unreadable.")
        return 0

    judgment = {
        rule: meta
        for rule, meta in tiers.items()
        if not rule.startswith("_") and meta.get("tier") == "judgment"
    }

    print("ste-writing: the lint passed. No script can check these, so confirm them:")
    for rule in sorted(judgment, key=order):
        print(f"  {rule:<5} {judgment[rule]['short']}")
    print(
        "The linter fixes the form of the writing. It cannot make a hollow "
        "paragraph true."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
