#!/usr/bin/env python3
"""Check prose against ASD-STE100 Simplified Technical English.

    ste-lint.py --mode ste-strict  README.md
    ste-lint.py --mode ste-general --format json docs/*.md
    cat draft.md | ste-lint.py --mode ste-general -

Exit codes, which are the point of this script:

    0   clean
    1   an enforced rule was broken
    2   only flagged rules were raised
    3   the check could not run (no dictionary, unreadable file)

Exit 3 never degrades to 0. A linter that passes because its dictionary is
missing is worse than no linter, because the gate still looks green.

Run build-dictionary.py first. This repository ships no content from the
standard, so the data directory starts empty.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ste_data  # noqa: E402  (needs the path above)

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
DATA = SKILL_DIR / "data"
ASSETS = SKILL_DIR / "assets"
MARKER = ".ste-writing.json"

EXIT_CLEAN, EXIT_ENFORCED, EXIT_FLAGGED, EXIT_ERROR = 0, 1, 2, 3

# Verbs whose past participle is not "-ed", for the passive-voice and auxiliary
# checks. Ours, not from the standard.
IRREGULAR_PARTICIPLES = {
    "been", "begun", "broken", "brought", "built", "bought", "caught", "chosen",
    "come", "cut", "done", "drawn", "driven", "eaten", "fallen", "felt", "found",
    "given", "gone", "got", "gotten", "grown", "held", "hidden", "hit", "kept",
    "known", "laid", "left", "let", "lost", "made", "meant", "met", "paid", "put",
    "read", "run", "said", "seen", "sent", "set", "shown", "shut", "sold",
    "spent", "split", "spread", "stood", "taken", "taught", "thrown", "told",
    "understood", "written",
}

BE = r"(?:am|is|are|was|were|be|been|being)"
MODAL = r"(?:can|could|may|might|must|shall|should|will|would)"
PARTICIPLE = rf"(?:\w+ed|{'|'.join(sorted(IRREGULAR_PARTICIPLES))})"

# "'s" is left out of the general case on purpose: "the project's glossary" is a
# possessive, which rule 4.2 permits. Only the "'s" forms that really are
# contractions are listed.
CONTRACTION = re.compile(
    r"\b[A-Za-z]+['’](?:t|re|ve|ll|d|m)\b"
    r"|\b(?:it|that|there|here|what|let|he|she|who|where|how|one)['’]s\b",
    re.I,
)
PASSIVE = re.compile(rf"\b{BE}\s+(?:\w+ly\s+)?{PARTICIPLE}\b", re.I)
ING_MAIN_VERB = re.compile(rf"\b{BE}\s+\w+ing\b", re.I)
# A stacked auxiliary needs a participle after it. "must be present" is a modal
# and an adjective, which is a simple construction and not what rule 3.4 is about.
AUXILIARY_STACK = re.compile(
    rf"\b(?:(?:has|have|had)\s+been\s+{PARTICIPLE}"
    rf"|{MODAL}\s+have\s+(?:been\s+)?{PARTICIPLE}"
    rf"|{MODAL}\s+be\s+being"
    rf"|{BE}\s+being\s+{PARTICIPLE})\b",
    re.I,
)
NOMINALIZATION = re.compile(
    r"\b(?:perform(?:s|ed)?|conduct(?:s|ed)?|carry\s+out|carries\s+out"
    r"|make\s+use\s+of|makes\s+use\s+of)\b"
    r"|\b\w{4,}(?:tion|ment|ance|ence)\s+of\b",
    re.I,
)
WORD = re.compile(r"[A-Za-z][A-Za-z'’]*(?:-[A-Za-z'’]+)*")


class LintError(Exception):
    """The check cannot run. Always exit 3, never 0."""


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

@dataclass
class Finding:
    rule: str
    check: str
    line: int
    column: int
    text: str
    message: str
    tier: str
    suggestion: str = ""

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "check": self.check,
            "tier": self.tier,
            "line": self.line,
            "column": self.column,
            "text": self.text,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class Document:
    """A file with its prose isolated from everything the rules do not cover."""

    path: str
    raw: str
    prose: str  # same length as raw, with masked regions replaced by spaces
    line_starts: list[int] = field(default_factory=list)

    def position(self, offset: int) -> tuple[int, int]:
        low, high = 0, len(self.line_starts) - 1
        while low < high:
            middle = (low + high + 1) // 2
            if self.line_starts[middle] <= offset:
                low = middle
            else:
                high = middle - 1
        return low + 1, offset - self.line_starts[low] + 1


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_json(path: Path, what: str) -> dict:
    if not path.is_file():
        raise LintError(
            f"{what} is missing ({path}).\n"
            "Build it from your own copy of the standard:\n"
            f"  python3 {HERE / 'build-dictionary.py'} "
            "--pdf /path/to/ASD-STE100_ISSUE9.pdf"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LintError(f"{what} is not valid JSON ({path}): {error}") from error


def find_config(start: Path) -> Path | None:
    """Walk up from a path to find the repository marker file."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for directory in [current, *current.parents]:
        candidate = directory / MARKER
        if candidate.is_file():
            return candidate
    return None


