#!/usr/bin/env python3
"""What this skill decides, as opposed to what ASD wrote.

Three sources feed the linter, and they stay apart:

    data/ste-dictionary.json   ASD's words. Built from your own copy of the
                               standard, gitignored, and never hand-edited.
    this module                our judgements: which rules the linter enforces,
                               and the words the standard never documents.
    <repo>/.ste-writing.json   the project's own words, and the marker that
                               switches the skill on for that repository.

This was four JSON files in an assets/ directory. It is code now, because none
of it is a dictionary. A rule tier names a Python method. A slop word only means
something to the check that reads it. Keeping them as data bought nothing and
cost a directory, a loader, and one real bug class: "check": "passive_voice" was
a string nobody validated, so a typo silently switched a rule off and every test
still passed. RULES below names the method, and CHECKS_EXIST in the tests holds
it to that.

ASD-STE100 was written for aircraft maintenance procedures. Its dictionary
approves about 800 words, which is enough for a procedure and nowhere near
enough for prose: an allowlist run over this repository's own README reported
279 findings in 1137 words, and the unknown words were "so", "way", "every",
and "still". So this skill does not run an allowlist. It uses the standard's
vocabulary judgements to find slop, which is the job it claims on the label.
"""

from __future__ import annotations

from typing import NamedTuple


class Rule(NamedTuple):
    """One ASD-STE100 rule, and what this skill does about it.

    tier   enforced  the linter decides, and a violation fails the run
           flagged   the linter warns, and the agent resolves it or says why not
           judgment  no machine can decide it, so the agent attests to it
           counting  not a fault at all: it shapes how words are counted

    check  the Linter method that implements the rule, or None when the rule is
           carried here only for the reference files and the checklist.

    short  the rule in one line. Emitted with every finding, so the agent can
           usually fix it without opening the rule at all.
    """

    tier: str
    check: str | None
    short: str


# The H rules are ours, not ASD's. The standard had no reason to ban "seamless".
HOUSE_RULES = ("H.1", "H.2", "H.3")

# A word this long, whose approved replacement is shorter, is the shape of the
# problem: a long Latinate word standing in for a short plain one.
SLOP_MIN_LENGTH = 8

MARKETING = {
    "battle-tested", "best-in-class", "blazing", "blazingly", "compelling",
    "cutting-edge", "delightful", "effortless", "effortlessly", "elegant",
    "elegantly", "empower", "empowers", "enterprise-grade", "first-class",
    "frictionless", "game-changing", "groundbreaking", "innovative",
    "lightning-fast", "next-generation", "performant", "powerful",
    "powerfully", "revolutionary", "robust", "robustly", "seamless",
    "seamlessly", "state-of-the-art", "streamline", "streamlined",
    "supercharge", "turnkey", "unleash", "unlock", "world-class"
}

SLOP_CORE = {
    "accomplish", "acquire", "additional", "adequate", "advise",
    "appropriate", "ascertain", "assist", "attempt", "commence", "conduct",
    "considerable", "determine", "ensure", "establish", "evident",
    "facilitate", "fundamental", "implement", "indicate", "initiate",
    "modify", "obtain", "perform", "permit", "provide", "represent",
    "request", "require", "significant", "terminate", "utilize", "various",
    "verify"
}

PHRASAL_VERBS = {
    "bubble up", "circle back", "dial in", "dive into", "double down",
    "drill down", "kick off", "lean into", "level up", "loop in", "ramp up",
    "reach out", "roll out", "spin down", "spin up", "stand up",
    "tear down", "wire up"
}

HEDGES = (
    "as mentioned above", "as noted above", "at the end of the day",
    "it is important to note", "it is worth noting", "it should be noted",
    "needless to say", "please note that", "that being said"
)

EXTRA_UNAPPROVED = {
    "additionally": ({"adv"}, ("ALSO",)),
    "aforementioned": ({"adj"}, ("THIS", "THESE")),
    "amongst": ({"prep"}, ("AMONG",)),
    "consequently": ({"adv"}, ("THEN", "AS A RESULT")),
    "constitute": ({"v"}, ("BE", "MAKE")),
    "crucial": ({"adj"}, ("IMPORTANT", "NECESSARY")),
    "delve": ({"v"}, ("EXAMINE",)),
    "demonstrate": ({"v"}, ("SHOW",)),
    "endeavor": ({"v", "n"}, ("TRY", "WORK")),
    "endeavour": ({"v", "n"}, ("TRY", "WORK")),
    "enhance": ({"v"}, ("IMPROVE",)),
    "finalize": ({"v"}, ("COMPLETE",)),
    "functionality": ({"n"}, ("FUNCTION",)),
    "furthermore": ({"adv"}, ("ALSO",)),
    "henceforth": ({"adv"}, ("AFTER THIS",)),
    "holistic": ({"adj"}, ("COMPLETE",)),
    "leverage": ({"v", "n"}, ("USE",)),
    "methodology": ({"n"}, ("METHOD",)),
    "moreover": ({"adv"}, ("ALSO",)),
    "myriad": ({"adj", "n"}, ("MANY",)),
    "optimize": ({"v"}, ("IMPROVE",)),
    "plethora": ({"n"}, ("MANY",)),
    "possess": ({"v"}, ("HAVE",)),
    "prior": ({"adj"}, ("BEFORE", "PREVIOUS")),
    "purchase": ({"v", "n"}, ("GET",)),
    "regarding": ({"prep"}, ("ABOUT",)),
    "robust": ({"adj"}, ("RELIABLE", "STRONG")),
    "streamline": ({"v"}, ("SIMPLIFY",)),
    "therein": ({"adv"}, ("IN IT",)),
    "whilst": ({"conj"}, ("WHILE",)),
}

