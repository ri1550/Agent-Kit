#!/usr/bin/env python3
"""Build the local STE data files from your own copy of ASD-STE100.

This repository ships no content from the standard. The standard is copyrighted,
and its free-use grant covers named organizations, not a public repository. So
you download the PDF yourself, and this script turns your copy into the data
files that ste-lint.py reads.

    python3 build-dictionary.py --pdf ~/Downloads/ASD-STE100_ISSUE9.pdf

Output goes to ../data/, which is not committed. Get the PDF free (registration
required) from https://asd-ste100.org.

The script fails loudly when it extracts less than it expects. A dictionary that
is quietly 40% complete is worse than no dictionary, because strict mode would
then pass text it never actually checked.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

import ste_data
import ste_policy

BUILDER = Path(__file__).name

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
DEFAULT_OUT = SKILL_DIR / "data"

# Parts of speech the dictionary uses. TN is a technical noun.
POS = "n|v|adj|adv|prep|pron|conj|art|int|abbr|num|det|TN"

HEADWORD = re.compile(rf"^(?P<word>[A-Za-z][A-Za-z0-9 \-/'’.]*?)\s+\((?P<pos>{POS})\)")
PAGE_WORDLIST = re.compile(r"Page 2-1-[A-Z]+\d+")
PAGE_PART1 = re.compile(r"Page 1-(\d)-\d+")
PAGE_INDEX = re.compile(r"Page SRI-\d+")
RULE_HEAD = re.compile(r"^\s*Rule\s+(\d+\.\d+)\b\s*(.*)$")

# Section 9 ends with eight general recommendations, GR-1 thru GR-8. They are
# not rules, and the standard says so, but its own subject index sends the
# reader to them ("Inclusive language: 9 - GR-7"). So they are extracted as
# records of their own. An index entry that names a target nothing can open is
# worse than no index.
GR_START = re.compile(r"^\s*General recommendations\s*$")
GR_HEAD = re.compile(r"^\s*GR-(\d+)\s+(\S.*)$")

# The two sides of a worked example. The standard prints them in one of a few
# ways, all of them a label, a colon, and the sentence.
EXAMPLE_WRONG = re.compile(
    r"^(\s*)(Non-STE|Do not write|Do not use|Passive|Incorrect|NOT)\s*:\s*(.*)$"
)
EXAMPLE_RIGHT = re.compile(r"^(\s*)(STE|WRITE|Active|CORRECT)\s*:\s*(.*)$")
# A line that is only a note about the example, not part of the sentence.
EXAMPLE_ASIDE = re.compile(r"^\s*(?:\(.*\)|or)\s*$")
# Rule 3.6 gives an active sentence that is still wrong, to show that the
# active voice alone is not enough. The label says STE and the sentence is a
# counter-example, so it is dropped: an example is a sentence to copy.
COUNTER_EXAMPLE = re.compile(r"\((?:incorrect|not correct|wrong)\b", re.I)

# Lines that are page furniture rather than content.
FURNITURE = re.compile(
    r"^\s*(ASD[- ]STE100 Simplified Technical English"
    r"|Issue \d"
    r"|Page [A-Z0-9-]+"
    r"|\d{4}-\d{2}-\d{2}"
    r"|Blank Page"
    r"|Part [12] [-–] "
    r"|Word\s*$"
    r"|\(part of speech\)"
    r"|Approved meaning/"
    r"|ALTERNATIVES"
    r"|STE EXAMPLE"
    r"|Non-STE example"
    r")",
)

SECTION_NAMES = {
    "1": "words",
    "2": "multi-word-nouns",
    "3": "verbs",
    "4": "sentences",
    "5": "procedural-writing",
    "6": "descriptive-writing",
    "7": "safety-instructions",
    "8": "punctuation-and-word-count",
    "9": "writing-practices",
}

# The extraction is only trusted when it clears these. Issue 9 yields 799
# approved lemmas, 1239 unapproved, 53 rules, and 112 index subjects. The
# thresholds sit just under those: close enough that a parsing regression fails
# the build, loose enough to absorb small edits within an issue. A later issue
# that legitimately differs needs --force and a look at the output by hand.
MINIMUMS = {
    "approved": 780,
    "unapproved": 1200,
    "rules": 53,
    "recommendations": 8,
    "examples": 170,
    "index_subjects": 100,
}

# Entries that must survive, one per parsing hazard that has actually bitten:
# a plain approved word, an irregular auxiliary split over three lines, a verb
# with inflected forms, a wrapped headword, a two-word headword, and three
# unapproved words with known replacements.
SPOT_CHECKS_APPROVED = ["above", "be", "is", "was", "absorb", "absorbs", "absorbed",
                        "chemically", "give", "given", "make sure", "can", "will"]
SPOT_CHECKS_ALTERNATIVES = {
    "abate": "DECREASE",
    "accomplish": "DO",
    "abnormal": "UNUSUAL",
    "check": "MAKE SURE",
    "utilize": "USE",
}

# One rule for each way the standard lays a worked example out: "Non-STE / STE",
# "Do not write / WRITE", and the same inside a recommendation. The example
# pairs are what an agent fixes a finding from, and a layout change would
# otherwise empty them in silence.
SPOT_CHECKS_EXAMPLES = ["2.1", "3.6", "5.3", "9.1", "GR-1"]


class BuildError(Exception):
    """Something went wrong that the user has to fix."""


# --------------------------------------------------------------------------
# PDF text
# --------------------------------------------------------------------------

def extract_text(pdf: Path) -> str:
    """Run pdftotext and return the whole document, one page per form feed."""
    if not pdf.is_file():
        raise BuildError(f"No PDF at {pdf}")
    if shutil.which("pdftotext") is None:
        raise BuildError(
            "pdftotext is not installed. It comes with poppler:\n"
            "  Arch:   sudo pacman -S poppler\n"
            "  Debian: sudo apt install poppler-utils\n"
            "  macOS:  brew install poppler"
        )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ste.txt"
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf), str(out)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise BuildError(f"pdftotext failed:\n{result.stderr.strip()}")
        text = out.read_text(encoding="utf-8", errors="replace")
    if "Simplified Technical English" not in text:
        raise BuildError(
            f"{pdf.name} does not look like ASD-STE100. Check that you gave the "
            "right file."
        )
    return text


def columns(page: str) -> tuple[int, int, int] | None:
    """Find the header row of a dictionary page and read its column starts.

    The four columns do not sit at fixed offsets: they move by a few characters
    from page to page. So every page reports its own geometry, taken from the
    header row that the table repeats at the top of each page.
    """
    lines = page.split("\n")
    for i, line in enumerate(lines):
        if "(part of speech)" not in line:
            continue
        pair = [lines[i - 1] if i else "", line]

        def find(keyword: str) -> int:
            for candidate in pair:
                at = candidate.find(keyword)
                if at >= 0:
                    return at
            return -1

        col2 = max(find("ALTERNATIVES"), find("Approved meaning"))
        col3 = find("STE EXAMPLE")
        if col2 > 0 and col3 > col2:
            return i, col2, col3
    return None


# --------------------------------------------------------------------------
# Part 2, the dictionary
# --------------------------------------------------------------------------

def dictionary_rows(pages: list[str]) -> list[tuple[str, str]]:
    """Return (column 1, column 2) for every body line of the word list.

    Pages are concatenated in order so that an entry which starts at the foot of
    one page and finishes at the head of the next stays a single entry.
    """
    rows: list[tuple[str, str]] = []
    for page in pages:
        if not PAGE_WORDLIST.search(page):
            continue
        geometry = columns(page)
        if geometry is None:
            continue
        header, col2, col3 = geometry
        for line in page.split("\n")[header + 1:]:
            if FURNITURE.match(line):
                continue
            rows.append((line[:col2].rstrip(), line[col2:col3].rstrip()))
    return rows


def split_entries(rows: list[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    """Group the rows into entries: a headword block and its column 2 lines.

    An entry starts on a column 1 line at the left margin that follows a break.
    Consecutive unindented lines belong to the same headword, which is how the
    inflected forms ("ABSORBS," "ABSORBED,") and headwords that wrap over two
    lines ("CHEMICALLY" / "(adv)") stay attached to their entry.

    Indented column 1 text is a note ("No other verb forms.") and is dropped.
    Column 2 keeps its blank lines: they are the row separators, and without
    them a definition and the replacements below it merge into one block.
    """
    entries: list[tuple[str, list[str]]] = []
    head: list[str] = []
    body: list[str] = []
    in_headword = False

    def join(parts: list[str]) -> str:
        """Join headword lines, closing the hyphen the typesetter used to wrap.

        "ELECTROMAG-" + "NETIC (adj)" is one word, not two.
        """
        block = ""
        for part in parts:
            if block.endswith("-"):
                block = block[:-1] + part
            elif block:
                block = f"{block} {part}"
            else:
                block = part
        return block

    def flush() -> None:
        if not head:
            return
        block = join(head)
        if HEADWORD.match(block):
            entries.append((block, body[:]))
        elif entries:
            # Not a headword after all. Its column 2 lines belong to whatever
            # entry came before, so give them back rather than losing them.
            entries[-1][1].extend(body)

    for col1, col2 in rows:
        unindented = bool(col1) and not col1[0].isspace()
        if unindented:
            # Entries are not always separated by a blank line. A line that is
            # itself a "word (pos)" heading starts a new entry when the block so
            # far is already complete; otherwise it continues the current one,
            # which is how inflected forms and wrapped headwords stay attached.
            complete = bool(head) and HEADWORD.match(join(head))
            if not in_headword or (complete and HEADWORD.match(col1.strip())):
                flush()
                head, body = [col1.strip()], []
            else:
                head.append(col1.strip())
            in_headword = True
        elif not col1.strip():
            in_headword = False
        body.append(col2)
    flush()
    return entries


def parse_headword(block: str) -> tuple[str, str, list[str]] | None:
    """Split a headword block into (lemma, part of speech, inflected forms)."""
    match = HEADWORD.match(block)
    if not match:
        return None
    lemma = re.sub(r"\s+", " ", match.group("word")).strip().lower()
    pos = match.group("pos")
    if not lemma or lemma in {"word", "example", "examples", "note"}:
        return None

    # Everything after the "(pos)" is the verb or adjective forms, given as a
    # comma-separated run: "ABSORBS, ABSORBED, ABSORBED" or "(SLOWER, SLOWEST)".
    forms = {lemma}
    for token in re.split(r"[,()]", block[match.end():]):
        token = token.strip().lower()
        token = re.sub(r"^(?:also|or)\s+", "", token)
        if token and re.fullmatch(r"[a-z][a-z\-' ]*", token) and token != "no other verb forms.":
            forms.add(token)
    return lemma, pos, sorted(forms)


def is_alternative(text: str) -> bool:
    """True when a column 2 block is a replacement word, not a definition.

    Replacements are printed in uppercase. Definitions are sentence case. The
    part-of-speech tag in parentheses is lowercase in both, so it is removed
    before the test.
    """
    stripped = re.sub(r"\([^)]*\)", "", text)
    stripped = re.sub(r"[^A-Za-z]", "", stripped)
    return bool(stripped) and stripped.isupper()


def column2_blocks(lines: list[str]) -> list[str]:
    """Join column 2 into blocks, one per printed row of the table."""
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return blocks


def parse_dictionary(pages: list[str]) -> tuple[dict, dict]:
    """Extract the approved word list and the unapproved-to-approved map."""
    approved: dict[str, dict] = OrderedDict()
    alternatives: dict[str, dict] = OrderedDict()

    for block, col2 in split_entries(dictionary_rows(pages)):
        parsed = parse_headword(block)
        if parsed is None:
            continue
        lemma, pos, forms = parsed
        blocks = column2_blocks(col2)

        if block.strip()[0].isupper() and lemma.upper() in block.upper():
            # An approved word is printed in uppercase.
            head = block.split("(")[0].strip()
            if head.isupper():
                entry = approved.setdefault(lemma, {"pos": [], "forms": [], "meaning": ""})
                if pos not in entry["pos"]:
                    entry["pos"].append(pos)
                entry["forms"] = sorted(set(entry["forms"]) | set(forms))
                meaning = next((b for b in blocks if not is_alternative(b)), "")
                if meaning and not entry["meaning"]:
                    entry["meaning"] = re.sub(r"^\d+\.\s*", "", meaning)[:200]
                continue

        replacements = [
            re.sub(r"\s+", " ", b).strip()
            for b in blocks
            if is_alternative(b)
        ]
        replacements = [r for r in replacements if 1 < len(r) < 60]
        if not replacements:
            continue
        entry = alternatives.setdefault(lemma, {"pos": [], "replacements": []})
        if pos not in entry["pos"]:
            entry["pos"].append(pos)
        for r in replacements:
            if r not in entry["replacements"]:
                entry["replacements"].append(r)

    return approved, alternatives



# --------------------------------------------------------------------------
# Part 1, the writing rules
# --------------------------------------------------------------------------

def clean(page: str) -> list[str]:
    """Drop page furniture from a Part 1 page."""
    return [
        line.rstrip()
        for line in page.split("\n")
        if not FURNITURE.match(line)
    ]


def rule_blocks(pages: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Return {section number: [(rule id, rule text), ...]}.

    Each section prints its rules twice: a summary list at the front, then the
    full treatment with examples. Both match the same heading pattern, so the
    longer block wins.
    """
    by_section: dict[str, list[str]] = {}
    for page in pages:
        match = PAGE_PART1.search(page)
        if not match:
            continue
        section = match.group(1)
        if section == "0":
            continue
        by_section.setdefault(section, []).extend(clean(page))

    rules: dict[str, list[tuple[str, str]]] = {}
    for section, lines in sorted(by_section.items()):
        blocks: dict[str, list[str]] = {}
        current: str | None = None
        buffer: list[str] = []
        for line in lines:
            head = RULE_HEAD.match(line)
            if head and head.group(1).split(".")[0] == section:
                if current:
                    blocks.setdefault(current, []).append("\n".join(buffer))
                current = head.group(1)
                buffer = [head.group(2).strip()] if head.group(2).strip() else []
            elif current:
                buffer.append(line)
        if current:
            blocks.setdefault(current, []).append("\n".join(buffer))

        chosen = []
        for rule_id, variants in blocks.items():
            best = max(variants, key=len)
            best = re.sub(r"\n{3,}", "\n\n", best).strip()
            chosen.append((rule_id, best))
        chosen.sort(key=lambda r: [int(n) for n in r[0].split(".")])
        rules[section] = chosen
    return rules


