#!/usr/bin/env python3
"""Tests for the ste-writing skill.

    python3 agent-skills/ste-writing/tests/test_ste.py

The dictionary tests need data/, so build it first. They report as skipped when
it is absent, because a clone has no data until you build it. Everything else
runs anywhere.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"
HOOKS = SKILL / "hooks"
DATA = SKILL / "data"
LINTER = SCRIPTS / "ste-lint.py"

CLEAN, ENFORCED, FLAGGED, ERROR = 0, 1, 2, 3


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(SCRIPTS))
lint = load("ste_lint", LINTER)
build = load("ste_build", SCRIPTS / "build-dictionary.py")
data_module = load("ste_data_module", SCRIPTS / "ste_data.py")
policy = load("ste_policy_module", SCRIPTS / "ste_policy.py")
localize = load("ste_localize", SCRIPTS / "localize.py")

DICTIONARY = DATA / "ste-dictionary.json"
RULES = DATA / "ste-rules.json"
have_data = DICTIONARY.is_file()
needs_data = unittest.skipUnless(have_data, "no data/, run build-dictionary.py first")
needs_rules = unittest.skipUnless(
    RULES.is_file(), "no data/ste-rules.json, run build-dictionary.py first"
)


def run_linter(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LINTER), *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


class WordCount(unittest.TestCase):
    """Rules 8.5 thru 8.7. These decide whether 5.1 and 6.3 measure anything."""

    def test_parenthetical_counts_as_one_word(self):
        # Drain | 2 liters | (approximately) | of | fuel
        self.assertEqual(lint.count_words("Drain 2 liters (approximately) of fuel."), 5)

    def test_number_with_unit_counts_as_one_word(self):
        # The | limit | is | 800 kPa
        self.assertEqual(lint.count_words("The limit is 800 kPa."), 4)

    def test_quoted_text_counts_as_one_word(self):
        self.assertEqual(lint.count_words('Set the switch to "ON" now.'), 6)

    def test_hyphenated_word_counts_as_one_word(self):
        self.assertEqual(lint.count_words("Turn the well-known high-pressure valve."), 5)


class Segmentation(unittest.TestCase):
    def test_wrapped_sentence_is_one_sentence(self):
        raw = "The parser reads the file and then it\nwrites a summary of the run.\n"
        found = lint.blocks(raw)
        self.assertEqual(len(found), 1)
        start, end, is_paragraph = found[0]
        self.assertTrue(is_paragraph)
        text = raw[start:end].replace("\n", " ")
        self.assertEqual(len(lint.split_sentences(text, start)), 1)

    def test_list_is_not_a_paragraph(self):
        raw = "- one.\n- two.\n- three.\n"
        self.assertTrue(all(not is_para for _, _, is_para in lint.blocks(raw)))

    def test_table_row_is_not_a_paragraph(self):
        raw = "| a | b |\n| c | d |\n"
        self.assertTrue(all(not is_para for _, _, is_para in lint.blocks(raw)))


class Patterns(unittest.TestCase):
    def test_possessive_is_not_a_contraction(self):
        self.assertFalse(lint.CONTRACTION.findall("the project's glossary"))

    def test_real_contractions_are_caught(self):
        for text in ("don't", "it's here", "we've seen", "they'll go"):
            self.assertTrue(lint.CONTRACTION.findall(text), text)

    def test_modal_with_adjective_is_not_a_stacked_auxiliary(self):
        for text in ("must be present", "must be in the list", "can be blue"):
            self.assertFalse(lint.AUXILIARY_STACK.findall(text), text)

    def test_stacked_auxiliaries_are_caught(self):
        for text in ("it has been removed", "must have been done", "is being tested"):
            self.assertTrue(lint.AUXILIARY_STACK.findall(text), text)


class Masking(unittest.TestCase):
    def test_offsets_survive_masking(self):
        raw = "Use `utilize` here.\n"
        self.assertEqual(len(lint.mask(raw)), len(raw))

    def test_code_is_out_of_scope(self):
        masked = lint.mask("Run `utilize --now` please.\n")
        self.assertNotIn("utilize", masked)

    def test_fenced_code_is_out_of_scope(self):
        masked = lint.mask("Text.\n\n```\nutilize the thing\n```\n")
        self.assertNotIn("utilize", masked)


class Version(unittest.TestCase):
    """The version tells the linter whether it can read the built dictionary."""

    def test_the_shipped_version_matches_the_release_pattern(self):
        # The repository tags releases as v[0-9]*, so the field follows it.
        self.assertRegex(data_module.DICTIONARY_VERSION, r"^v[0-9]+(\.[0-9]+)*$")

    def test_versions_parse(self):
        self.assertEqual(data_module.parse_version("v1.0.0"), (1, 0, 0))
        self.assertEqual(data_module.parse_version("v2"), (2, 0, 0))
        self.assertEqual(data_module.parse_version("v1.4"), (1, 4, 0))

    def test_a_version_without_the_prefix_is_rejected(self):
        for text in ("1.0.0", "stable-1", "", None, "vNext"):
            with self.assertRaises(data_module.VersionError):
                data_module.parse_version(text)

    def test_a_matching_major_is_accepted(self):
        major = data_module.parse_version(data_module.DICTIONARY_VERSION)[0]
        self.assertTrue(data_module.check_version({"version": f"v{major}.99.99"}))

    def test_a_different_major_is_refused(self):
        major = data_module.parse_version(data_module.DICTIONARY_VERSION)[0]
        with self.assertRaises(data_module.VersionError):
            data_module.check_version({"version": f"v{major + 1}.0.0"})

    def test_a_dictionary_from_before_versioning_is_refused(self):
        with self.assertRaises(data_module.VersionError):
            data_module.check_version({"built_by": "build-dictionary.py 2"})


class Policy(unittest.TestCase):
    """The rule table and the linter have to agree about what exists."""

    def setUp(self):
        self.source = LINTER.read_text(encoding="utf-8")

    def test_every_declared_check_is_emitted_somewhere(self):
        # This is the bug the JSON version could not catch: a check name nobody
        # validated, so a typo silently switched a rule off and the tests passed.
        for rule, entry in policy.RULES.items():
            if entry.check:
                self.assertIn(f'"{entry.check}"', self.source, f"{rule}: {entry.check}")

    # Text built to set off as many checks as one document can. Reading the
    # source for this does not work: most checks are emitted from tables, so a
    # regex over self.make() sees 6 of the 16 and passes for the wrong reason.
    TRIGGERS = (
        "We utilized a comprehensive methodology; it was designed to ensure success.\n"
        "The team will spin up the service and it is worth noting we are testing it.\n"
        "The report has been reviewed and don't forget the check.\n"
        "Do the maintenance of the unit and perform an analysis of the log.\n"
        "This is a very long descriptive sentence that keeps going and going well "
        "past the limit of twenty five words in total length here.\n"
        "Install the pump and then close the valve and then open the drain and "
        "then start the engine and check it.\n"
    )

    @needs_data
    def test_every_check_the_linter_emits_is_declared(self):
        declared = {entry.check for entry in policy.RULES.values() if entry.check}
        # An empty config, so the repository's own glossary cannot suppress a
        # check and quietly weaken this test.
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / ".ste-writing.json"
            config.write_text("{}")
            report = json.loads(
                run_linter(
                    "--config", str(config), "--format", "json", "-",
                    stdin=self.TRIGGERS,
                ).stdout
            )
        emitted = {f["check"] for findings in report["files"].values() for f in findings}
        self.assertGreaterEqual(len(emitted), 10, "the trigger text stopped working")
        self.assertEqual(emitted - declared, set())
        for findings in report["files"].values():
            for finding in findings:
                self.assertIn(finding["rule"], policy.RULES)
                self.assertEqual(finding["tier"], policy.RULES[finding["rule"]].tier)
                self.assertEqual(finding["short"], policy.RULES[finding["rule"]].short)

    def test_every_rule_has_a_statement(self):
        for rule, entry in policy.RULES.items():
            self.assertTrue(entry.short.strip(), rule)

    def test_tiers_are_known(self):
        for rule, entry in policy.RULES.items():
            self.assertIn(entry.tier, {"enforced", "flagged", "judgment", "counting"}, rule)

    def test_a_rule_with_a_check_is_never_judgment(self):
        for rule, entry in policy.RULES.items():
            if entry.check:
                self.assertNotEqual(entry.tier, "judgment", rule)

    def test_the_documented_counts_match_the_table(self):
        """The tier counts appear in prose, and prose drifts.

        This has already gone stale twice: once when the tiers were rewritten,
        and once when H.4 was added and "enforces 12" stayed behind.
        """
        import collections
        counts = collections.Counter(
            entry.tier for entry in policy.RULES.values() if entry.check
        )
        # Check every stated count, not just one. Accepting "at least one right
        # mention" lets a stale number sit next to a fresh one: a first version
        # of this test passed while the table said 12 and the prose said 13.
        for doc in (SKILL / "SKILL.md", SKILL / "README.md"):
            text = doc.read_text(encoding="utf-8")
            for tier in ("enforced", "flagged"):
                verb = "enforces" if tier == "enforced" else "flags"
                stated = [
                    int(n) for n in re.findall(
                        rf"{verb} (\d+)\b"           # "enforces 13"
                        rf"|\| {tier} \| (\d+) \|"   # "| enforced | 13 |"
                        rf"|The (\d+) {tier}\b",     # "The 13 enforced:"
                        text,
                    ) for n in n if n
                ]
                self.assertTrue(stated, f"{doc.name} states no {tier} count")
                self.assertEqual(
                    set(stated), {counts[tier]},
                    f"{doc.name} states {sorted(set(stated))} for {tier}, "
                    f"and the table says {counts[tier]}",
                )

    def test_house_rules_are_declared(self):
        for rule in policy.HOUSE_RULES:
            self.assertIn(rule, policy.RULES)


class Locale(unittest.TestCase):
    """Rule 1.14 is off until a locale exists, and a bad locale is refused."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    @needs_data
    def test_the_plan_names_the_traps(self):
        dictionary = json.loads(DICTIONARY.read_text())
        plan = localize.plan("en-GB", dictionary)
        self.assertIn("en-GB", plan)
        self.assertIn("locale-en-GB.json", plan)
        # The direction of the map is the mistake this pass most easily makes.
        self.assertIn("The key is the word to flag", plan)

    @needs_data
    def test_the_candidate_list_holds_no_generated_inflections(self):
        # A loose finder produced "woulded" and "whicheverrer", and a list that
        # long stops being reviewed.
        dictionary = json.loads(DICTIONARY.read_text())
        words = localize.candidates(dictionary)
        self.assertLess(len(words), 120, "candidate list is too long to review")
        for junk in ("woulded", "whicheverrer", "withdrawed"):
            self.assertNotIn(junk, words)

    @needs_data
    def test_a_backwards_map_is_refused(self):
        dictionary = json.loads(DICTIONARY.read_text())
        target = DATA / "locale-xx-YY.json"
        target.write_text(json.dumps({
            "meta": {"locale": "xx-YY"},
            "spellings": {"colour": "color"},
        }))
        try:
            self.assertEqual(localize.check("xx-YY", dictionary), 1)
        finally:
            target.unlink(missing_ok=True)

    @needs_data
    def test_a_good_map_is_accepted_and_switches_rule_114_on(self):
        dictionary = json.loads(DICTIONARY.read_text())
        target = DATA / "locale-xx-YY.json"
        target.write_text(json.dumps({
            "meta": {"locale": "xx-YY"},
            "spellings": {"color": "colour", "center": "centre"},
        }))
        config = self.dir / ".ste-writing.json"
        config.write_text(json.dumps({"settings": {"locale": "xx-YY"}}))
        page = self.dir / "x.md"
        page.write_text("The color of the center.\n")
        try:
            self.assertEqual(localize.check("xx-YY", dictionary), 0)
            result = run_linter("--config", str(config), str(page))
            self.assertIn("rule 1.14", result.stdout)
            self.assertIn("colour", result.stdout)
        finally:
            target.unlink(missing_ok=True)


