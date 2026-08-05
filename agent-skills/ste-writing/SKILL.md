---
name: ste-writing
description: Rewrite prose (docs, READMEs, PR descriptions, error messages, release notes, comments — never code) into ASD-STE100 Simplified Technical English to remove "AI slop". Use when asked to make writing not sound like AI, make docs clear or plain, enforce a controlled writing style, or write technical documentation that reads human. A linter decides whether the text passes, and a Stop hook holds the turn open until it does.
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

1. **Build the dictionary.** The skill ships no content from the standard,
   because ASD holds the copyright. Download ASD-STE100 Issue 9 from
   https://asd-ste100.org. It is free, but you must make an account. Then:

   ```bash
   python3 <skill>/scripts/build-dictionary.py --pdf /path/to/ASD-STE100_ISSUE9.pdf
   ```

   `<skill>` is the directory that holds this file. Resolve it from the path of
   `SKILL.md`, because the working directory is the user's project, not the
   skill. Every other path here is relative to `<skill>` for the same reason.

   This writes `<skill>/data/`, which is never committed. It needs `pdftotext`
   from poppler. Rebuild it after you clone.

2. **Switch the repository on.** From the root of the project:

   ```bash
   python3 <skill>/scripts/ste-lint.py --init
   ```

   That writes `.ste-writing.json`, which is the marker the hook looks for and
   the place this project's own words live. Commit it. Delete it to opt out.

3. **Install the gate, once.** Merge `hooks/settings-snippet.json` into
   `~/.claude/settings.json`. The hook is inert in every repository that has no
   marker file, so installing it globally switches nothing on by itself.

## The loop

Follow this in order. Step 3 is not optional and its result is not negotiable.

1. **Check that the text is in scope.** Code, identifiers, command syntax,
   marketing copy, and anything that needs a voice are out. Say so and stop.
2. **Write the text.** Write only the text the user asked for. Add no preamble,
   no summary, and no closing remarks.
3. **Run the linter.**

   ```bash
   python3 <skill>/scripts/ste-lint.py --format json <file>
   ```

   Exit codes: `0` clean · `1` the text breaks an enforced rule · `2` flagged
   findings only · `3` the linter could not run.

   Exit 3 is never a pass. It means the gate is off, so fix the setup first.

4. **Fix each finding.** Every finding carries the rule id, the offending text,
   the rule in one line (`short`), and usually the replacement the standard
   itself suggests. Fix it from those when they are enough.

   When they are not enough, read the rule:

   ```bash
   python3 <skill>/scripts/ste-lint.py --rule 3.6
   ```

   An id that starts with `H` is a house rule. ASD did not write those, so
   there is no rule text to read and the suggestion is the whole answer.

5. **Run the linter again.** Repeat until it exits 0.
6. **Walk the checklist.** Run `python3 <skill>/scripts/remind.py` and confirm
   each item it prints. No script can check those rules.

If a finding is wrong, say which one and why. Do not ignore it quietly, and do
not edit `scripts/ste_policy.py` to remove it.

## The words this project decided on

`.ste-writing.json` holds three word sections, and the linter reads them in this
order. Each one is a decision. Record it once, and stop fixing the same word
in every file.

| Section | Effect | Command |
|---|---|---|
| `deny` | Refuses a word here, even one the standard approves | `--deny utilise use` |
| `allow` | Lets you use a word the dictionary does not hold, and teaches rule 2.1 that it is a noun | `--add-word endpoint webhook` |
| `prefer` | One name for one thing, per rule 1.11 | `--prefer repository repo` |

To see every word this project trips on, grouped so you decide each one once:

```bash
python3 <skill>/scripts/ste-lint.py --triage docs/
```

Use `allow` for the words the project decided on, not for the words you did not
want to fix. A word cannot be in both `allow` and `deny`, and the linter refuses
a marker file that says so.

## What the linter cannot check

Of the 53 writing rules, the linter enforces 13 and flags 4 more that it can see
but cannot judge. Four tell it how to count words. The rest need a person:
whether a technical noun was the right choice, whether the information arrives
in a useful order, whether a paragraph holds one topic.

`scripts/remind.py` prints those, and `scripts/ste_policy.py` says which rule
sits in which tier.

This skill fixes the form of the writing. It cannot make a hollow paragraph true.

## Writing in another variety of English

Rule 1.14 asks for American spelling, which is right for the standard and wrong
for a team that does not write it. The skill ships no spelling list. Instead it
builds one, once, per language:

```bash
python3 <skill>/scripts/localize.py --en-GB           # the work plan
python3 <skill>/scripts/localize.py --en-GB --check   # check what you wrote
```

The plan gives you the words from the dictionary that could differ, and names
the traps. You decide each one and write `data/locale-en-GB.json`. Then set
`"locale": "en-GB"` in `.ste-writing.json`. Until you do, there is no spelling
check at all.

## Write it right the first time

The linter is the gate, not the method. These keep most findings from happening.

- One name for one thing. Do not call the same item by two names.
- Use the short common word: `start` not `begin`, `use` not `utilize`, `help` not
  `facilitate`, `make sure` not `ensure`, `before` not `prior to`, `about` not
  `regarding`, `get` not `obtain`, `show` not `demonstrate`, `also` not
  `additionally`.
- Active voice. `The parser reads the file`, not `the file is read by the parser`.
- Use a verb for an action. `analyze the log`, not `perform an analysis of the log`.
- One instruction per sentence. 20 words for an instruction, 25 for description.
- No contractions. No semicolons.
- One topic per paragraph, six sentences at most.
- For steps, use a numbered list, one action per item, in the command form.
- Put a condition before its command.
- No marketing adjectives: `seamless`, `robust`, `powerful`, `effortless`, `world-class`.

## Files

| Path | What it is |
|---|---|
| `scripts/ste-lint.py` | The gate. Rule ids, `file:line:column`, exit codes |
| `scripts/ste_policy.py` | Which rules the linter enforces, and our own word lists |
| `scripts/ste_data.py` | The word lists that the scripts share |
| `scripts/build-dictionary.py` | Turns your copy of the PDF into `data/` |
| `scripts/localize.py` | Plans and checks a locale |
| `scripts/remind.py` | Prints the checklist above. Never blocks |
| `hooks/ste-hook.py` | Stop hook. Inert unless the repository has a marker file |
| `data/ste-dictionary.json` | The words of the standard. The build step writes it |
| `.ste-writing.json` | The marker, and this project's own words |

Two dictionaries, and they do not mix. `data/ste-dictionary.json` holds what ASD
wrote, and only the build step writes there. `.ste-writing.json` holds what the
project decided. Everything else is code.

ASD holds the copyright to the standard. Do not paste it into a file, an issue,
or a commit.