RULES = {
    "1.1": Rule("judgment", None, "Use approved words, technical nouns, or technical verbs"),
    "1.2": Rule("flagged", None, "Use an approved word only as its specified part of speech"),
    "1.3": Rule("flagged", None, "Use an approved word only with its approved meaning"),
    "1.4": Rule("judgment", None, "Use only approved forms of verbs and adjectives"),
    "1.5": Rule("judgment", None, "Technical noun categories"),
    "1.6": Rule("judgment", None, "An unapproved word must be a technical noun"),
    "1.7": Rule("flagged", None, "Do not use a technical noun as a verb"),
    "1.8": Rule("judgment", None, "Technical nouns come from your company or field"),
    "1.9": Rule("judgment", None, "Select a short technical noun that is easy to understand"),
    "1.10": Rule("judgment", None, "No regional, slang, or jargon technical nouns"),
    "1.11": Rule("flagged", "inconsistent_term", "One name for one thing"),
    "1.12": Rule("judgment", None, "Technical verb categories"),
    "1.13": Rule("flagged", None, "Do not use a technical verb as a noun"),
    "1.14": Rule("enforced", "locale_spelling", "American English spelling"),
    "2.1": Rule("flagged", "long_noun_cluster", "Multi-word nouns of no more than three words"),
    "2.2": Rule("flagged", None, "Write a technical noun of more than three words in full"),
    "3.1": Rule("judgment", None, "Use only the verb forms given in the dictionary"),
    "3.2": Rule("flagged", None, "Use only the permitted verb forms and tenses"),
    "3.3": Rule("flagged", None, "Use the past participle as an adjective"),
    "3.4": Rule("enforced", "auxiliary_stack", "No complex verb constructions from stacked auxiliaries"),
    "3.5": Rule("enforced", "ing_main_verb", "The “-ing” form only as a technical noun or modifier"),
    "3.6": Rule("enforced", "passive_voice", "Use the active voice"),
    "3.7": Rule("flagged", "nominalization", "Use a verb for an action, not a noun"),
    "4.1": Rule("judgment", None, "Write short and clear sentences"),
    "4.2": Rule("enforced", "contraction", "Do not omit words or use contractions"),
    "4.3": Rule("flagged", None, "Use a vertical list for complex text"),
    "4.4": Rule("flagged", None, "Use connecting words between related sentences"),
    "4.5": Rule("flagged", None, "Use an article or demonstrative adjective before a noun"),
    "5.1": Rule("enforced", "long_instruction", "Instructions: 20 words maximum"),
    "5.2": Rule("flagged", None, "One instruction per sentence"),
    "5.3": Rule("flagged", None, "Write instructions in the imperative form"),
    "5.4": Rule("flagged", None, "Put a condition before its command"),
    "5.5": Rule("flagged", None, "Notes give information, not instructions"),
    "6.1": Rule("judgment", None, "Give information gradually"),
    "6.2": Rule("judgment", None, "Use key words and phrases for logical structure"),
    "6.3": Rule("enforced", "long_descriptive", "Descriptive text: 25 words maximum"),
    "6.4": Rule("judgment", None, "Use paragraphs to show related information"),
    "6.5": Rule("judgment", None, "One topic per paragraph"),
    "6.6": Rule("enforced", "long_paragraph", "No paragraph of more than six sentences"),
    "7.1": Rule("flagged", None, "Identify the level of risk"),
    "7.2": Rule("flagged", None, "Start a safety instruction with the command or condition"),
    "7.3": Rule("flagged", None, "Explain the risk or possible result"),
    "8.1": Rule("enforced", "semicolon", "No semicolon"),
    "8.2": Rule("flagged", None, "Hyphens connect directly related words"),
    "8.3": Rule("flagged", None, "Permitted uses of parentheses"),
    "8.4": Rule("counting", None, "In a vertical list a colon ends a sentence"),
    "8.5": Rule("counting", None, "Parenthetical text counts as one word"),
    "8.6": Rule("counting", None, "Numbers, units, abbreviations, and quoted text count as one word"),
    "8.7": Rule("counting", None, "A hyphenated word counts as one word"),
    "9.1": Rule("judgment", None, "Rewrite the sentence when word-for-word replacement fails"),
    "9.2": Rule("judgment", None, "Use each approved word correctly"),
    "9.3": Rule("enforced", "phrasal_verb", "Do not make phrasal verbs"),
    "9.4": Rule("judgment", None, "Use a consistent style"),
    "H.1": Rule("enforced", "marketing_word", "House rule: no marketing adjectives"),
    "H.2": Rule("enforced", "unapproved_alternative", "House rule: replace a word the dictionary does not approve"),
    "H.3": Rule("flagged", "hedge", "House rule: no hedging preamble"),
}