def load_config(explicit: Path | None, target: Path) -> dict:
    path = explicit or find_config(target)
    if path is None:
        return {}
    config = json.loads(path.read_text(encoding="utf-8"))
    config["_path"] = str(path)
    glossary_file = config.get("glossary_file")
    if glossary_file:
        words = (path.parent / glossary_file).read_text(encoding="utf-8").split()
        config.setdefault("glossary", []).extend(words)
    return config


# --------------------------------------------------------------------------
# Markdown masking
# --------------------------------------------------------------------------

def mask(raw: str) -> str:
    """Blank out everything the writing rules do not apply to.

    Masked regions become spaces of the same length, so every offset in the
    result still points at the same character of the original file. That is what
    lets a finding report a true line and column.

    Code, identifiers, and command syntax are out of scope by design. STE governs
    prose, and flagging a variable name would be noise.
    """
    masked = list(raw)

    def blank(start: int, end: int) -> None:
        for i in range(start, min(end, len(masked))):
            if masked[i] != "\n":
                masked[i] = " "

    regions = [
        re.compile(r"\A---\n.*?\n---\n", re.S),              # YAML front matter
        re.compile(r"```.*?```", re.S),                       # fenced code
        re.compile(r"~~~.*?~~~", re.S),                       # fenced code
        re.compile(r"`[^`\n]*`"),                             # inline code
        re.compile(r"^(?: {4,}|\t)\S.*$", re.M),              # indented code
        re.compile(r"<[^>\n]+>"),                             # HTML, autolinks
        re.compile(r"\]\([^)\n]*\)"),                         # link targets
        re.compile(r"https?://\S+"),                          # bare URLs
        re.compile(r"^\s*\[[^\]]+\]:\s*\S+.*$", re.M),        # link definitions
        re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+.*$", re.M),  # table rules
    ]
    for pattern in regions:
        for match in pattern.finditer(raw):
            blank(match.start(), match.end())

    text = "".join(masked)

    # Heading markers, list bullets, quote markers, and table pipes are
    # structure, not words. Blank the marker and keep the prose after it.
    markers = [
        re.compile(r"^\s*#{1,6}\s", re.M),
        re.compile(r"^\s*[-*+]\s", re.M),
        re.compile(r"^\s*\d+[.)]\s", re.M),
        re.compile(r"^\s*>\s?", re.M),
        re.compile(r"\|"),
    ]
    for pattern in markers:
        for match in pattern.finditer(text):
            blank(match.start(), match.end())

    return "".join(masked)


# --------------------------------------------------------------------------
# Sentences and STE word counting
# --------------------------------------------------------------------------

