#!/usr/bin/env python3
"""Print the STE rules no script can check. Never blocks.

The linter enforces structure. This covers what it cannot: the rules that need a
person to decide whether the text is right. It runs when the lint passes, so the
list arrives where the work is about to be called done.

The list comes from ste_policy.RULES, so it cannot drift away from what the
linter actually checks.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ste_policy  # noqa: E402  (needs the path above)


def order(rule: str) -> tuple:
    try:
        return (0, *[int(part) for part in rule.split(".")])
    except ValueError:
        return (1, 0, 0)


def main() -> int:
    judgment = {
        rule: entry for rule, entry in ste_policy.RULES.items()
        if entry.tier == "judgment"
    }
    print("ste-writing: the lint passed. No script can check these, so confirm them:")
    for rule in sorted(judgment, key=order):
        print(f"  {rule:<5} {judgment[rule].short}")
    print(
        "The linter fixes the form of the writing. It cannot make a hollow "
        "paragraph true."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
