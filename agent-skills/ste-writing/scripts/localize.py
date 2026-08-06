#!/usr/bin/env python3
"""Tell an agent how to localize the STE dictionary, then check what it wrote.

    python3 localize.py --en-GB          print the work plan
    python3 localize.py --en-GB --check  check data/locale-en-GB.json

ASD-STE100 rule 1.14 requires American spelling. That is correct for the
standard and wrong for a team that does not write American English, so this
skill ships no spelling list at all. Instead an agent walks the dictionary once
per language and writes the map, and the linter reads it.

Why an agent and not a script: the two are different jobs. A script can find the
candidates, because a British variant almost always differs by a known suffix.
It cannot decide the cases that matter. "practise" is the British verb and
"practice" the British noun. "programme" is British for a schedule but not for
software. "advise" is not a British spelling at all. Those need a reader.

So this script does the half a script is good at. It reads the built dictionary,
finds every word a suffix rule could touch, and hands the agent a short list with
the traps called out. The agent decides, and writes one JSON file.

The output lives in data/, which is not committed, so it is rebuilt after a
clone in the same way the dictionary is.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
DICTIONARY = DATA / "ste-dictionary.json"

# Suffixes that separate American from British spelling. Each finds candidates;
# none of them decides anything.
#
# Kept deliberately tight. A loose set ("-ed" for "-t", "-er" for "-re") matched
# 1760 words, most of them generated inflections like "woulded", and a list that
# long stops being a review and becomes a rubber stamp.
SUFFIXES = [
    "ize", "izes", "ized", "izing", "ization", "izer",
    "yze", "yzes", "yzed", "yzing",
    "og", "ogs",
    "eled", "eling", "eler",
]

# -our, -re, -ence, and the rest are not safe as suffix rules: "or" alone pulls
# in "motor" and "sensor" and every other noun that ends that way. These are the
# words where the pair is real, checked against the dictionary before use.
KNOWN_PAIRS = [
    "color", "colored", "colors", "favor", "favorite", "honor", "labor", "odor",
    "vapor", "armor", "rumor", "savor", "harbor", "neighbor", "behavior",
    "flavor", "humor", "endeavor", "splendor", "valor",
    "center", "centered", "centers", "meter", "meters", "liter", "liters",
    "fiber", "fibers", "theater", "caliber", "somber", "specter", "luster",
    "saber", "scepter", "maneuver", "maneuvers",
    "defense", "offense", "license", "pretense", "practice",
    "program", "programs", "aluminum", "airplane", "gray", "tire", "tires",
    "sulfur", "judgment", "aging", "acknowledgment", "plow", "mold", "molding",
    "smolder", "draft", "curb", "jail", "check", "gage", "story", "disk",
    "enroll", "enrollment", "fulfill", "fulfillment", "install", "installment",
    "skillful", "willful", "counterclockwise",
]

# Words a suffix rule reaches and gets wrong. The agent is told about these by
# name, because they are the errors a careless pass makes.
TRAPS = {
    "advise": "already British and American. Not an -ize word.",
    "surprise": "never -ize in any variety.",
    "exercise": "never -ize in any variety.",
    "compromise": "never -ize in any variety.",
    "promise": "never -ize in any variety.",
    "supervise": "never -ize in any variety.",
    "revise": "never -ize in any variety.",
    "practice": "British splits it: practise (verb), practice (noun).",
    "license": "British splits it: license (verb), licence (noun).",
    "program": "British 'programme' for a schedule, 'program' for software.",
    "meter": "British 'metre' for length, 'meter' for the instrument.",
    "draft": "British 'draught' for air or beer, 'draft' for a document.",
    "story": "British 'storey' for a floor, 'story' for a tale.",
    "disk": "British 'disc' generally, but 'disk' for magnetic media.",
    "tire": "British 'tyre' for the wheel, 'tire' for fatigue.",
}


class LocaleError(Exception):
    """The work cannot proceed."""


def load_dictionary() -> dict:
    if not DICTIONARY.is_file():
        raise LocaleError(
            f"No dictionary at {DICTIONARY}.\n"
            "Build it first:\n"
            f"  python3 {HERE / 'build-dictionary.py'} --pdf /path/to/ASD-STE100_ISSUE9.pdf"
        )
    return json.loads(DICTIONARY.read_text(encoding="utf-8"))


def candidates(dictionary: dict) -> list[str]:
    """The dictionary words whose spelling might differ in another language.

    Lemmas only. The dictionary also holds inflected forms this skill generates,
    and those produce candidates like "woulded" that waste the reviewer's
    attention and cost trust in the rest of the list.

    It still over-finds, on purpose: rejecting a word is far easier than
    remembering one. But it over-finds by a factor of two, not fifty.
    """
    lemmas = set(dictionary["approved"]["lemmas"])
    lemmas |= set(dictionary["alternatives"]["lemmas"])

    found = set()
    for word in lemmas:
        if not word.isalpha() or len(word) < 4:
            continue
        if word in KNOWN_PAIRS:
            found.add(word)
            continue
        for suffix in SUFFIXES:
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                found.add(word)
                break
    return sorted(found)


def plan(locale: str, dictionary: dict) -> str:
    words = candidates(dictionary)
    traps = sorted(set(words) & set(TRAPS))
    target = DATA / f"locale-{locale}.json"
    counts = dictionary.get("meta", {}).get("counts", {})

    lines = [
        f"# Localize the STE dictionary into {locale}",
        "",
        f"Source: {DICTIONARY.name}, "
        f"{counts.get('approved_lemmas', '?')} approved lemmas and "
        f"{counts.get('unapproved_lemmas', '?')} non-approved lemmas.",
        f"Write the result to: {target}",
        "",
        "## What to do",
        "",
        f"Below are {len(words)} words from the dictionary that a spelling rule",
        f"could touch. Go through them and keep only the ones that are really",
        f"spelled differently in {locale}. Reject the rest. Most will be rejects:",
        "the list is deliberately wide so that you decide, not the pattern.",
        "",
        "For each word you keep, record the American form and the "
        f"{locale} form.",
        "",
        "## Traps in this list",
        "",
        "These match a suffix rule and are wrong to convert, or are wrong to",
        "convert the obvious way. Read each one before you decide:",
        "",
    ]
    for word in traps:
        lines.append(f"  {word:<12} {TRAPS[word]}")
    if not traps:
        lines.append("  (none of the known traps are in this dictionary)")

    lines += [
        "",
        "Also reject any word where the two spellings mean different things.",
        "A wrong entry here makes the linter demand a change that is incorrect,",
        "which is worse than no spelling check at all.",
        "",
        "## Output format",
        "",
        json.dumps(
            {
                "meta": {
                    "locale": locale,
                    "source": DICTIONARY.name,
                    "note": (
                        "Deviates from ASD-STE100 rule 1.14, which requires "
                        "American spelling."
                    ),
                },
                "spellings": {"color": "colour", "organize": "organise"},
            },
            indent=1,
        ),
        "",
        "The key is the word to flag, which is the American spelling the",
        f"dictionary holds. The value is the {locale} spelling to use instead.",
        "That direction matters: the linter reports the key and suggests the",
        "value, so getting it backwards tells writers to undo correct work.",
        "",
        "Include the inflected forms you keep, as separate entries. The linter",
        "matches whole words and does no stemming here.",
        "",
        f"When you have written the file, check it: localize.py --{locale} --check",
        "",
        "## Candidates",
        "",
    ]
    for i in range(0, len(words), 8):
        lines.append("  " + "  ".join(f"{w:<16}" for w in words[i:i + 8]).rstrip())
    return "\n".join(lines) + "\n"


def check(locale: str, dictionary: dict) -> int:
    """Hold the agent's output to the contract, so a bad pass is not silent."""
    target = DATA / f"locale-{locale}.json"
    if not target.is_file():
        print(f"localize: nothing at {target} yet", file=sys.stderr)
        return 1
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"localize: {target} is not valid JSON: {error}", file=sys.stderr)
        return 1

    problems: list[str] = []
    if data.get("meta", {}).get("locale") != locale:
        problems.append(f'meta.locale should be "{locale}"')

    spellings = data.get("spellings")
    if not isinstance(spellings, dict) or not spellings:
        problems.append("spellings is missing or empty")
        spellings = {}

    known = set(dictionary["approved"]["forms"]) | set(dictionary["alternatives"]["forms"])
    for flagged, replacement in spellings.items():
        if flagged == replacement:
            problems.append(f"{flagged!r} maps to itself")
        if not str(flagged).isalpha() or not str(replacement).isalpha():
            problems.append(f"{flagged!r} -> {replacement!r} is not a pair of plain words")
        if flagged in TRAPS:
            problems.append(f"{flagged!r} is a known trap: {TRAPS[flagged]}")
        if replacement in TRAPS:
            problems.append(f"{replacement!r} is a known trap: {TRAPS[replacement]}")
        # The key is the word to flag, and it must be the one the dictionary
        # holds. Backwards entries tell writers to undo correct work, and they
        # are the single most likely mistake in this pass.
        if replacement in known and flagged not in known:
            problems.append(
                f"{flagged!r} -> {replacement!r} looks backwards: the dictionary "
                f"holds {replacement!r}, so that is the word to flag"
            )

    # A pair that touches no word in the dictionary does nothing. That is not an
    # error, but a pass that is mostly inert usually means it was guessed.
    inert = [f for f, a in spellings.items() if a not in known and f not in known]
    if spellings and len(inert) > len(spellings) // 2:
        problems.append(
            f"{len(inert)} of {len(spellings)} pairs match no word in the "
            "dictionary. Check that the pass read the real word list."
        )

    if problems:
        print(f"{target.name}: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"{target.name}: {len(spellings)} spelling pairs, and they check out.")
    print(f'Set "locale": "{locale}" in .ste-writing.json to switch rule 1.14 on.')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan and check a localisation of the STE dictionary.",
        epilog="Example: localize.py --en-GB",
    )
    parser.add_argument(
        "locale", nargs="?", help="a language tag, for example en-GB"
    )
    parser.add_argument("--check", action="store_true", help="check the written file")
    args, extra = parser.parse_known_args()

    # Accept --en-GB as well as a positional tag, because that is how it reads.
    locale = args.locale
    for flag in extra:
        if re.fullmatch(r"--[a-z]{2}(?:-[A-Za-z]{2,4})?", flag):
            locale = flag[2:]
    if not locale:
        parser.error("give a locale, for example --en-GB")

    try:
        dictionary = load_dictionary()
    except LocaleError as error:
        print(f"localize: {error}", file=sys.stderr)
        return 1

    if args.check:
        return check(locale, dictionary)
    print(plan(locale, dictionary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