def split_sentences(block: str, offset: int = 0) -> list[tuple[str, int]]:
    """Split one block into sentences, keeping each one's offset in the file.

    A colon ends a sentence when it introduces a vertical list (rule 8.4), so it
    counts as a terminator with the period, question mark, and exclamation mark.

    The block arrives with its soft line breaks already turned into spaces. A
    sentence that wraps over two lines is one sentence, and splitting on the line
    break instead would count it twice and hide its true length.
    """
    sentences: list[tuple[str, int]] = []
    for part in re.finditer(r"[^.!?:]+[.!?:]*", block):
        text = part.group()
        if text.strip():
            lead = len(text) - len(text.lstrip())
            sentences.append((text.strip(), offset + part.start() + lead))
    return sentences


def count_words(text: str) -> int:
    """Count words the way rules 8.5 thru 8.7 require.

    Parenthetical text, quoted text, and a number with its unit each count as one
    word. A hyphenated word counts as one word, which falls out of splitting on
    whitespace. Naive counting inflates every sentence, so the 20 and 25 word
    limits would report lengths nobody can reproduce by hand.
    """
    text = re.sub(r"\([^)]*\)", " X ", text)                      # 8.5
    text = re.sub(r"[\"“][^\"”]*[\"”]", " X ", text)              # 8.6, quoted text
    text = re.sub(r"\b\d[\d,.]*\s*[A-Za-z%°/]+\b", " X ", text)   # 8.6, number + unit
    text = re.sub(r"\b\d[\d,.]*\b", " X ", text)                  # 8.6, numbers
    return sum(1 for token in text.split() if re.search(r"[A-Za-z0-9]", token))


NOT_A_PARAGRAPH = re.compile(
    r"^\s*(?:[-*+]\s|\d+[.)]\s|\||#{1,6}\s|>|```|~~~|\[[^\]]+\]:)"
)


def blocks(raw: str) -> list[tuple[int, int, bool]]:
    """Split the file into blocks of (start, end, is_paragraph).

    A run of consecutive plain lines is one paragraph, because markdown wraps a
    paragraph over as many lines as it likes. Every other non-blank line — a
    heading, a list item, a table row — is a block on its own.

    The distinction matters twice. Rule 6.6 limits a paragraph to six sentences,
    and a vertical list is not a paragraph: the standard covers lists in rules
    4.3 and 8.4, so counting a seven-item list as a seven-sentence paragraph is
    noise. And a sentence must be measured across the lines it wraps over, or a
    30-word sentence split over two lines never reaches the limit.
    """
    found: list[tuple[int, int, bool]] = []
    start: int | None = None
    end = 0
    offset = 0
    for line in raw.splitlines(keepends=True):
        length = len(line)
        if not line.strip():
            other = None
        elif NOT_A_PARAGRAPH.match(line):
            other = (offset, offset + length)
        else:
            other = None
            if start is None:
                start = offset
            end = offset + length
            offset += length
            continue
        if start is not None:
            found.append((start, end, True))
            start = None
        if other:
            found.append((*other, False))
        offset += length
    if start is not None:
        found.append((start, end, True))
    return found


def is_instruction(text: str, base_verbs: set[str]) -> bool:
    """True when a sentence reads as a command, which caps it at 20 words.

    Rule 5.1 caps an instruction at 20 words and rule 6.3 caps descriptive text
    at 25, so the two have to be told apart. This checks whether the sentence
    opens with a verb in its base form. "Install the pump" is an instruction.
    "The pump is installed" is not.
    """
    match = WORD.search(text)
    if not match or text[: match.start()].strip():
        return False
    return match.group().lower() in base_verbs


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------