class Marker(unittest.TestCase):
    """--init and --add-word, so the skill can opt a repository in itself."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_init_writes_a_valid_marker(self):
        result = subprocess.run(
            [sys.executable, str(LINTER), "--init"],
            cwd=self.dir, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, CLEAN, result.stderr)
        written = self.dir / ".ste-writing.json"
        self.assertTrue(written.is_file())
        config = json.loads(written.read_text())
        self.assertEqual(list(config), ["meta", "settings", "words"])
        self.assertEqual(config["words"]["allow"], [])
        self.assertEqual(config["words"]["deny"], {})
        self.assertEqual(config["words"]["prefer"], {})
        self.assertEqual(config["settings"]["locale"], "")

    def test_init_refuses_to_overwrite(self):
        (self.dir / ".ste-writing.json").write_text("{}")
        result = subprocess.run(
            [sys.executable, str(LINTER), "--init"],
            cwd=self.dir, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, ERROR)

    def marker(self, **words) -> Path:
        path = self.dir / ".ste-writing.json"
        path.write_text(json.dumps({"words": words}))
        return path

    def run(self, marker: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(LINTER), "--config", str(marker), *args],
            capture_output=True, text=True,
        )

    def test_add_word_appends_without_duplicating(self):
        marker = self.marker(allow=["webhook"])
        for _ in range(2):
            self.run(marker, "--add-word", "endpoint", "webhook")
        self.assertEqual(
            json.loads(marker.read_text())["words"]["allow"], ["endpoint", "webhook"]
        )

    def test_deny_records_a_replacement_or_none(self):
        marker = self.marker()
        self.run(marker, "--deny", "utilise", "use")
        self.run(marker, "--deny", "synergy")
        self.assertEqual(
            json.loads(marker.read_text())["words"]["deny"],
            {"synergy": "", "utilise": "use"},
        )

    def test_prefer_merges_variants(self):
        marker = self.marker()
        self.run(marker, "--prefer", "repository", "repo")
        self.run(marker, "--prefer", "repository", "repos")
        self.assertEqual(
            json.loads(marker.read_text())["words"]["prefer"],
            {"repository": ["repo", "repos"]},
        )

    def test_old_key_names_are_refused_not_ignored(self):
        # A silently ignored glossary looks like the linter has gone mad.
        marker = self.dir / ".ste-writing.json"
        marker.write_text(json.dumps({"glossary": ["webhook"]}))
        page = self.dir / "x.md"
        page.write_text("A webhook.\n")
        result = self.run(marker, str(page))
        self.assertEqual(result.returncode, ERROR)
        self.assertIn("words.allow", result.stderr)

    def test_a_word_cannot_be_allowed_and_denied(self):
        marker = self.marker(allow=["utilise"], deny={"utilise": "use"})
        page = self.dir / "x.md"
        page.write_text("We utilise it.\n")
        result = self.run(marker, str(page))
        self.assertEqual(result.returncode, ERROR)
        self.assertIn("both", result.stderr)


@needs_rules
class RuleLookup(unittest.TestCase):
    """--rule replaces reading a section file by hand."""

    def test_a_real_rule_prints_its_tier_and_body(self):
        result = run_linter("--rule", "3.6")
        self.assertEqual(result.returncode, CLEAN)
        self.assertIn("Rule 3.6", result.stdout)
        self.assertIn("enforced", result.stdout)
        self.assertIn("active voice", result.stdout.lower())

    def test_a_house_rule_says_there_is_no_body(self):
        result = run_linter("--rule", "H.2")
        self.assertEqual(result.returncode, CLEAN)
        self.assertIn("house rule", result.stdout.lower())

    def test_an_unknown_rule_is_an_error(self):
        self.assertEqual(run_linter("--rule", "9.99").returncode, ERROR)

    def test_a_rule_arrives_with_its_examples(self):
        # The examples are what an agent fixes a finding from. Before this they
        # were prose inside a wall of prose, and nothing could reach them.
        result = run_linter("--rule", "3.6")
        self.assertIn("Examples:", result.stdout)
        self.assertIn("Non-STE", result.stdout)

    def test_the_statement_comes_first_and_the_text_is_asked_for(self):
        short = run_linter("--rule", "2.1").stdout
        full = run_linter("--rule", "2.1", "--full").stdout
        self.assertLess(len(short), len(full))
        self.assertIn("--full", short)

    def test_a_recommendation_is_readable_and_has_no_tier(self):
        # The subject index sends the reader to GR-5, so --rule has to open it.
        result = run_linter("--rule", "gr-5")
        self.assertEqual(result.returncode, CLEAN)
        self.assertIn("GR-5", result.stdout)
        self.assertIn("recommendation", result.stdout.lower())

    def test_a_subject_gives_the_rules_that_cover_it(self):
        result = run_linter("--subject", "hyphen")
        self.assertEqual(result.returncode, CLEAN)
        self.assertIn("8.2", result.stdout)

    def test_an_unknown_subject_is_an_error(self):
        self.assertEqual(run_linter("--subject", "kerning").returncode, ERROR)

    def test_the_rule_list_holds_every_rule(self):
        result = run_linter("--rules")
        self.assertEqual(result.returncode, CLEAN)
        for rule in policy.RULES:
            self.assertIn(rule, result.stdout)


class RuleParsing(unittest.TestCase):
    """The example and index parsers, on text written for the test.

    The standard is copyrighted, so nothing here quotes it. These check the
    shapes its typesetter uses, which is what the parsers actually depend on.
    """

    def test_the_refused_sentence_pairs_with_the_one_that_replaces_it(self):
        examples = build.parse_examples(
            "Examples:\n"
            "    Non-STE:      Perform an inspection of the valve.\n"
            "        STE:      Examine the valve.\n"
        )
        self.assertEqual(
            examples, [{"non_ste": "Perform an inspection of the valve.",
                        "ste": "Examine the valve."}]
        )

    def test_a_pair_printed_the_other_way_round_is_not_crossed(self):
        # Rule 3.6 prints the good sentence first. Assuming one order joined the
        # second half of one example to the first half of the next.
        examples = build.parse_examples(
            "    Active:       The pump moves the fuel.\n"
            "    Passive:      The fuel is moved by the pump.\n"
            "\n"
            "    Active:       The switch stops the motor.\n"
            "    Passive:      The motor is stopped by the switch.\n"
        )
        self.assertEqual(
            [example["ste"] for example in examples],
            ["The pump moves the fuel.", "The switch stops the motor."],
        )
        self.assertEqual(examples[0]["non_ste"], "The fuel is moved by the pump.")

    def test_a_sentence_that_wraps_stays_one_sentence(self):
        examples = build.parse_examples(
            "    Do not write: Make sure the valve that is on the left side of\n"
            "                  the pump is open.\n"
            "        WRITE:    Make sure that the left valve is open.\n"
        )
        self.assertEqual(
            examples[0]["non_ste"],
            "Make sure the valve that is on the left side of the pump is open.",
        )

    def test_a_counter_example_is_not_an_example(self):
        # A sentence the standard prints to refuse is not one to copy.
        self.assertEqual(
            build.parse_examples(
                "    STE:      Transmission stopped the data. (Incorrect, the "
                "agent is wrong.)\n"
            ),
            [],
        )

    def test_a_refused_sentence_with_no_replacement_is_commentary(self):
        self.assertEqual(
            build.parse_examples("    Non-STE:   The unit is operational.\n"), []
        )

    def test_index_targets_resolve_to_rule_ids(self):
        known = {"1.5", "1.6", "1.7", "2.1", "2.2", "8.2", "GR-5"}
        self.assertEqual(build.resolve_targets("8.2, 1.5", known), ["1.5", "8.2"])
        self.assertEqual(build.resolve_targets("2#", known), ["2.1", "2.2"])
        self.assertEqual(
            build.resolve_targets("1.5 thru 1.7", known), ["1.5", "1.6", "1.7"]
        )
        self.assertEqual(build.resolve_targets("9 – GR-5", known), ["GR-5"])
        # The typesetter sometimes prints the point as a comma.
        self.assertEqual(build.resolve_targets("1,5", known), ["1.5"])
        # A target that names no rule is dropped, not kept as text.
        self.assertEqual(build.resolve_targets("Part 2, Introduction", known), [])

    def test_rules_sort_in_reading_order(self):
        self.assertEqual(
            sorted(["1.10", "GR-2", "1.2", "2.1"], key=data_module.rule_sort_key),
            ["1.2", "1.10", "2.1", "GR-2"],
        )

    def test_rule_ids_are_taken_as_written_or_in_lower_case(self):
        self.assertEqual(data_module.normalize_rule_id("gr-5"), "GR-5")
        self.assertEqual(data_module.normalize_rule_id("h.2"), "H.2")
        self.assertEqual(data_module.normalize_rule_id("3.6"), "3.6")

    def test_a_rule_book_from_another_release_is_refused(self):
        with self.assertRaises(data_module.VersionError):
            data_module.RuleBook({"meta": {"version": "v99.0.0"}})
        with self.assertRaises(data_module.VersionError):
            data_module.RuleBook({"rules": {}})


@needs_rules
class RuleFile(unittest.TestCase):
    """data/ste-rules.json holds what ASD wrote, and only that."""

    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads(RULES.read_text())
        cls.book = data_module.RuleBook(cls.raw)

    def test_meta_comes_first_for_diagnosis(self):
        self.assertEqual(list(self.raw)[0], "meta")
        self.assertEqual(self.raw["meta"]["built_by"], "build-dictionary.py")
        self.assertEqual(self.raw["meta"]["version"], data_module.RULES_VERSION)

    def test_the_recorded_counts_match_the_content(self):
        counts = self.raw["meta"]["counts"]
        self.assertEqual(counts["rules"], len(self.book.ids("rule")))
        self.assertEqual(counts["recommendations"], len(self.book.ids("recommendation")))
        self.assertEqual(counts["index_subjects"], len(self.book.subjects))

    def test_the_rules_are_the_rules_the_table_names(self):
        # A count of 53 passes while a rule arrives under the wrong id. The two
        # sets have to be the same set, or a rule has no tier or cannot be read.
        declared = set(policy.RULES) - set(policy.HOUSE_RULES)
        self.assertEqual(set(self.book.ids("rule")), declared)

    def test_the_rules_hold_no_house_rule(self):
        # data/ is what ASD wrote. The house rules are ours, and the standard
        # never had an opinion about the word "seamless".
        for rule in policy.HOUSE_RULES:
            self.assertNotIn(rule, self.book.rules)

    def test_no_tier_is_written_into_the_data(self):
        # The tier is ours and it changes without a rebuild, so it is joined to
        # the record when the rule is printed. The old markdown baked it in and
        # the reader then deleted the line again.
        for record in self.book.rules.values():
            self.assertNotIn("tier", record)
            self.assertNotIn("check", record)

    def test_every_rule_opens_with_its_statement(self):
        for rule_id, record in self.book.rules.items():
            self.assertTrue(record["statement"].strip(), rule_id)
            flat = re.sub(r"\s+", " ", record["text"]).strip()
            self.assertTrue(flat.startswith(record["statement"]), rule_id)

    def test_every_recommendation_has_a_title(self):
        ids = self.book.ids("recommendation")
        self.assertEqual(len(ids), 8)
        for rule_id in ids:
            self.assertTrue(self.book.rule(rule_id)["title"].strip(), rule_id)

    def test_every_subject_points_at_a_rule_that_exists(self):
        for subject, entry in self.book.subjects.items():
            for rule_id in entry["rules"]:
                self.assertIn(rule_id, self.book.rules, subject)

    def test_the_examples_survived_the_layout(self):
        with_examples = [
            rule for rule, record in self.book.rules.items() if record["examples"]
        ]
        self.assertGreater(len(with_examples), 20)
        for record in self.book.rules.values():
            for example in record["examples"]:
                self.assertTrue(example["ste"].strip())
                self.assertNotIn("\n", example["ste"])


class Inflection(unittest.TestCase):
    def test_verb_forms(self):
        self.assertEqual(
            data_module.inflect("utilize", ["v"]),
            {"utilize", "utilizes", "utilized", "utilizing"},
        )

    def test_consonant_doubling(self):
        self.assertIn("fitted", data_module.inflect("fit", ["v"]))

    def test_plural_of_y_noun(self):
        self.assertIn("abnormalities", data_module.inflect("abnormality", ["n"]))


@needs_data
class Dictionary(unittest.TestCase):
    """Spot checks, one per parsing hazard that has actually bitten."""

    @classmethod
    def setUpClass(cls):
        cls.dictionary = json.loads(DICTIONARY.read_text())
        cls.approved = cls.dictionary["approved"]
        cls.alternatives = cls.dictionary["alternatives"]


    def test_meta_comes_first_for_diagnosis(self):
        self.assertEqual(list(self.dictionary)[0], "meta")
        for key in ("built_by", "version", "source_file", "validated", "counts"):
            self.assertIn(key, self.dictionary["meta"])

    def test_built_by_and_version_are_separate_fields(self):
        meta = self.dictionary["meta"]
        self.assertEqual(meta["built_by"], "build-dictionary.py")
        self.assertEqual(meta["version"], data_module.DICTIONARY_VERSION)
        self.assertNotIn(" ", meta["version"])

    def test_the_recorded_counts_match_the_content(self):
        counts = self.dictionary["meta"]["counts"]
        self.assertEqual(counts["approved_lemmas"], len(self.approved["lemmas"]))
        self.assertEqual(counts["unapproved_forms"], len(self.alternatives["forms"]))

    def test_the_dictionary_holds_no_house_words(self):
        # data/ is what ASD wrote. Our own additions merge at load time, so a
        # word that only we invented must not be in the built file.
        for word in ("methodology", "leverage", "endeavor"):
            self.assertNotIn(word, self.alternatives["lemmas"], word)

    def test_every_slop_core_word_is_in_the_standard(self):
        # Catches the list rotting: an entry the standard does not list as
        # non-approved does nothing at all.
        unmatched = data_module.unmatched_slop_core(self.alternatives["lemmas"])
        self.assertEqual(unmatched, set())

    def test_irregular_auxiliary_survives_its_three_line_entry(self):
        for word in ("be", "is", "was"):
            self.assertIn(word, self.approved["forms"], word)

    def test_verb_inflections_are_captured(self):
        for word in ("absorb", "absorbs", "absorbed"):
            self.assertIn(word, self.approved["forms"], word)

    def test_wrapped_headword_is_rejoined(self):
        self.assertIn("chemically", self.approved["forms"])

    def test_hyphen_wrapped_headword_is_rejoined(self):
        self.assertIn("electromagnetic", self.approved["forms"])
        self.assertNotIn("electromag- netic", self.approved["lemmas"])

    def test_replacements_are_paired_with_the_right_word(self):
        for word, expected in (("abate", "DECREASE"), ("accomplish", "DO")):
            got = self.alternatives["lemmas"][word]["replacements"]
            self.assertTrue(any(r.startswith(expected) for r in got), (word, got))


@needs_data
class Detection(unittest.TestCase):
    SLOP = (
        "We utilized a comprehensive methodology to facilitate the rollout; "
        "it was designed to ensure success.\n"
    )
    STE = (
        "Install the pump. If the pressure is more than 800 kPa, close the valve.\n"
        "Make sure that the seal is not damaged.\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def config(self, **words) -> str:
        """A marker in the sectioned shape, with only the words section set."""
        path = self.dir / ".ste-writing.json"
        path.write_text(json.dumps({"words": words}))
        return str(path)

    def test_slop_fails_the_run(self):
        result = run_linter("-", stdin=self.SLOP)
        self.assertEqual(result.returncode, ENFORCED)
        for word in ("utilize", "facilitate", "ensure", "methodology"):
            self.assertIn(word, result.stdout, word)

    def test_ordinary_words_are_left_alone(self):
        # The whole non-approved list holds "way", "every", and "under". Using it
        # whole would make the linter unusable, so it must not fire on these.
        text = "The agent drops the rule under load, so every way through fails.\n"
        result = run_linter("-", stdin=text)
        for word in ("way", "every", "under", "load"):
            self.assertNotIn(f"“{word}”", result.stdout, word)

    def test_glossary_does_not_silence_the_marketing_check(self):
        config = self.config(allow=["robust"])
        target = self.dir / "x.md"
        target.write_text("The parser is robust.\n")
        result = run_linter("--config", config, str(target))
        self.assertIn("rule H.1", result.stdout)

    def lint_text(self, text: str, **config) -> str:
        path = self.config(**config) if config else None
        target = self.dir / "x.md"
        target.write_text(text)
        args = ["--config", path] if path else []
        return run_linter(*args, str(target)).stdout

    def test_no_spelling_check_without_a_locale(self):
        # The skill ships no spelling list. Rule 1.14 is off until a locale
        # exists, so a project that writes any variety of English is left alone.
        self.assertNotIn("rule 1.14", self.lint_text("Set the colour of the label.\n"))
        self.assertNotIn("rule 1.14", self.lint_text("Set the color of the label.\n"))

    def test_phrasal_verb_is_caught(self):
        self.assertIn("rule 9.3", self.lint_text("Spin up the server now.\n"))

    def test_hedge_is_flagged(self):
        self.assertIn("rule H.3", self.lint_text("It is worth noting that this works.\n"))

    def test_inconsistent_term_is_flagged(self):
        output = self.lint_text(
            "Clone the repo now.\n",
            prefer={"repository": ["repo"]},
        )
        self.assertIn("rule 1.11", output)
        self.assertIn("repository", output)

    def test_deny_beats_the_dictionary(self):
        # A project may refuse a word the standard approves. That decision has
        # to be read before anything can permit the word.
        output = self.lint_text("Check the color of the part.\n",
                                deny={"color": "colour"})
        self.assertIn("rule H.4", output)
        self.assertIn("colour", output)

    def test_deny_with_no_replacement_still_reports(self):
        output = self.lint_text("A synergy of teams.\n", deny={"synergy": ""})
        self.assertIn("rule H.4", output)

    def test_allow_matches_the_plural_of_a_declared_word(self):
        output = self.lint_text("The endpoints are ready.\n", allow=["endpoint"])
        self.assertNotIn("endpoint", output)

    def test_noun_cluster_is_flagged(self):
        output = self.lint_text(
            "Replace the engine oil pressure sensor cable now.\n",
            allow=["engine", "oil", "pressure", "sensor", "cable"],
        )
        self.assertIn("rule 2.1", output)



@needs_data
class ExitCodes(unittest.TestCase):
    def test_clean_is_zero(self):
        self.assertEqual(run_linter("-", stdin="Install the pump.\n").returncode, CLEAN)

    def test_enforced_is_one(self):
        result = run_linter("-", stdin="We utilized it.\n")
        self.assertEqual(result.returncode, ENFORCED)

    def test_flagged_only_is_two(self):
        # Rule 3.7 is flagged, so it reports without failing the run.
        result = run_linter("-", stdin="Do the maintenance of the unit.\n")
        self.assertEqual(result.returncode, FLAGGED, result.stdout)

    def test_fail_on_flagged_promotes_it(self):
        result = run_linter("--fail-on-flagged", "-", stdin="Do the maintenance of the unit.\n")
        self.assertEqual(result.returncode, ENFORCED)

    def test_missing_file_is_a_tool_error(self):
        self.assertEqual(run_linter("no-such-file.md").returncode, ERROR)

    def test_json_output_parses(self):
        result = run_linter("--format", "json", "-", stdin="We utilized it.\n")
        report = json.loads(result.stdout)
        self.assertGreater(report["enforced"], 0)
        finding = report["files"]["<stdin>"][0]
        for key in ("rule", "tier", "line", "column", "text", "suggestion"):
            self.assertIn(key, finding)


class MissingDictionary(unittest.TestCase):
    """Exit 3 must never soften into exit 0. That is the gate looking green."""

    @needs_data
    def test_an_incompatible_dictionary_gives_exit_three(self):
        # Not a crash halfway through a file, and never a quiet pass.
        original = DICTIONARY.read_text()
        stale = json.loads(original)
        stale["meta"]["version"] = "v99.0.0"
        DICTIONARY.write_text(json.dumps(stale))
        try:
            result = run_linter("-", stdin="Anything at all.\n")
        finally:
            DICTIONARY.write_text(original)
        self.assertEqual(result.returncode, ERROR)
        self.assertIn("v99.0.0", result.stderr)
        self.assertIn("build-dictionary.py", result.stderr)

    @unittest.skipUnless(have_data, "needs data/ present so it can be hidden")
    def test_hidden_dictionary_gives_exit_three(self):
        hidden = DATA.parent / ".data-test-hidden"
        DATA.rename(hidden)
        try:
            result = run_linter("-", stdin="Anything at all.\n")
        finally:
            hidden.rename(DATA)
        self.assertEqual(result.returncode, ERROR)
        self.assertIn("build-dictionary.py", result.stderr)


@needs_data
class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.git("init", "-q", ".")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        (self.repo / "doc.md").write_text("The agent reads the file.\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")

    def git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=self.repo, capture_output=True, check=False,
            env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"},
        )

    def mark(self, **values) -> None:
        (self.repo / ".ste-writing.json").write_text(
            json.dumps({"words": {"allow": values.get("glossary", [])}})
        )

    def call(self, stop_hook_active: bool = False) -> dict:
        payload = {
            "hook_event_name": "Stop",
            "cwd": str(self.repo),
            "stop_hook_active": stop_hook_active,
        }
        result = subprocess.run(
            [sys.executable, str(HOOKS / "ste-hook.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout or "{}")

    def test_inert_without_a_marker(self):
        (self.repo / "doc.md").write_text("We utilized it.\n")
        self.assertEqual(self.call(), {})

    def test_silent_when_nothing_changed(self):
        self.mark()
        self.git("add", "-A")
        self.git("commit", "-qm", "marker")
        self.assertEqual(self.call(), {})

    def test_blocks_on_changed_prose(self):
        self.mark()
        (self.repo / "doc.md").write_text("We utilized a comprehensive approach.\n")
        answer = self.call()
        self.assertEqual(answer.get("decision"), "block")
        self.assertIn("doc.md:1:", answer["reason"])
        self.assertIn("rule H.2", answer["reason"])

    def test_releases_on_the_second_pass(self):
        self.mark()
        (self.repo / "doc.md").write_text("We utilized a comprehensive approach.\n")
        answer = self.call(stop_hook_active=True)
        self.assertNotIn("decision", answer)

    def test_reminder_arrives_when_the_lint_passes(self):
        self.mark()
        (self.repo / "doc.md").write_text("The agent reads the file and stops.\n")
        answer = self.call()
        self.assertNotIn("decision", answer)
        self.assertIn("1.8", answer["hookSpecificOutput"]["additionalContext"])

    def test_only_changed_files_are_linted(self):
        # Adoption stays incremental: prose already committed is left alone.
        (self.repo / "legacy.md").write_text("We utilized a comprehensive approach.\n")
        self.mark()
        self.git("add", "-A")
        self.git("commit", "-qm", "legacy")
        self.assertEqual(self.call(), {})

        (self.repo / "new.md").write_text("We utilized it.\n")
        self.assertEqual(self.call().get("decision"), "block")

    def test_missing_dictionary_blocks_with_a_setup_hint(self):
        self.mark()
        (self.repo / "doc.md").write_text("We utilized it.\n")
        hidden = DATA.parent / ".data-test-hidden"
        DATA.rename(hidden)
        try:
            answer = self.call()
        finally:
            hidden.rename(DATA)
        self.assertEqual(answer.get("decision"), "block")
        self.assertIn("build-dictionary.py", answer["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
