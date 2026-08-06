#!/usr/bin/env python3
"""Check prose against ASD-STE100 Simplified Technical English.

    ste-lint.py README.md
    ste-lint.py --format json docs/*.md
    cat draft.md | ste-lint.py -
    ste-lint.py --init            write .ste-writing.json and switch this repo on

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
import ste_policy  # noqa: E402

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
DATA = SKILL_DIR / "data"

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
    short: str = ""
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
            # The rule in one line. Usually enough to fix the finding without
            # opening the rule at all.
            "short": self.short,
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


# The keys this file used before the sections existed, and where they went. A
# silently ignored glossary looks like the linter has gone mad, so say it.
RENAMED = {
    "glossary": "words.allow",
    "one_name_for_one_thing": "words.prefer",
    "glossary_file": "words.allow (inline)",
    "mode": "removed, there is one mode",
    "strict_paths": "removed, there is one mode",
}


class Config:
    """A project's marker file, in the shape the linter wants.

    The file mirrors ste-dictionary.json: `meta` first so that `head` on it says
    what wrote it, then named sections. `settings` is how the linter runs here,
    and `words` is the vocabulary this project decided on.
    """

    def __init__(self, raw: dict | None = None, path: Path | None = None) -> None:
        raw = raw or {}
        self.path = path
        self.meta: dict = raw.get("meta", {})
        settings: dict = raw.get("settings", {})
        words: dict = raw.get("words", {})

        self.locale: str = settings.get("locale", "")
        self.exclude: list[str] = settings.get("exclude", [])

        self.allow: set[str] = {w.lower() for w in words.get("allow", [])}
        self.deny: dict[str, str] = {
            w.lower(): replacement
            for w, replacement in words.get("deny", {}).items()
            if not w.startswith("_")
        }
        # Stored as name -> [variants]; the linter wants variant -> name.
        self.prefer: dict[str, str] = {
            variant.lower(): name
            for name, variants in words.get("prefer", {}).items()
            if not name.startswith("_")
            for variant in variants
        }

    def validate(self) -> None:
        both = sorted(self.allow & set(self.deny))
        if both:
            raise LintError(
                f"{self.path}: {', '.join(both)} is in both words.allow and "
                "words.deny. A word cannot be permitted and refused at once."
            )
        clash = sorted(self.allow & set(self.prefer))
        if clash:
            raise LintError(
                f"{self.path}: {', '.join(clash)} is in words.allow and is also a "
                "variant in words.prefer. Remove it from one of them."
            )


def load_config(explicit: Path | None, target: Path) -> Config:
    path = explicit or find_config(target)
    if path is None:
        return Config()
    raw = json.loads(path.read_text(encoding="utf-8"))

    stale = [key for key in RENAMED if key in raw]
    if stale:
        moved = "\n".join(f"  {key}  ->  {RENAMED[key]}" for key in stale)
        raise LintError(
            f"{path} uses key names from an older layout:\n{moved}\n"
            "Move them into the meta / settings / words sections. "
            f"Run: {HERE / 'ste-lint.py'} --init  in an empty directory to see "
            "the shape."
        )

    config = Config(raw, path)
    config.validate()
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
    def __init__(self, data: dict, config: dict) -> None:
        self.config = config

        vocabulary = data["vocabulary"]
        self.approved_forms: set[str] = vocabulary.approved_forms
        self.approved_lemmas: dict = vocabulary.approved_lemmas
        # The subset the linter fails on. See select_slop for why it is a subset.
        self.slop_forms: dict[str, str] = vocabulary.slop_forms
        self.phrasal: list[str] = vocabulary.phrasal
        self.replacements = vocabulary.replacements
        self.marketing: set[str] = set(ste_policy.MARKETING)
        self.hedges: tuple[str, ...] = ste_policy.HEDGES
        # Empty unless the project selected a locale. See localize.py.
        self.spellings: dict[str, str] = vocabulary.spellings
        self.locale: str = vocabulary.locale

        self.allow: set[str] = config.allow
        self.deny: dict[str, str] = config.deny
        self.prefer: dict[str, str] = config.prefer
        self.base_verbs = {
            lemma for lemma, entry in self.approved_lemmas.items() if "v" in entry["pos"]
        }
        # Rule 2.1 needs to know which words are nouns. The standard names 239 of
        # them, which is too few to see a cluster in software prose, so the
        # project's own words are the lever that makes the check work at all.
        self.nouns = {
            lemma
            for lemma, entry in self.approved_lemmas.items()
            if "n" in entry["pos"] or "TN" in entry["pos"]
        } | self.allow

    # -- helpers -----------------------------------------------------------

    def active(self, rule: str) -> bool:
        """True when a rule can produce a finding.

        There is one mode, so this is only about whether the rule has a check at
        all. Rule 1.14 is the exception: it needs a locale, and the skill ships
        no spelling list.
        """
        entry = ste_policy.RULES.get(rule)
        if entry is None or entry.check is None:
            return False
        if rule == "1.14":
            return bool(self.spellings)
        return True

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
            tier=entry.tier if (entry := ste_policy.RULES.get(rule)) else "flagged",
            short=entry.short if entry else "",
            suggestion=suggestion,
        )

    def declared(self, lower: str, vocabulary: set[str] | dict) -> str:
        """The declared word this one is a form of, or "".

        The sections hold base forms, so the plural and the possessive of a
        declared word count as declared too. Nothing else is stemmed: a project
        list is short enough to write out when a form is irregular.
        """
        if lower in vocabulary:
            return lower
        for suffix in ("s", "es", "'s", "’s"):
            if lower.endswith(suffix) and lower[: -len(suffix)] in vocabulary:
                return lower[: -len(suffix)]
        if lower.endswith("ies") and lower[:-3] + "y" in vocabulary:
            return lower[:-3] + "y"
        return ""

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

            # words.deny comes first, before anything can permit the word. A
            # project is allowed to refuse a word the standard approves, and
            # that decision has to beat every other check to mean anything.
            if self.active("H.4") and (denied := self.declared(lower, self.deny)):
                findings.append(self.make(
                    "H.4", "denied_word", document, offset, word,
                    f"“{denied}” is a word this project does not use.",
                    f"Write “{self.deny[denied]}”." if self.deny[denied]
                    else "Remove it, or write the plain word you mean.",
                ))
                continue

            if self.active("1.14") and lower in self.spellings:
                findings.append(self.make(
                    "1.14", "locale_spelling", document, offset, word,
                    f"Not the spelling this project uses ({self.locale}).",
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

            if self.active("1.11") and (variant := self.declared(lower, self.prefer)):
                findings.append(self.make(
                    "1.11", "inconsistent_term", document, offset, word,
                    "Two names for one thing.",
                    f"Write “{self.prefer[variant]}”.",
                ))
                continue

            # A word in words.allow is one this project decided on, per rules
            # 1.6 and 1.8. That answers the question the slop check is about to
            # ask, so there is nothing left to say about it.
            if self.declared(lower, self.allow):
                continue

            if self.active("H.2") and (slop := self.slop_forms.get(lower)):
                findings.append(self.make(
                    "H.2", "unapproved_alternative", document, offset, word,
                    f"“{slop}” is not an approved word.",
                    self.replacement_hint(slop)
                    or f"Replace it, or add it to the glossary in {MARKER} "
                       "if this project means it as a technical noun.",
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


def report_text(results: dict[str, list[Finding]]) -> str:
    lines: list[str] = []
    for path, findings in results.items():
        if not findings:
            continue
        lines.append(path)
        for finding in findings:
            marker = "error" if finding.tier == "enforced" else "warn "
            lines.append(
                f"  {marker} {path}:{finding.line}:{finding.column}"
                f"  rule {finding.rule}  {finding.message}"
            )
            lines.append(f"        “{finding.text}”")
            # A house rule's message already is its statement, so repeating the
            # short line there would be noise.
            if finding.short and finding.rule not in ste_policy.HOUSE_RULES:
                lines.append(f"        {finding.short}")
            if finding.suggestion:
                lines.append(f"        -> {finding.suggestion}")
        lines.append("")

    enforced, flagged = totals(results)
    if not enforced and not flagged:
        return "clean\n"
    lines.append(f"{enforced} enforced, {flagged} flagged")
    if enforced:
        lines.append("For the full rule, run: ste-lint.py --rule <id>")
    return "\n".join(lines) + "\n"


def report_triage(results: dict[str, list[Finding]]) -> str:
    """Group the word findings by word, so each is decided once, not per use.

    This is the list a stored "flagged" section would hold, computed instead of
    saved. Nothing to keep in sync, and it cannot claim a word is a problem
    after the prose that used it is gone.
    """
    WORD_RULES = {"H.1", "H.2", "H.4", "1.11", "1.14"}
    seen: dict[str, list[tuple[str, Finding]]] = {}
    for path, findings in results.items():
        for finding in findings:
            if finding.rule in WORD_RULES:
                seen.setdefault(finding.text.lower(), []).append((path, finding))

    if not seen:
        return "No words to decide.\n"

    lines = [f"{len(seen)} word(s) to decide.", ""]
    for word in sorted(seen, key=lambda w: (-len(seen[w]), w)):
        group = seen[word]
        path, first = group[0]
        lines.append(f"  {word:<20} {len(group):>3}x  rule {first.rule}  {first.message}")
        if first.suggestion:
            lines.append(f"  {'':<20}      {first.suggestion}")
        lines.append(f"  {'':<20}      first at {path}:{first.line}:{first.column}")
    lines += [
        "",
        "Decide each one:",
        "  ste-lint.py --add-word <word>          this project uses it",
        "  ste-lint.py --deny <word> <instead>    this project refuses it",
        "  ste-lint.py --prefer <name> <word>     it is another name for <name>",
    ]
    return "\n".join(lines) + "\n"


def report_json(results: dict[str, list[Finding]]) -> str:
    enforced, flagged = totals(results)
    return json.dumps(
        {
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


NOT_BUILT = "The rule text is not built. Run build-dictionary.py to get it."

# Enough to show the shape of the rule without printing the whole standard at
# an agent that came here to fix one finding.
EXAMPLE_LIMIT = 6


def load_rule_book() -> ste_data.RuleBook | None:
    """The writing rules, or None when they are not built.

    Loaded here and nowhere else. Nothing but a rule lookup needs them, and
    every lint of every file would otherwise pay to parse 53 rules it never
    reads.
    """
    path = DATA / "ste-rules.json"
    if not path.is_file():
        return None
    try:
        return ste_data.RuleBook(load_json(path, "The STE rules"))
    except ste_data.VersionError as error:
        raise LintError(
            f"The STE rules cannot be read: {error}.\n"
            "Build them again from your own copy of the standard:\n"
            f"  python3 {HERE / 'build-dictionary.py'} "
            "--pdf /path/to/ASD-STE100_ISSUE9.pdf"
        ) from error


def print_examples(record: dict) -> None:
    examples = record.get("examples", [])
    if not examples:
        return
    print()
    print("Examples:")
    for example in examples[:EXAMPLE_LIMIT]:
        if example["non_ste"]:
            print(f"  Non-STE  {example['non_ste']}")
        print(f"      STE  {example['ste']}")
        print()
    if len(examples) > EXAMPLE_LIMIT:
        print(f"  ({len(examples) - EXAMPLE_LIMIT} more, in the full rule)")


def print_rule(rule_id: str, full: bool = False) -> int:
    """Print one rule: its tier, its statement, and its worked examples.

    The tier and the check come from ste_policy.py, and everything else comes
    from data/ste-rules.json. The join happens here, at the moment of printing,
    which is why a tier that changes needs no rebuild.
    """
    rule_id = ste_data.normalize_rule_id(rule_id)
    entry = ste_policy.RULES.get(rule_id)
    book = load_rule_book()
    record = book.rule(rule_id) if book else None

    if entry is None and record is None:
        print(f"ste-lint: no rule {rule_id}", file=sys.stderr)
        if book is None and re.match(r"^\d+\.\d+$|^GR-\d+$", rule_id):
            print(f"ste-lint: {NOT_BUILT}", file=sys.stderr)
        return EXIT_ERROR

    if entry is not None:
        print(f"Rule {rule_id} — {entry.tier}"
              + (f" (check: {entry.check})" if entry.check else ""))
        print(entry.short)
    else:
        # A general recommendation. ASD says these are not rules, so they have
        # no tier and no check, and the linter never raises one.
        title = record.get("title", "")
        print(f"{rule_id} — general recommendation" + (f", {title}" if title else ""))

    if rule_id in ste_policy.HOUSE_RULES:
        print()
        print("This is a house rule. ASD did not write it, so there is no rule")
        print("text to read. The finding's suggestion is the whole answer.")
        return EXIT_CLEAN

    if record is None:
        print()
        print(NOT_BUILT)
        return EXIT_CLEAN

    print()
    print(record["text"] if full else record["statement"])
    print_examples(record)
    if not full:
        print()
        print(f"For the rule in full: ste-lint.py --rule {rule_id} --full")
    return EXIT_CLEAN


def print_rules() -> int:
    """List every rule, which is the index the agent starts from."""
    book = load_rule_book()
    for rule_id in sorted(ste_policy.RULES, key=ste_data.rule_sort_key):
        entry = ste_policy.RULES[rule_id]
        print(f"  {rule_id:<5} {entry.tier:<9} {entry.short}")
    if book:
        for rule_id in book.ids("recommendation"):
            title = book.rule(rule_id).get("title", "")
            print(f"  {rule_id:<5} {'advice':<9} {title}")
    else:
        print()
        print(NOT_BUILT)
    return EXIT_CLEAN


def print_subject(query: str) -> int:
    """Answer "which rule covers this?" from the standard's own index.

    The index was extracted and written to disk for two releases, and no code
    ever opened it. It is the fastest way into 53 rules, and it is the
    standard's own answer rather than ours.
    """
    book = load_rule_book()
    if book is None:
        print(f"ste-lint: {NOT_BUILT}", file=sys.stderr)
        return EXIT_ERROR

    found = book.find_subjects(query)
    if not found:
        print(f"ste-lint: no subject holds “{query}”", file=sys.stderr)
        return EXIT_ERROR

    for subject, entry in found:
        print(subject)
        for rule_id in entry["rules"]:
            rule = ste_policy.RULES.get(rule_id)
            record = book.rule(rule_id) or {}
            tier = rule.tier if rule else "advice"
            statement = rule.short if rule else record.get("title", "")
            print(f"  {rule_id:<5} {tier:<9} {statement}")
        if not entry["rules"]:
            print(f"        {entry['raw']}")
    return EXIT_CLEAN


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


def excluded(path: Path, config: "Config") -> bool:
    return matches(path, config.exclude)


MARKER_VERSION = "v1.0.0"

# Mirrors data/ste-dictionary.json: meta first, so that `head` on the file says
# what wrote it, then named sections.
MARKER_TEMPLATE = {
    "meta": {
        "written_by": "ste-lint.py --init",
        "version": MARKER_VERSION,
        "note": [
            "This file switches ste-writing on for this repository, and holds",
            "the vocabulary this project decided on. Commit it: a teammate who",
            "clones should get the opt-in and the words together. Delete it to",
            "opt out, and nothing else has to change.",
        ],
    },
    "settings": {
        "locale": "",
        "exclude": ["LICENSE", "**/node_modules/**"],
        "_note": [
            "locale   empty means no spelling check. Set it to one you have",
            "         generated, for example \"en-GB\", and the linter reads",
            "         data/locale-en-GB.json. Make one with: localize.py --en-GB",
            "exclude  paths the linter skips, as glob patterns.",
        ],
    },
    "words": {
        "allow": [],
        "deny": {},
        "prefer": {},
        "_note": [
            "Three decisions, and the linter reads them in this order.",
            "",
            "deny     words this project refuses, as word -> replacement. Give",
            "         an empty replacement to say only 'do not use this'. Read",
            "         first, so a project can refuse a word STE approves.",
            "           \"deny\": { \"utilise\": \"use\", \"synergy\": \"\" }",
            "         Add with: ste-lint.py --deny <word> [replacement]",
            "",
            "allow    words this project uses that the STE dictionary does not,",
            "         per rules 1.6 and 1.8. Silences a finding, and teaches",
            "         rule 2.1 that the word is a noun. A word here is one you",
            "         decided on, not one you could not be bothered to fix.",
            "         Add with: ste-lint.py --add-word <word> ...",
            "",
            "prefer   rule 1.11, one name for one thing, as name -> [variants].",
            "           \"prefer\": { \"repository\": [\"repo\"] }",
            "         Add with: ste-lint.py --prefer <name> <variant> ...",
            "",
            "Base forms only. The plural and the possessive are matched for you.",
            "To see what this project trips on: ste-lint.py --triage <paths>",
        ],
    },
}


def read_marker(target: Path) -> dict | None:
    if not target.is_file():
        print(f"ste-lint: no {target}. Run --init first.", file=sys.stderr)
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def save_marker(target: Path, config: dict) -> None:
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def write_marker(target: Path) -> int:
    """Create the marker file, which is how a repository opts in."""
    if target.exists():
        print(f"ste-lint: {target} already exists, leaving it alone", file=sys.stderr)
        return EXIT_ERROR
    save_marker(target, MARKER_TEMPLATE)
    print(f"wrote {target}")
    print("ste-writing is now on for this repository. Commit the file.")
    return EXIT_CLEAN


def edit_words(target: Path, section: str, change) -> int:
    """Apply a change to one section of words, keeping the file readable."""
    config = read_marker(target)
    if config is None:
        return EXIT_ERROR
    words = config.setdefault("words", {})
    message = change(words)
    save_marker(target, config)
    print(f"{target}: {message}")
    return EXIT_CLEAN


def add_allowed(target: Path, new: list[str]) -> int:
    def change(words: dict) -> str:
        allow = words.get("allow", [])
        known = {w.lower() for w in allow}
        added = [w for w in new if w.lower() not in known]
        words["allow"] = sorted(allow + added, key=str.lower)
        return f"allow += {', '.join(added) or 'nothing new'}"
    return edit_words(target, "allow", change)


def add_denied(target: Path, word: str, replacement: str) -> int:
    def change(words: dict) -> str:
        deny = words.setdefault("deny", {})
        deny[word.lower()] = replacement
        words["deny"] = dict(sorted(deny.items()))
        return f"deny += {word}" + (f" -> {replacement}" if replacement else "")
    return edit_words(target, "deny", change)


def add_preferred(target: Path, name: str, variants: list[str]) -> int:
    def change(words: dict) -> str:
        prefer = words.setdefault("prefer", {})
        existing = prefer.get(name, [])
        merged = sorted({*existing, *(v.lower() for v in variants)})
        prefer[name] = merged
        words["prefer"] = dict(sorted(prefer.items()))
        return f"prefer += {name} over {', '.join(merged)}"
    return edit_words(target, "prefer", change)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check prose against ASD-STE100 Simplified Technical English.",
    )
    parser.add_argument("files", nargs="*", help="files to check, or - for standard input")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--config", type=Path, default=None, help=f"path to {MARKER}")
    parser.add_argument(
        "--init", action="store_true", help=f"write {MARKER} here and switch this repo on"
    )
    parser.add_argument(
        "--add-word", nargs="+", metavar="WORD", help="add words to words.allow"
    )
    parser.add_argument(
        "--deny", nargs="+", metavar=("WORD", "REPLACEMENT"),
        help="refuse a word in this project: --deny utilise use",
    )
    parser.add_argument(
        "--prefer", nargs="+", metavar=("NAME", "VARIANT"),
        help="one name for one thing: --prefer repository repo",
    )
    parser.add_argument(
        "--triage", action="store_true",
        help="group the findings by word, so each can be allowed or denied once",
    )
    parser.add_argument("--rule", metavar="ID", help="print one rule, for example 3.6")
    parser.add_argument(
        "--full", action="store_true",
        help="with --rule, print the text of the rule and not only its statement",
    )
    parser.add_argument(
        "--rules", action="store_true", help="list every rule and its tier"
    )
    parser.add_argument(
        "--subject", metavar="TEXT",
        help="which rule covers this? Searches the standard's own index",
    )
    parser.add_argument(
        "--fail-on-flagged",
        action="store_true",
        help="exit 1 on flagged findings too, not only enforced ones",
    )
    args = parser.parse_args()

    marker = args.config or find_config(Path.cwd()) or (Path.cwd() / MARKER)
    if args.init:
        return write_marker(Path.cwd() / MARKER)
    if args.add_word:
        return add_allowed(marker, args.add_word)
    if args.deny:
        word, *rest = args.deny
        return add_denied(marker, word, " ".join(rest))
    if args.prefer:
        if len(args.prefer) < 2:
            parser.error("--prefer needs the name and at least one variant")
        name, *variants = args.prefer
        return add_preferred(marker, name, variants)

    targets = args.files or ["-"]

    try:
        # Reading a rule needs the rules and nothing else. It answers before the
        # dictionary is loaded, so a repository with no dictionary yet can still
        # find out what the rule it just failed actually says.
        if args.rule:
            return print_rule(args.rule, args.full)
        if args.subject:
            return print_subject(args.subject)
        if args.rules:
            return print_rules()

        anchor = Path(targets[0]) if targets[0] != "-" else Path.cwd()
        config = load_config(args.config, anchor)
        dictionary = load_json(DATA / "ste-dictionary.json", "The STE dictionary")
        locale = None
        if config.locale:
            locale = load_json(
                DATA / f"locale-{config.locale}.json",
                f"The {config.locale} locale",
            )
        try:
            # The slop list and the phrasal verb list are derived here rather
            # than stored, so a change to ste_policy.py takes effect at once
            # instead of waiting for a rebuild.
            vocabulary = ste_data.Vocabulary(dictionary, locale)
        except ste_data.VersionError as error:
            raise LintError(
                f"The STE dictionary cannot be read: {error}.\n"
                "Build it again from your own copy of the standard:\n"
                f"  python3 {HERE / 'build-dictionary.py'} "
                "--pdf /path/to/ASD-STE100_ISSUE9.pdf"
            ) from error

        linter = Linter({"vocabulary": vocabulary}, config)

        results: dict[str, list[Finding]] = {}
        for name in targets:
            if name == "-":
                results["<stdin>"] = linter.lint(
                    build_document("<stdin>", sys.stdin.read())
                )
                continue
            path = Path(name)
            if not path.is_file():
                raise LintError(f"no such file: {name}")
            if excluded(path, config):
                continue
            results[name] = linter.lint(
                build_document(name, path.read_text(encoding="utf-8", errors="replace"))
            )
    except (LintError, OSError, json.JSONDecodeError, KeyError) as error:
        print(f"ste-lint: {error}", file=sys.stderr)
        return EXIT_ERROR

    if args.triage:
        print(report_triage(results), end="")
        return EXIT_CLEAN

    print(
        report_json(results) if args.format == "json" else report_text(results),
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