def split_recommendations(body: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Cut the general recommendations off the end of the last rule of section 9.

    They fall inside that rule's block only because they follow it on the page
    and carry no "Rule" heading of their own.
    """
    lines = body.split("\n")
    start = next((i for i, line in enumerate(lines) if GR_START.match(line)), None)
    if start is None:
        return body, []

    found: list[tuple[str, str, str]] = []
    current: tuple[str, str] | None = None
    buffer: list[str] = []
    for line in lines[start + 1:]:
        head = GR_HEAD.match(line)
        if head:
            if current:
                found.append((*current, "\n".join(buffer).strip()))
            current = (f"GR-{head.group(1)}", head.group(2).strip())
            buffer = []
        elif current:
            buffer.append(line)
    if current:
        found.append((*current, "\n".join(buffer).strip()))
    return "\n".join(lines[:start]).strip(), found


def parse_examples(body: str) -> list[dict]:
    """Pull the worked examples out of a rule.

    The examples are the part of a rule that an agent can act on directly: the
    sentence the standard refuses, and the sentence it writes instead. In the
    markdown they were prose in a wall of prose, so nothing could reach them.

    A label can wrap onto the lines below it, and those lines are indented
    further than the label. Anything indented no further starts new text and
    ends the example.

    The two sides come in either order. Rule 3.6 prints the STE sentence first
    and the sentence it refuses below it, and the rest of the standard does the
    opposite. So a pair stays open until a line arrives that is not part of it.
    Assuming one order joined the passive half of one example to the active half
    of the next, and the result read like something the standard said.
    """
    examples: list[dict] = []
    pending: dict[str, str] = {}
    side: str | None = None
    indent = 0
    parts: list[str] = []

    def flush() -> None:
        """Close the open pair.

        A refused sentence with nothing to replace it is commentary, so only a
        pair that gives the STE sentence becomes an example.
        """
        right = pending.get("right", "")
        if right and not COUNTER_EXAMPLE.search(right):
            examples.append({"non_ste": pending.get("wrong", ""), "ste": right})
        pending.clear()

    def close() -> None:
        """Put the side that was being read into the open pair."""
        nonlocal side
        if side is None:
            return
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if text:
            if side in pending:
                flush()
            pending[side] = text
        side = None

    for line in body.split("\n"):
        wrong = EXAMPLE_WRONG.match(line)
        head = wrong or EXAMPLE_RIGHT.match(line)
        if head:
            close()
            side = "wrong" if wrong else "right"
            indent = len(head.group(1))
            parts = [head.group(3).strip()]
            continue
        if side and line.strip() and len(line) - len(line.lstrip()) > indent:
            if not EXAMPLE_ASIDE.match(line):
                parts.append(line.strip())
            continue
        # A blank line, or text back at the margin. The example is over.
        close()
        flush()
    close()
    flush()
    return examples


def build_rules(pages: list[str]) -> dict[str, dict]:
    """Turn the rule text into one record for each rule and recommendation.

    A record holds only what ASD wrote. The tier and the linter check belong to
    this skill, live in ste_policy.py, and are joined to the record when it is
    printed.
    """
    records: dict[str, dict] = {}
    for section, entries in sorted(rule_blocks(pages).items()):
        for rule_id, body in entries:
            recommendations: list[tuple[str, str, str]] = []
            if section == "9":
                body, recommendations = split_recommendations(body)
            records[rule_id] = {
                "id": rule_id,
                "kind": "rule",
                "section": section,
                "statement": statement_of(body),
                "text": body,
                "examples": parse_examples(body),
            }
            for gr_id, title, gr_body in recommendations:
                records[gr_id] = {
                    "id": gr_id,
                    "kind": "recommendation",
                    "section": section,
                    "title": title,
                    "statement": statement_of(gr_body),
                    "text": gr_body,
                    "examples": parse_examples(gr_body),
                }
    return records


# A target in the subject index is a rule id ("3.6"), a whole section ("2#"), a
# range ("1.5 thru 1.13"), or a recommendation ("9 - GR-5"). "1,5" also occurs,
# where the typesetter used a comma for the point.
TARGET = re.compile(r"GR-\d+|\d+\.\d+|\d+,\d+|\d+\s*#|\bthru\b", re.I)


def resolve_targets(raw: str, known: set[str]) -> list[str]:
    """Turn one index entry's targets into rule ids this build actually has.

    A target that resolves to nothing is dropped rather than kept as text. The
    raw entry is stored beside the ids, so an entry that points at the
    introduction of the dictionary instead of a rule still says so.
    """
    found: list[str] = []
    ranged = False
    for token in TARGET.findall(raw):
        text = token.strip().upper()
        if text == "THRU":
            ranged = True
            continue
        if text.startswith("GR-"):
            ids = [text]
        elif text.endswith("#"):
            section = text[:-1].strip()
            ids = [r for r in known if r.split(".")[0] == section and "." in r]
        else:
            ids = [text.replace(",", ".")]
        ids = sorted((rule for rule in ids if rule in known), key=ste_data.rule_sort_key)
        if ranged and found and ids:
            ids = [
                rule for rule in known
                if ste_data.rule_sort_key(found[-1])
                <= ste_data.rule_sort_key(rule)
                <= ste_data.rule_sort_key(ids[0])
            ]
            ranged = False
        for rule in ids:
            if rule not in found:
                found.append(rule)
    return sorted(found, key=ste_data.rule_sort_key)


def parse_subject_index(pages: list[str]) -> list[tuple[str, str]]:
    """Extract the standard's own subject-to-rule index."""
    found: list[tuple[str, str]] = []
    for page in pages:
        if not PAGE_INDEX.search(page):
            continue
        for line in page.split("\n"):
            if FURNITURE.match(line) or not line.strip():
                continue
            # "Active voice                     3.6"
            match = re.match(r"^(?P<subject>\S.*?\S)\s{2,}(?P<rules>[0-9A-Za-z][^\n]*)$", line)
            if not match:
                continue
            subject = match.group("subject").strip()
            targets = match.group("rules").strip()
            if subject.lower() in {"subject", "rule"} or not targets:
                continue
            if not re.search(r"\d|Part|General|introduction", targets):
                continue
            found.append((subject, targets))
    return found


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def statement_of(rule_text: str) -> str:
    """Take the rule statement, which is the first sentence of its block."""
    flat = re.sub(r"\s+", " ", rule_text).strip()
    match = re.match(r"^(.{0,300}?[.:])(\s|$)", flat)
    return (match.group(1) if match else flat[:200]).strip()


def write_rules(out: Path, meta: dict, records: dict[str, dict],
                index: list[tuple[str, str]]) -> None:
    """Write data/ste-rules.json.

    This was nine markdown files and an index, which nothing read: the linter
    reached one rule by regular expression over a heading, and the subject index
    was build output that no code opened. Records make both a lookup.

    The tier and the linter check are not written here. They are ours, they live
    in ste_policy.py, and joining them in at build time is what made a tier go
    stale in data/ until the next rebuild.
    """
    known = set(records)
    subjects = {
        subject: {"rules": resolve_targets(targets, known), "raw": targets}
        for subject, targets in index
    }
    rules = {
        rule_id: records[rule_id]
        for rule_id in sorted(records, key=ste_data.rule_sort_key)
    }
    document = {
        "meta": meta,
        "sections": {
            section: name.replace("-", " ")
            for section, name in sorted(SECTION_NAMES.items())
        },
        "rules": rules,
        "subjects": dict(sorted(subjects.items())),
    }
    (out / "ste-rules.json").write_text(
        json.dumps(document, indent=1, ensure_ascii=False), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate(approved: dict, alternatives: dict, records: dict, index: list) -> list[str]:
    problems = []
    rules = {rule for rule, r in records.items() if r["kind"] == "rule"}
    recommendations = {rule for rule, r in records.items() if r["kind"] == "recommendation"}
    counts = {
        "approved": len(approved),
        "unapproved": len(alternatives),
        "rules": len(rules),
        "recommendations": len(recommendations),
        "examples": sum(len(r["examples"]) for r in records.values()),
        "index_subjects": len(index),
    }
    for key, minimum in MINIMUMS.items():
        if counts[key] < minimum:
            problems.append(
                f"only {counts[key]} {key} extracted, expected at least {minimum}"
            )

    every_form = set()
    for entry in approved.values():
        every_form.update(entry["forms"])
    for word in SPOT_CHECKS_APPROVED:
        if word not in every_form:
            problems.append(f"approved word missing: {word!r}")

    for word, expected in SPOT_CHECKS_ALTERNATIVES.items():
        entry = alternatives.get(word)
        if entry is None:
            problems.append(f"unapproved word missing: {word!r}")
        elif not any(r.upper().startswith(expected) for r in entry["replacements"]):
            problems.append(
                f"{word!r} should suggest {expected!r}, got {entry['replacements']}"
            )

    missing_sections = sorted(
        set(SECTION_NAMES) - {records[rule]["section"] for rule in rules}
    )
    if missing_sections:
        problems.append(f"no rules found for section(s) {', '.join(missing_sections)}")

    # Count 53 and stop, and a rule that arrives under the wrong id still
    # passes. The two sets have to be the same set. A rule the extractor finds
    # and the table does not name has no tier, and a rule the table names and
    # the extractor loses cannot be read at all.
    declared = {rule for rule in ste_policy.RULES if rule not in ste_policy.HOUSE_RULES}
    for rule in sorted(declared - rules, key=ste_data.rule_sort_key):
        problems.append(f"rule {rule} is in the rule table and was not extracted")
    for rule in sorted(rules - declared, key=ste_data.rule_sort_key):
        problems.append(f"rule {rule} was extracted and is not in the rule table")

    # The examples are the part an agent acts on, and their layout is the most
    # fragile thing here. One rule per shape that the standard prints.
    for rule in SPOT_CHECKS_EXAMPLES:
        if not records.get(rule, {}).get("examples"):
            problems.append(f"no examples extracted for rule {rule}")

    unresolved = [
        subject for subject, targets in index
        if not resolve_targets(targets, set(records))
        and re.search(r"\d\.\d|GR-|#", targets)
    ]
    if unresolved:
        problems.append(
            f"{len(unresolved)} index subject(s) name a rule that did not "
            f"resolve, first: {unresolved[0]!r}"
        )
    return problems


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the local STE data files from your copy of ASD-STE100.",
    )
    parser.add_argument("--pdf", required=True, type=Path, help="path to your ASD-STE100 PDF")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    parser.add_argument(
        "--force", action="store_true", help="write the data even if validation fails"
    )
    args = parser.parse_args()

    try:
        text = extract_text(args.pdf)
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    pages = text.split("\f")
    print(f"read {len(pages)} pages from {args.pdf.name}")

    approved, alternatives = parse_dictionary(pages)
    records = build_rules(pages)
    index = parse_subject_index(pages)

    approved_forms = {form for entry in approved.values() for form in entry["forms"]}

    # Expand unapproved words to their inflected forms. An approved word always
    # wins, so a generated form never turns a permitted word into a violation.
    # Each form maps to its lemma, and the lemma holds the replacements: storing
    # the replacements against every form instead made the file three times
    # larger and gave the same answer.
    expanded: dict[str, str] = {}
    for lemma, entry in alternatives.items():
        for form in ste_data.inflect(lemma, entry["pos"]):
            if form not in approved_forms:
                expanded.setdefault(form, lemma)

    # The house lists are not written here. They belong to us, not to ASD, and
    # the linter merges them at load time so that editing them does not need a
    # rebuild.
    rule_count = sum(1 for record in records.values() if record["kind"] == "rule")
    example_count = sum(len(record["examples"]) for record in records.values())
    print(
        f"approved {len(approved)} lemmas / {len(approved_forms)} forms · "
        f"unapproved {len(alternatives)} lemmas / {len(expanded)} forms · "
        f"rules {rule_count} / {len(records) - rule_count} recommendations / "
        f"{example_count} examples · "
        f"index {len(index)} subjects"
    )

    problems = validate(approved, alternatives, records, index)
    if problems:
        print("\nextraction failed its checks:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        if not args.force:
            print(
                "\nNothing was written. A partial dictionary makes strict mode lie.\n"
                "If you are adapting this to a different issue of the standard, "
                "re-run with --force once you have checked the output by hand.",
                file=sys.stderr,
            )
            return 1
        print("--force given, writing anyway", file=sys.stderr)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    # meta first, so `head ste-dictionary.json` tells you which PDF built this
    # and whether it passed its checks.
    dictionary = {
        "meta": {
            "built_by": BUILDER,
            "version": ste_data.DICTIONARY_VERSION,
            "source_file": args.pdf.name,
            "source_pages": len(pages),
            "validated": not problems,
            "counts": {
                "approved_lemmas": len(approved),
                "approved_forms": len(approved_forms),
                "unapproved_lemmas": len(alternatives),
                "unapproved_forms": len(expanded),
            },
            "note": (
                "Extracted from ASD-STE100, which ASD holds the copyright to. "
                "Do not commit this file or share it."
            ),
        },
        "approved": {"lemmas": approved, "forms": sorted(approved_forms)},
        "alternatives": {"lemmas": alternatives, "forms": expanded},
    }
    (out / "ste-dictionary.json").write_text(
        json.dumps(dictionary, indent=1), encoding="utf-8"
    )
    write_rules(
        out,
        {
            "built_by": BUILDER,
            "version": ste_data.RULES_VERSION,
            "source_file": args.pdf.name,
            "source_pages": len(pages),
            "validated": not problems,
            "counts": {
                "rules": rule_count,
                "recommendations": len(records) - rule_count,
                "examples": example_count,
                "index_subjects": len(index),
            },
            "note": (
                "Extracted from ASD-STE100, which ASD holds the copyright to. "
                "Do not commit this file or share it."
            ),
        },
        records,
        index,
    )

    print(f"\nwrote {out / 'ste-dictionary.json'} and {out / 'ste-rules.json'}")
    print("This directory is not committed. Rebuild it after you clone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
