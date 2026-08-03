---
name: ste-writing
description: Rewrite prose (docs, READMEs, PR descriptions, error messages, release notes, comments — never code) into ASD-STE100 Simplified Technical English to remove "AI slop". Use when asked to make writing not sound like AI, make docs clear or plain, enforce a controlled writing style, or write technical documentation that reads human. Two modes — ste-strict (procedures, safety) and ste-general (everything else) — both checked by a linter that decides pass or fail.
---

# ste-writing

Write prose in ASD-STE100 Simplified Technical English. This applies to
documentation, READMEs, pull request text, error messages, release notes, and
comments. It does not apply to code, identifiers, or command syntax.

Do not use it for marketing copy, essays, or anything that needs a voice. STE
removes voice on purpose.

**The linter decides whether the work passes, not you.** Do not report prose as
done until `ste-lint.py` exits 0. It reads the same rules you do, and it does not
get tired.

## Setup

Run this first. If `scripts/ste-lint.py` exits 3, one of these steps is not
complete.

1. **Build the dictionary.** The repository ships no content from the standard,
   because ASD holds the copyright. Download ASD-STE100 Issue 9 from
   https://asd-ste100.org. It is free, but you must make an account. Then:

   ```bash
   python3 scripts/build-dictionary.py --pdf /path/to/ASD-STE100_ISSUE9.pdf
   ```

   This writes `data/`, which is never committed. It needs `pdftotext` from
   poppler. Rebuild it after you clone.

2. **Switch this repository on.** Copy `assets/marker-template.json` to the
   repository root as `.ste-writing.json`, set `mode`, and add this project's
   technical nouns to `glossary`. Commit it. That file is the opt-in switch and
   the project's settings in one. Without it the Stop hook does nothing.

3. **Install the gate, once.** Merge `hooks/settings-snippet.json` into
   `~/.claude/settings.json`. The hook is inert in every repository that has no
   marker file, so installing it globally switches nothing on by itself.

## Pick the mode

| Mode | Use it for | What fails the run |
|---|---|---|
| `ste-strict` | Procedures, runbooks, safety text, error messages | The structure rules, plus the approved-word allowlist. Every word must be in the STE dictionary or in this project's glossary. |
| `ste-general` | READMEs, pull request text, docs, release notes, comments | The structure rules, plus the slop list. It leaves ordinary English words alone. |

When the text mixes both, split it. Write the procedure in `ste-strict` and the
prose around it in `ste-general`.

## The loop

Follow this in order. Step 4 is not optional and its result is not negotiable.

1. **Check that the text is in scope.** Code, identifiers, command syntax,
   marketing copy, and anything that needs a voice are out. Say so and stop.
2. **Pick the mode** from the table above, or take it from `.ste-writing.json`.
3. **Write the text.** Write only the text the user asked for. Add no preamble,
   no summary, and no closing remarks.
4. **Run the linter.**

   ```bash
   python3 scripts/ste-lint.py --mode <mode> --format json <file>
   ```

   Exit codes: `0` clean · `1` the text breaks an enforced rule · `2` flagged
   findings only · `3` the linter could not run.

   Exit 3 is never a pass. It means the gate is off, so fix the setup first.

5. **Fix each finding.** Every finding carries a rule id. Look the id up in
   `data/rule-index.md`, then open **only** the section file it points to. Do not
   read the other rule files. Findings also carry the replacement the standard
   itself suggests, so use it.
6. **Run the linter again.** Repeat until it exits 0.
7. **Walk the checklist below**, because no script can check it.

If a finding is wrong, say which one and why. Do not ignore it quietly, and do
not edit the rule tiers to remove it.

## What the linter cannot check

The linter enforces structure. These need you, and `scripts/remind.py` prints
them when the lint passes:

- **1.8** Technical nouns come from this project's glossary, not invented on the spot.
- **1.9** Each technical noun is short and easy to understand.
- **4.1** Every sentence says one thing, and says it plainly.
- **6.1** Information arrives in the order the reader needs it.
- **6.4** Each paragraph holds one topic.
- **9.2** Every approved word keeps its approved meaning.
- **9.4** Terminology matches the rest of the document.

This skill fixes the form of the writing. It cannot make a hollow paragraph true.

## Write it right the first time

The linter is the gate, not the method. Applying these while drafting keeps most
findings from happening.

- One name for one thing. Do not call the same item by two names.
- Use the short common word: `start` not `begin`, `use` not `utilize`, `help` not
  `facilitate`, `make sure` not `ensure`, `before` not `prior to`, `about` not
  `regarding`, `get` not `obtain`, `show` not `demonstrate`, `also` not
  `additionally`.
- Active voice. `The parser reads the file`, not `the file is read by the parser`.
- Use a verb for an action. `analyze the log`, not `perform an analysis of the log`.
- One instruction per sentence. 20 words for an instruction, 25 for description.
- No contractions. No semicolons. American spelling.
- One topic per paragraph, six sentences at most.
- For steps, use a numbered list, one action per item, in the command form.
- Put a condition before its command.
- No marketing adjectives: `seamless`, `robust`, `powerful`, `effortless`, `world-class`.

## Files

| Path | What it is |
|---|---|
| `scripts/ste-lint.py` | The gate. Rule ids, `file:line:column`, exit codes |
| `scripts/build-dictionary.py` | Turns your copy of the PDF into `data/` |
| `scripts/remind.py` | Prints the checklist above. Never blocks |
| `hooks/ste-hook.py` | Stop hook. Inert unless the repository has a marker file |
| `assets/rule-tiers.json` | The tier of each rule: enforced, flagged, or judgment |
| `assets/house-style.json` | Our slop list, for the words STE never documents |
| `data/rule-index.md` | Rule id to section file. The build step writes it |

ASD holds the copyright to the standard. Do not paste it into a file, an issue,
or a commit.
