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

DICTIONARY = DATA / "ste-dictionary.json"
have_data = DICTIONARY.is_file()
needs_data = unittest.skipUnless(have_data, "no data/, run build-dictionary.py first")


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
        cls.house = json.loads((SKILL / "assets" / "house-style.json").read_text())

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
        unmatched = data_module.unmatched_slop_core(
            self.alternatives["lemmas"], self.house
        )
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
class Modes(unittest.TestCase):
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

    def config(self, **values) -> str:
        path = self.dir / ".ste-writing.json"
        path.write_text(json.dumps(values))
        return str(path)

    def test_general_fails_on_slop(self):
        result = run_linter("--mode", "ste-general", "-", stdin=self.SLOP)
        self.assertEqual(result.returncode, ENFORCED)
        for word in ("utilize", "facilitate", "ensure", "methodology"):
            self.assertIn(word, result.stdout, word)

    def test_general_leaves_ordinary_words_alone(self):
        # The whole non-approved list holds "way", "every", and "under". Using it
        # whole would make ste-general unusable, so it must not fire on these.
        text = "The agent drops the rule under load, so every way through fails.\n"
        result = run_linter("--mode", "ste-general", "-", stdin=text)
        for word in ("way", "every", "under", "load"):
            self.assertNotIn(f"“{word}”", result.stdout, word)

    def test_strict_passes_when_the_glossary_declares_the_nouns(self):
        config = self.config(
            mode="ste-strict",
            glossary=["pump", "valve", "pressure", "seal", "kPa"],
        )
        target = self.dir / "good.md"
        target.write_text(self.STE)
        result = run_linter("--mode", "ste-strict", "--config", config, str(target))
        self.assertEqual(result.returncode, CLEAN, result.stdout)

    def test_strict_fails_on_the_same_text_without_the_glossary(self):
        config = self.config(mode="ste-strict", glossary=[])
        target = self.dir / "good.md"
        target.write_text(self.STE)
        result = run_linter("--mode", "ste-strict", "--config", config, str(target))
        self.assertEqual(result.returncode, ENFORCED)
        self.assertIn("rule 1.1", result.stdout)

    def test_glossary_does_not_silence_the_marketing_check(self):
        config = self.config(mode="ste-general", glossary=["robust"])
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

    def test_british_spelling_is_caught(self):
        output = self.lint_text("Set the colour of the label.\n")
        self.assertIn("rule 1.14", output)
        self.assertIn("color", output)

    def test_american_spelling_is_clean(self):
        self.assertNotIn("rule 1.14", self.lint_text("Set the color of the label.\n"))

    def test_phrasal_verb_is_caught(self):
        self.assertIn("rule 9.3", self.lint_text("Spin up the server now.\n"))

    def test_hedge_is_flagged(self):
        self.assertIn("rule H.3", self.lint_text("It is worth noting that this works.\n"))

    def test_inconsistent_term_is_flagged(self):
        output = self.lint_text(
            "Clone the repo now.\n",
            mode="ste-general",
            one_name_for_one_thing={"repository": ["repo"]},
        )
        self.assertIn("rule 1.11", output)
        self.assertIn("repository", output)

    def test_noun_cluster_is_flagged(self):
        output = self.lint_text(
            "Replace the engine oil pressure sensor cable now.\n",
            mode="ste-general",
            glossary=["engine", "oil", "pressure", "sensor", "cable"],
        )
        self.assertIn("rule 2.1", output)


@needs_data
class ModeResolution(unittest.TestCase):
    """The mode belongs to the text. A runbook is strict in a general repo."""

    STRICT_ONLY = "Install the widget.\n"  # "widget" is in no dictionary

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        (self.dir / ".ste-writing.json").write_text(
            json.dumps({"mode": "ste-general", "strict_paths": ["runbooks/**"]})
        )
        (self.dir / "runbooks").mkdir()
        (self.dir / "README.md").write_text(self.STRICT_ONLY)
        (self.dir / "runbooks" / "restart.md").write_text(self.STRICT_ONLY)

    def lint(self, *names: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(LINTER), "--format", "json", *names],
            cwd=self.dir, capture_output=True, text=True,
        )

    def test_default_mode_applies_outside_the_strict_paths(self):
        report = json.loads(self.lint("README.md").stdout)
        self.assertEqual(report["modes"]["README.md"], "ste-general")

    def test_strict_paths_win_over_the_default_mode(self):
        name = "runbooks/restart.md"
        report = json.loads(self.lint(name).stdout)
        self.assertEqual(report["modes"][name], "ste-strict")

    def test_one_run_can_mix_both_modes(self):
        result = self.lint("README.md", "runbooks/restart.md")
        report = json.loads(result.stdout)
        self.assertEqual(
            set(report["modes"].values()), {"ste-general", "ste-strict"}
        )
        # The same text passes as general prose and fails as a strict procedure.
        self.assertEqual(report["files"]["README.md"], [])
        self.assertTrue(report["files"]["runbooks/restart.md"])
        self.assertEqual(result.returncode, ENFORCED)

    def test_explicit_mode_overrides_the_paths(self):
        report = json.loads(
            subprocess.run(
                [sys.executable, str(LINTER), "--mode", "ste-general",
                 "--format", "json", "runbooks/restart.md"],
                cwd=self.dir, capture_output=True, text=True,
            ).stdout
        )
        self.assertEqual(report["modes"]["runbooks/restart.md"], "ste-general")


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
        self.assertEqual(report["mode"], "ste-general")
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
            json.dumps({"mode": "ste-general", **values})
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
