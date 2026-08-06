#!/usr/bin/env python3
"""The shapes of the built data, shared by the extractor and the linter.

The split this module keeps:

    data/ste-dictionary.json   the words ASD approved. Built from your own copy
                               of the standard, never committed.
    data/ste-rules.json        the writing rules ASD wrote, in the same
                               condition and for the same reason.
    scripts/ste_policy.py      what we decided. The slop words, the marketing
                               words, and the words STE never documents.
    <repo>/.ste-writing.json   what the project decided. Its own words, and the
                               marker that switches the skill on.

The first two are generated. Our own words stay out of the dictionary file and
are merged here, at load time, so a change to the policy takes effect at once
instead of waiting for a rebuild that wants a 434-page PDF. The tier of a rule
keeps out of the rule file for the same reason.
"""

from __future__ import annotations

import re

import ste_policy

# The release of the build format, written into data/ste-dictionary.json as
# "version". It follows the release tag pattern this repository uses, v[0-9]*.
#
# Raise the major when a built dictionary stops being readable by the current
# linter: a renamed key, a changed shape, a field that moves. The linter refuses
# a major it does not know and asks for a rebuild, which is better than a
# KeyError halfway through a file. Raise the minor or the patch for a change
# that an older linter can still read.
DICTIONARY_VERSION = "v1.0.0"

# The release of data/ste-rules.json, which holds the writing rules. It is
# versioned apart from the dictionary because the two files change for different
# reasons: a new part of speech does not move a rule field, and a new rule field
# does not move a word.
RULES_VERSION = "v1.0.0"

VERSION_PATTERN = re.compile(r"^v(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?$")

VOWELS = set("aeiou")


class VersionError(Exception):
    """A built file does not match the code that reads it."""