class Linter:
    def __init__(self, mode: str, data: dict, config: dict) -> None:
        self.mode = mode
        self.tiers = data["tiers"]
        self.config = config

        vocabulary = data["vocabulary"]
        self.approved_forms: set[str] = vocabulary.approved_forms
        self.approved_lemmas: dict = vocabulary.approved_lemmas
        # Every non-approved word, used by ste-strict to suggest a replacement
        # once the allowlist has already rejected the word.
        self.alternative_forms: dict[str, str] = vocabulary.alternative_forms
        # The subset ste-general fails on, because it does not run the allowlist.
        self.slop_forms: dict[str, str] = vocabulary.slop_forms
        self.phrasal: list[str] = vocabulary.phrasal
        self.replacements = vocabulary.replacements
        self.marketing: set[str] = set(data["house"]["marketing"])
        self.hedges: list[str] = data["house"]["hedges"]
        self.spellings: dict = data["spelling"]["spellings"]

        self.glossary = {word.lower() for word in config.get("glossary", [])}
        self.synonyms = {
            variant.lower(): canonical
            for canonical, variants in config.get("one_name_for_one_thing", {}).items()
            for variant in variants
        }
        self.base_verbs = {
            lemma for lemma, entry in self.approved_lemmas.items() if "v" in entry["pos"]
        }
        self.nouns = {
            lemma
            for lemma, entry in self.approved_lemmas.items()
            if "n" in entry["pos"] or "TN" in entry["pos"]
        } | self.glossary

    # -- helpers -----------------------------------------------------------

    def active(self, rule: str) -> bool:
        """True when a rule can produce a finding in the current mode.

        A flagged rule always reports, because it never fails the run. An
        enforced rule reports only in the modes that enforce it.
        """
        meta = self.tiers.get(rule, {})
        if meta.get("tier") == "flagged":
            return True
        return self.mode in meta.get("modes", [])

    def make(self, rule: str, check: str, document: Document, offset: int,
             text: str, message: str, suggestion: str = "") -> Finding:
        line, column = document.position(offset)
        return Finding(
            rule=rule,
            check=check,
            line=line,
            column=column,
            text=re.sub(r"\s+", " ", text).strip(),
            message=message,
            tier=self.tiers.get(rule, {}).get("tier", "flagged"),
            suggestion=suggestion,
        )

    def in_glossary(self, lower: str) -> bool:
        """True when the project declared this word, in any regular form.

        The glossary holds base forms, so the plural and the possessive of a
        declared noun count as declared too.
        """
        if lower in self.glossary:
            return True
        for suffix in ("s", "es", "'s", "’s"):
            if lower.endswith(suffix) and lower[: -len(suffix)] in self.glossary:
                return True
        return lower.endswith("ies") and lower[:-3] + "y" in self.glossary

    def known_word(self, word: str) -> bool:
        lower = word.lower()
        if lower in self.approved_forms or self.in_glossary(lower):
            return True
        # A hyphenated compound is approved when both halves are.
        if "-" in lower:
            parts = [part for part in lower.split("-") if part]
            return bool(parts) and all(
                part in self.approved_forms or self.in_glossary(part) for part in parts
            )
        return False

    def known_lemma(self, word: str) -> bool:
        """True when an approved word exists that this looks like a form of."""
        for cut in (1, 2, 3):
            if len(word) > cut + 2 and word[:-cut] in self.approved_lemmas:
                return True
        return word.rstrip("s") in self.approved_lemmas

    def replacement_hint(self, lemma: str | None) -> str:
        options = ", ".join(self.replacements(lemma)[:3]) if lemma else ""
        return f"The standard suggests {options}." if options else ""

    # -- words -------------------------------------------------------------

    def check_words(self, document: Document) -> list[Finding]:
        findings: list[Finding] = []
        for match in WORD.finditer(document.prose):
            word = match.group()
            lower = word.lower()
            offset = match.start()

            # An acronym or an identifier is a technical noun, not prose.
            if word.isupper() and len(word) > 1:
                continue

            if self.active("1.14") and lower in self.spellings:
                findings.append(self.make(
                    "1.14", "british_spelling", document, offset, word,
                    "British spelling.",
                    f"Write “{self.spellings[lower]}”.",
                ))
                continue

            if self.active("H.1") and lower in self.marketing:
                findings.append(self.make(
                    "H.1", "marketing_word", document, offset, word,
                    "Marketing adjective. It tells the reader nothing.",
                    "Delete it, or give the measurement you mean.",
                ))
                continue

            if self.active("1.11") and lower in self.synonyms:
                findings.append(self.make(
                    "1.11", "inconsistent_term", document, offset, word,
                    "Two names for one thing.",
                    f"Write “{self.synonyms[lower]}”.",
                ))
                continue

            # A word in the project glossary is a technical noun that this
            # project decided on, per rules 1.6 and 1.8. It answers every
            # question about whether the dictionary holds the word, so the
            # checks below have nothing left to say about it.
            if self.in_glossary(lower):
                continue

            alternative = self.alternative_forms.get(lower)
            slop = self.slop_forms.get(lower)

            if self.active("H.2") and slop:
                findings.append(self.make(
                    "H.2", "unapproved_alternative", document, offset, word,
                    f"“{slop}” is not an approved word.",
                    self.replacement_hint(slop),
                ))
                continue

            if not self.active("1.1") or self.known_word(word):
                continue

            # An approved lemma in an unapproved form is rule 1.4, not 1.1. The
            # word is right and the form is wrong, which is a different fix and
            # a different page of the standard.
            if self.known_lemma(lower):
                if self.active("1.4"):
                    findings.append(self.make(
                        "1.4", "unapproved_form", document, offset, word,
                        f"“{word}” is not an approved form of this word.",
                        "Use a form that the dictionary gives.",
                    ))
                continue

            findings.append(self.make(
                "1.1", "unapproved_word", document, offset, word,
                f"“{word}” is not in the STE dictionary.",
                self.replacement_hint(alternative)
                or f"Replace it, or add it to the glossary in {MARKER} "
                   "if it is a technical noun.",
            ))
        return findings

    # -- patterns ----------------------------------------------------------

    def check_patterns(self, document: Document) -> list[Finding]:
        findings: list[Finding] = []
        simple = [
            ("8.1", "semicolon", re.compile(r";"),
             "Semicolon. STE does not permit it.",
             "Write two sentences."),
            ("4.2", "contraction", CONTRACTION,
             "Contraction.",
             "Write the words in full."),
            ("3.6", "passive_voice", PASSIVE,
             "Passive voice.",
             "Name the actor and put it first."),
            ("3.5", "ing_main_verb", ING_MAIN_VERB,
             "An “-ing” form used as the main verb.",
             "Use the simple present or the simple past."),
            ("3.4", "auxiliary_stack", AUXILIARY_STACK,
             "Stacked auxiliary verbs.",
             "Use a simple tense."),
            ("3.7", "nominalization", NOMINALIZATION,
             "An action written as a noun.",
             "Use the verb: “analyze the log”, not “perform an analysis of the log”."),
        ]
        for rule, check, pattern, message, suggestion in simple:
            if not self.active(rule):
                continue
            for match in pattern.finditer(document.prose):
                findings.append(self.make(
                    rule, check, document, match.start(),
                    match.group(), message, suggestion,
                ))

        phrases = [
            ("9.3", "phrasal_verb", self.phrasal,
             "is a phrasal verb.", "Use one plain verb."),
            ("H.3", "hedge", self.hedges,
             "is a hedging preamble.", "Delete it and state the point."),
        ]
        for rule, check, vocabulary, message, suggestion in phrases:
            if not self.active(rule):
                continue
            for phrase in vocabulary:
                pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.I)
                for match in pattern.finditer(document.prose):
                    findings.append(self.make(
                        rule, check, document, match.start(), match.group(),
                        f"“{phrase}” {message}", suggestion,
                    ))
        return findings

    # -- structure ---------------------------------------------------------

    def check_structure(self, document: Document) -> list[Finding]:
        findings: list[Finding] = []
        for start, end, is_paragraph in blocks(document.raw):
            # Newlines become spaces so a wrapped sentence reads as one
            # sentence. The substitution is one character for one character, so
            # every offset still points where it did.
            block = document.prose[start:end].replace("\n", " ")
            sentences = split_sentences(block, start)

            for text, offset in sentences:
                words = count_words(text)
                instruction = is_instruction(text, self.base_verbs)
                rule, limit = ("5.1", 20) if instruction else ("6.3", 25)
                if words <= limit or not self.active(rule):
                    continue
                kind = "instruction" if instruction else "descriptive sentence"
                findings.append(self.make(
                    rule,
                    "long_instruction" if instruction else "long_descriptive",
                    document, offset, text[:80],
                    f"{words}-word {kind}. The limit is {limit}.",
                    "Split it into two sentences.",
                ))

            if is_paragraph and len(sentences) > 6 and self.active("6.6"):
                findings.append(self.make(
                    "6.6", "long_paragraph", document, start, block.strip()[:80],
                    f"{len(sentences)}-sentence paragraph. The limit is six.",
                    "Split it into two paragraphs.",
                ))

        if self.active("2.1"):
            findings.extend(self.check_noun_clusters(document))
        return findings

    def check_noun_clusters(self, document: Document) -> list[Finding]:
        """Rule 2.1, a multi-word noun of more than three words.

        Without a part-of-speech tagger this reports only a run of four or more
        words that the dictionary itself calls nouns, which keeps it quiet enough
        to be worth reading. It warns. It never fails a run.
        """
        findings: list[Finding] = []
        run: list[re.Match] = []

        def close() -> None:
            if len(run) >= 4:
                phrase = document.prose[run[0].start():run[-1].end()]
                findings.append(self.make(
                    "2.1", "long_noun_cluster", document, run[0].start(), phrase,
                    f"{len(run)}-word noun cluster. The limit is three.",
                    "Write it in full, then give a shorter form.",
                ))

        for match in WORD.finditer(document.prose):
            adjacent = bool(run) and match.start() - run[-1].end() <= 1
            if match.group().lower() in self.nouns and (adjacent or not run):
                run.append(match)
                continue
            close()
            run = [match] if match.group().lower() in self.nouns else []
        close()
        return findings

    # -- entry point -------------------------------------------------------

    def lint(self, document: Document) -> list[Finding]:
        findings = (
            self.check_words(document)
            + self.check_patterns(document)
            + self.check_structure(document)
        )
        findings.sort(key=lambda finding: (finding.line, finding.column, finding.rule))
        return findings


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def totals(results: dict[str, list[Finding]]) -> tuple[int, int]:
    every = [finding for findings in results.values() for finding in findings]
    enforced = sum(1 for finding in every if finding.tier == "enforced")
    return enforced, len(every) - enforced


