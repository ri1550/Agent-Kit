# Agent-Kit
Skills, Scripts and Workflows that make coding agents work in a structured manner.

## The Idea
Most skills and MCP servers are heuristics. They tell the agent what to do and
trust it to remember and apply the rules the same way every time. That trust does
not hold. An agent under load drops the rule, or applies half of it, or reasons
its way around it.

Better instructions do not fix this. Structure does. Put the rule where the agent
must meet it, and add scripts that check the result.

The instruction guides the work. The scripts decide whether the work passes. An
agent can talk its way past a guideline. It cannot talk its way past a script.
The goal is agent work that is repeatable.

### What The Structure Looks Like
Each skill here has three parts:
1. A `SKILL.md` file that tells the agent how to work.
2. One or more scripts that test the output against the same rules.
3. A hook that runs the scripts, so nothing depends on the agent choosing to.

The scripts are the part that runs the same way every time.

## Contents
### agent-skills/
Each skill is a directory that holds a `SKILL.md` file and the scripts the skill
needs.

- **ste-writing** — rewrites prose into ASD-STE100 Simplified Technical English.
  Use it on documentation, READMEs, pull request text, error messages, and
  release notes. It does not apply to code. A linter decides whether the text
  passes, and a Stop hook holds the turn open until it does.

## How To Install
Each skill in `agent-skills` is one directory. Take the whole directory, never
the `SKILL.md` file alone. The directory keeps `SKILL.md` and `scripts/`
together, so the script paths still resolve. Claude Code uses `~/.claude/skills/`
for personal skills, and `.claude/skills/` for project skills. Other agents use
their own location, so read the documentation for the agent you use.

Copy the skill:
```bash
git clone git@github.com:ri1550/Agent-Kit.git
cp -r Agent-Kit/agent-skills/<skill> ~/.claude/skills/
```

Or link it, which is what I do:
```bash
git clone git@github.com:ri1550/Agent-Kit.git
ln -s "$PWD/Agent-Kit/agent-skills/<skill>" ~/.claude/skills/<skill>
```

A symlink keeps one copy of the source. You edit the file in the local repository
and the change takes effect at once, and `git pull` updates every skill you
linked.

## Set Up ste-writing
This skill needs three steps before it works. Do them once.

**1. Build the dictionary.** The repository ships no content from ASD-STE100.
ASD holds the copyright, and its free-use grant covers named organizations, not a
public repository. So you download the standard and build the data on your own
machine.

Get ASD-STE100 Issue 9 from [asd-ste100.org](https://asd-ste100.org). It is free,
but you must make an account. Then:

```bash
python3 agent-skills/ste-writing/scripts/build-dictionary.py \
  --pdf ~/Downloads/ASD-STE100_ISSUE9.pdf
```

This needs `pdftotext`, which comes with poppler. It writes
`agent-skills/ste-writing/data/`, which `.gitignore` covers. Rebuild it after you
clone.

That directory holds `ste-dictionary.json` and the rule files, and nothing else.
It is the words of the standard and only that: our own word lists stay in
`assets/`, where an edit takes effect on the next run rather than after a
rebuild. The dictionary starts with a `meta` block that names the PDF it came
from and the counts it extracted. Run `head` on the file to see what you have.

The script checks its own work and writes nothing if the extraction falls short.
A dictionary that is quietly half complete is worse than no dictionary, because
strict mode would then pass text it never checked.

**2. Mark the repositories you want.** Copy
`agent-skills/ste-writing/assets/marker-template.json` to the root of a
repository as `.ste-writing.json`, then add that project's technical nouns to
`glossary`. Commit it. The file is the opt-in switch and the project settings in
one. Delete it to opt out.

Set `mode` to the default for the repository, and list the paths that must be
stricter in `strict_paths`. The mode belongs to the text, not to the repository.
A runbook is still a runbook in a repository that is mostly prose, so the linter
reads the mode for each file.

**3. Install the hook, once.** Merge
`agent-skills/ste-writing/hooks/settings-snippet.json` into
`~/.claude/settings.json` and correct the path. The hook does nothing in a
repository that has no marker file, so a global install switches nothing on by
itself.

### The checks
| Check | What it does | Blocks? |
|---|---|---|
| `ste-lint.py` | Reads prose and reports each finding with its rule id and its `file:line:column`. Two modes: `ste-strict` runs the approved-word allowlist, `ste-general` runs the slop list | Yes, on an enforced rule |
| `ste-hook.py` | Stop hook. Lints the prose files that differ from `HEAD` and holds the turn open until they pass | Yes, once. It releases on the second pass so it cannot loop |
| `build-dictionary.py` | Turns your copy of the PDF into the word lists and the rule files | Yes, if the extraction falls short |
| `remind.py` | Prints the rules no script can check, after the lint passes | Never |
| `tests/test_ste.py` | 55 tests over the word counting, the segmentation, both modes, every exit code, and the hook | Yes, on a failure |

Run the linter by hand at any time:
```bash
python3 agent-skills/ste-writing/scripts/ste-lint.py --mode ste-general README.md
echo $?   # 0 clean · 1 enforced · 2 flagged · 3 could not run
```

Run the tests the same way. The tests that need the dictionary report as skipped
until you build it:
```bash
python3 agent-skills/ste-writing/tests/test_ste.py
```

Exit 3 never becomes exit 0. A linter that passes because it has no dictionary is
worse than no linter, because the gate still looks green.

### What it does not do
ASD-STE100 has 53 writing rules. The linter enforces 14 and flags 22 more that it
can see but cannot judge. Four more tell it how to count words, so it applies
those to the word count and never reports them as a fault. The last 13 need a
person, and `remind.py` prints them when the lint passes.
`assets/rule-tiers.json` says which rule sits where.

This is not a certified STE checker. It fixes the form of the writing. It cannot
make a hollow paragraph true.

## Credits
- **ste-writing** — came from [@woosal1337](https://github.com/woosal1337)'s
  video, "The Cure for AI Slop is a 1986 Aircraft Manual". I kept the idea and
  rebuilt the skill around an extractor, a linter with rule ids and exit codes,
  and a hook. The first skill and linter carry an MIT license, Copyright (c)
  2026 Ege Çelebi.
  [Source](https://github.com/woosal1337/blog/tree/main/videos/ep01-the-cure-for-ai-slop).