def parse_version(version: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.match(str(version or ""))
    if not match:
        raise VersionError(f"{version!r} is not a version of the form v1.0.0")
    return (
        int(match["major"]),
        int(match["minor"] or 0),
        int(match["patch"] or 0),
    )


def check_version(meta: dict, wanted: str = DICTIONARY_VERSION,
                  what: str = "dictionary") -> str:
    """Confirm a built file is one this code can read.

    A file from before versioning has no "version" at all, which is the clearest
    case of all: it was built by code that wrote a different shape.
    """
    found = meta.get("version")
    if found is None:
        raise VersionError(
            f"this {what} was built before the format was versioned"
        )
    major = parse_version(found)[0]
    if major != parse_version(wanted)[0]:
        raise VersionError(
            f"this {what} is {found}, and this code reads "
            f"{wanted.split('.')[0]}.x"
        )
    return found


def inflect(lemma: str, parts_of_speech: list[str]) -> set[str]:
    """Generate the inflected forms of a word.

    The dictionary prints inflected forms for approved words but gives
    unapproved words in their base form only. Without this, the denylist would
    catch "utilize" and miss "utilizing", which is most of the real text.

    No lemmatizer is available (this is standard library only), so this applies
    English suffix rules directly. Over-generation is handled by the caller: any
    form that collides with an approved word is dropped.
    """
    if " " in lemma or "-" in lemma:
        return {lemma}

    forms = {lemma}
    stem = lemma

    def plural_s() -> str:
        if re.search(r"(s|x|z|ch|sh)$", stem):
            return stem + "es"
        if re.search(r"[^aeiou]y$", stem):
            return stem[:-1] + "ies"
        return stem + "s"

    def doubled() -> str:
        # A short stressed syllable doubles its final consonant: "fit" -> "fitted".
        if (
            len(stem) >= 3
            and stem[-1] not in VOWELS
            and stem[-1] not in "wxy"
            and stem[-2] in VOWELS
            and stem[-3] not in VOWELS
        ):
            return stem + stem[-1]
        return stem

    if "v" in parts_of_speech:
        forms.add(plural_s())
        if stem.endswith("e"):
            forms.add(stem + "d")
            forms.add(stem[:-1] + "ing")
        elif re.search(r"[^aeiou]y$", stem):
            forms.add(stem[:-1] + "ied")
            forms.add(stem + "ing")
        else:
            forms.add(doubled() + "ed")
            forms.add(doubled() + "ing")

    if "n" in parts_of_speech or "TN" in parts_of_speech:
        forms.add(plural_s())

    if "adj" in parts_of_speech:
        if stem.endswith("e"):
            forms.update({stem + "r", stem + "st"})
        elif re.search(r"[^aeiou]y$", stem):
            forms.update({stem[:-1] + "ier", stem[:-1] + "iest", stem[:-1] + "ily"})
        else:
            forms.update({doubled() + "er", doubled() + "est", stem + "ly"})

    # A lemma that holds a space returned above, so no form can hold one here.
    return {form for form in forms if form.isalpha()}


def house_extras() -> dict[str, dict]:
    """The unapproved words we add, which the standard never documents."""
    return {
        word: {"pos": sorted(pos), "replacements": list(replacements)}
        for word, (pos, replacements) in ste_policy.EXTRA_UNAPPROVED.items()
    }


def select_slop(lemmas: dict) -> set[str]:
    """Choose the words the linter treats as slop.

    The obvious source is the standard's own non-approved list, but that list is
    the whole non-approved vocabulary of English, not a slop list: it holds
    "way", "every", "under", and "load". Using it whole gave 44 errors on a
    README that reads fine, and a check nobody can act on is a check nobody
    reads.

    So a word gets in two ways: it is in SLOP_CORE, or it is at least
    SLOP_MIN_LENGTH characters and the standard replaces it with something
    shorter. That second test is the shape of the problem, a long Latinate word
    standing in for a short plain one.
    """
    chosen = {word for word in ste_policy.SLOP_CORE if word in lemmas}
    chosen |= set(ste_policy.EXTRA_UNAPPROVED)

    for lemma, entry in lemmas.items():
        if len(lemma) < ste_policy.SLOP_MIN_LENGTH or " " in lemma:
            continue
        replacements = [
            re.sub(r"\s*\([^)]*\)", "", text).strip() for text in entry["replacements"]
        ]
        shortest = min((len(text) for text in replacements if text), default=None)
        if shortest is not None and shortest < len(lemma):
            chosen.add(lemma)
    return chosen


def unmatched_slop_core(lemmas: dict) -> set[str]:
    """SLOP_CORE entries the standard does not list as non-approved.

    They are either approved after all, or absent from the dictionary entirely.
    Either way the entry does nothing, so the tests report it rather than let the
    list rot quietly.
    """
    return set(ste_policy.SLOP_CORE) - set(lemmas)


class Vocabulary:
    """Every word list the linter needs, built once at load time."""

    def __init__(self, dictionary: dict, locale: dict | None = None) -> None:
        self.meta: dict = dictionary.get("meta", {})
        # Check before touching the content. A dictionary built by different
        # code should say so, not fail later on a missing key. The call is the
        # guard: it raises, and nothing needs the version it returns.
        check_version(self.meta)

        approved = dictionary["approved"]
        alternatives = dictionary["alternatives"]
        self.approved_forms: set[str] = set(approved["forms"])
        self.approved_lemmas: dict = approved["lemmas"]

        # Start from the standard, then add our own unapproved words. Theirs are
        # already expanded; ours are expanded here.
        self.alternative_lemmas: dict = dict(alternatives["lemmas"])
        self.alternative_forms: dict[str, str] = dict(alternatives["forms"])

        for lemma, spec in house_extras().items():
            entry = self.alternative_lemmas.setdefault(
                lemma, {"pos": [], "replacements": []}
            )
            entry["pos"] = sorted(set(entry["pos"]) | set(spec["pos"]))
            for replacement in spec["replacements"]:
                if replacement not in entry["replacements"]:
                    entry["replacements"].append(replacement)
            for form in inflect(lemma, entry["pos"]):
                # An approved word always wins, so a generated form never turns a
                # permitted word into a violation.
                if form not in self.approved_forms:
                    self.alternative_forms.setdefault(form, lemma)

        slop_lemmas = select_slop(self.alternative_lemmas)
        self.slop_forms: dict[str, str] = {
            form: lemma
            for form, lemma in self.alternative_forms.items()
            if lemma in slop_lemmas
        }

        self.phrasal: list[str] = sorted(
            {
                lemma
                for lemma in self.alternative_lemmas
                if " " in lemma and len(lemma.split()) == 2
            }
            | set(ste_policy.PHRASAL_VERBS)
        )

        # A locale turns rule 1.14 on. Without one there is no spelling check at
        # all, because the skill ships no spelling list: the map is generated by
        # an agent walking the dictionary, once, per language. See localize.py.
        self.locale: str = ""
        self.spellings: dict[str, str] = {}
        if locale:
            self.locale = locale.get("meta", {}).get("locale", "")
            self.spellings = dict(locale.get("spellings", {}))

    def replacements(self, lemma: str) -> list[str]:
        return self.alternative_lemmas.get(lemma, {}).get("replacements", [])


def normalize_rule_id(rule_id: str) -> str:
    """Accept "3.6", "gr-5", and "h.2" for the ids the data calls 3.6, GR-5, H.2."""
    text = str(rule_id or "").strip()
    return text.upper() if re.match(r"^(?:gr-|h\.)", text, re.I) else text


def rule_sort_key(rule_id: str) -> tuple:
    """Sort 1.2 before 1.10, and put the recommendations after the rules."""
    match = re.match(r"^(?:GR-)?(\d+)(?:\.(\d+))?$", normalize_rule_id(rule_id))
    if not match:
        return (2, 0, 0, rule_id)
    group = 1 if rule_id.upper().startswith("GR-") else 0
    return (group, int(match.group(1)), int(match.group(2) or 0), "")


class RuleBook:
    """The writing rules of the standard, as data.

    data/ste-rules.json holds what ASD wrote: the statement of each rule, its
    text, its worked examples, and the standard's own subject index. What this
    skill decided about a rule — its tier, and the linter check that implements
    it — stays in ste_policy.py, and the two are joined when a rule is printed.

    They used to be joined when the file was built. The extractor wrote the tier
    into the rule text, and the reader deleted that line again with a regex, so
    a tier that changed sat stale in data/ until somebody re-ran a 434-page PDF
    through the extractor. A build-time join of two things that change at
    different speeds is a build-time lie.
    """

    def __init__(self, raw: dict) -> None:
        self.meta: dict = raw.get("meta", {})
        # Check before touching the content, exactly as the dictionary does.
        check_version(self.meta, RULES_VERSION, "rule book")
        self.rules: dict = raw.get("rules", {})
        self.subjects: dict = raw.get("subjects", {})

    def rule(self, rule_id: str) -> dict | None:
        return self.rules.get(normalize_rule_id(rule_id))

    def ids(self, kind: str | None = None) -> list[str]:
        return sorted(
            (
                rule_id
                for rule_id, record in self.rules.items()
                if kind is None or record.get("kind") == kind
            ),
            key=rule_sort_key,
        )

    def find_subjects(self, query: str) -> list[tuple[str, dict]]:
        """Subjects of the standard's own index that hold the query text."""
        wanted = query.strip().lower()
        return [
            (subject, entry)
            for subject, entry in sorted(self.subjects.items())
            if wanted in subject.lower()
        ]