def describe(modes: dict[str, str]) -> str:
    used = sorted(set(modes.values()))
    return used[0] if len(used) == 1 else ", ".join(used)


def report_text(results: dict[str, list[Finding]], modes: dict[str, str]) -> str:
    lines: list[str] = []
    for path, findings in results.items():
        if not findings:
            continue
        lines.append(f"{path}  [{modes.get(path, '')}]")
        for finding in findings:
            marker = "error" if finding.tier == "enforced" else "warn "
            lines.append(
                f"  {marker} {path}:{finding.line}:{finding.column}"
                f"  rule {finding.rule}  {finding.message}"
            )
            lines.append(f"        “{finding.text}”")
            if finding.suggestion:
                lines.append(f"        -> {finding.suggestion}")
        lines.append("")

    enforced, flagged = totals(results)
    if not enforced and not flagged:
        return f"clean ({describe(modes)})\n"
    lines.append(f"{enforced} enforced, {flagged} flagged ({describe(modes)})")
    if enforced:
        lines.append("Find the rule id in data/rule-index.md, then read only that rule.")
    return "\n".join(lines) + "\n"


def report_json(results: dict[str, list[Finding]], modes: dict[str, str]) -> str:
    enforced, flagged = totals(results)
    return json.dumps(
        {
            "mode": describe(modes),
            "modes": modes,
            "enforced": enforced,
            "flagged": flagged,
            "files": {
                path: [finding.as_dict() for finding in findings]
                for path, findings in results.items()
            },
        },
        indent=1,
        ensure_ascii=False,
    ) + "\n"


