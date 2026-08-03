#!/usr/bin/env python3
"""Vocabulary shared by the extractor and the linter.

The split this module keeps:

    data/ste-dictionary.json   what ASD wrote. Built from your own copy of the
                               standard, never committed.
    assets/house-style.json    what we wrote. The slop list, the marketing
                               words, and the words STE never documents.
    .ste-writing.json          what the project decided. Its technical nouns.

Only the first is generated. The house lists stay out of the dictionary file and
are merged here, at load time, so editing them takes effect at once instead of
waiting for a rebuild that wants a 434-page PDF.
"""

from __future__ import annotations

import re

VOWELS = set("aeiou")


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

    return {form for form in forms if form.isalpha() or " " in form}


def house_extras(house: dict) -> dict[str, dict]:
    """The unapproved words we add, which the standard never documents."""
    return {
        word.lower(): {"pos": spec["pos"], "replacements": list(spec["replacements"])}
        for word, spec in house["extra_unapproved"].items()
        if not word.startswith("_")
    }


def select_slop(lemmas: dict, house: dict) -> set[str]:
    """Choose the words ste-general treats as slop.

    See "_slop_comment" in house-style.json for why this is a subset rather than
    the whole non-approved list. Two ways in: the curated core, and a length test
    for a long word that the standard replaces with a shorter one.
    """
    minimum = house["slop_min_length"]
    chosen = {word.lower() for word in house["slop_core"] if word.lower() in lemmas}
    chosen |= set(house_extras(house))

    for lemma, entry in lemmas.items():
        if len(lemma) < minimum or " " in lemma:
            continue
        replacements = [
            re.sub(r"\s*\([^)]*\)", "", text).strip() for text in entry["replacements"]
        ]
        shortest = min((len(text) for text in replacements if text), default=None)
        if shortest is not None and shortest < len(lemma):
            chosen.add(lemma)
    return chosen


def unmatched_slop_core(lemmas: dict, house: dict) -> set[str]:
    """slop_core entries the standard does not list as non-approved.

    They are either approved after all, or absent from the dictionary entirely.
    Either way the entry does nothing, so the tests report it rather than let the
    list rot quietly.
    """
    return {word.lower() for word in house["slop_core"]} - set(lemmas)


class Vocabulary:
    """Every word list the linter needs, built once at load time."""

    def __init__(self, dictionary: dict, house: dict) -> None:
        approved = dictionary["approved"]
        alternatives = dictionary["alternatives"]

        self.meta: dict = dictionary.get("meta", {})
        self.approved_forms: set[str] = set(approved["forms"])
        self.approved_lemmas: dict = approved["lemmas"]

        # Start from the standard, then add our own unapproved words. Theirs are
        # already expanded; ours are expanded here.
        self.alternative_lemmas: dict = dict(alternatives["lemmas"])
        self.alternative_forms: dict[str, str] = dict(alternatives["forms"])

        for lemma, spec in house_extras(house).items():
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

        slop_lemmas = select_slop(self.alternative_lemmas, house)
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
            | set(house["phrasal_verbs"])
        )

    def replacements(self, lemma: str) -> list[str]:
        return self.alternative_lemmas.get(lemma, {}).get("replacements", [])