# --------------------------------------------------------------------------

def build_document(path: str, raw: str) -> Document:
    starts = [0] + [match.end() for match in re.finditer(r"\n", raw)]
    return Document(path=path, raw=raw, prose=mask(raw), line_starts=starts)


def matches(path: Path, patterns: list[str]) -> bool:
    text = path.as_posix()
    return any(
        fnmatch.fnmatch(text, pattern)
        or fnmatch.fnmatch(path.name, pattern)
        or fnmatch.fnmatch(text, f"*/{pattern.lstrip('/')}")
        for pattern in patterns
    )


def excluded(path: Path, config: dict) -> bool:
    return matches(path, config.get("exclude", []))


def mode_for(path: Path, config: dict, override: str | None) -> str:
    """Decide the mode for one file.

    The mode belongs to the text, not to the repository. A runbook is strict
    even when the repository around it is general, so `strict_paths` in the
    marker file names the paths that get `ste-strict`. Without this, the hook
    would gate every file at the repository mode, and strict would go back to
    being advice for exactly the safety text it exists for.

    An explicit --mode wins, so a person checking one file by hand still can.
    """
    if override:
        return override
    if matches(path, config.get("strict_paths", [])):
        return "ste-strict"
    return config.get("mode") or "ste-general"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check prose against ASD-STE100 Simplified Technical English.",
    )
    parser.add_argument("files", nargs="*", help="files to check, or - for standard input")
    parser.add_argument("--mode", choices=["ste-strict", "ste-general"], default=None)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--config", type=Path, default=None, help=f"path to {MARKER}")
    parser.add_argument(
        "--fail-on-flagged",
        action="store_true",
        help="exit 1 on flagged findings too, not only enforced ones",
    )
    args = parser.parse_args()
    targets = args.files or ["-"]

    try:
        anchor = Path(targets[0]) if targets[0] != "-" else Path.cwd()
        config = load_config(args.config, anchor)
        house = load_json(ASSETS / "house-style.json", "The house style list")
        dictionary = load_json(DATA / "ste-dictionary.json", "The STE dictionary")
        data = {
            # The slop list and the phrasal verb list are derived here rather
            # than stored, so a change to house-style.json takes effect at once
            # instead of waiting for a rebuild.
            "vocabulary": ste_data.Vocabulary(dictionary, house),
            "house": house,
            "spelling": load_json(ASSETS / "spelling-en-us.json", "The spelling list"),
            "tiers": load_json(ASSETS / "rule-tiers.json", "The rule tier table"),
        }
        # One linter per mode, built on demand, so a run can mix a strict
        # runbook and a general README without loading the data twice.
        linters: dict[str, Linter] = {}

        def linter_for(mode: str) -> Linter:
            if mode not in linters:
                linters[mode] = Linter(mode, data, config)
            return linters[mode]

        results: dict[str, list[Finding]] = {}
        modes: dict[str, str] = {}
        for name in targets:
            if name == "-":
                mode = args.mode or config.get("mode") or "ste-general"
                modes["<stdin>"] = mode
                results["<stdin>"] = linter_for(mode).lint(
                    build_document("<stdin>", sys.stdin.read())
                )
                continue
            path = Path(name)
            if not path.is_file():
                raise LintError(f"no such file: {name}")
            if excluded(path, config):
                continue
            mode = mode_for(path, config, args.mode)
            modes[name] = mode
            results[name] = linter_for(mode).lint(
                build_document(name, path.read_text(encoding="utf-8", errors="replace"))
            )
    except (LintError, OSError, json.JSONDecodeError, KeyError) as error:
        print(f"ste-lint: {error}", file=sys.stderr)
        return EXIT_ERROR

    print(
        report_json(results, modes) if args.format == "json"
        else report_text(results, modes),
        end="",
    )

    enforced, flagged = totals(results)
    if enforced:
        return EXIT_ENFORCED
    if flagged:
        return EXIT_ENFORCED if args.fail_on_flagged else EXIT_FLAGGED
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
