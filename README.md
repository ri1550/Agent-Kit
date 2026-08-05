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
It is the words of the standard and only that. Our own judgements live in
`scripts/ste_policy.py`, and the project's words live in `.ste-writing.json`.
Two dictionaries, and they do not mix.

The dictionary starts with a `meta` block that names the PDF it came from, the
counts it extracted, and the `version` of the build format. Run `head` on the
file to see what you have.

The linter reads that version before it reads a word. A dictionary built by an
older format exits 3 and tells you to build it again. That beats a crash part
way through a file.

The script checks its own work and writes nothing if the extraction falls short.
A dictionary that is quietly half complete is worse than no dictionary, because
the linter would then pass text it never checked.

**2. Mark the repositories you want.** From the root of the project:

```bash
python3 agent-skills/ste-writing/scripts/ste-lint.py --init
```

That writes `.ste-writing.json`, which is the marker the hook looks for and the
place the project's own words live. Commit it. Delete it to opt out.

It has the same shape as the dictionary: `meta` first, so `head` on it says what
wrote the file, then `settings` and `words`. The `words` section holds three
decisions, which the linter reads in order:

```bash
ste-lint.py --deny utilise use          # refuse a word here, even an approved one
ste-lint.py --add-word endpoint         # permit a word the dictionary lacks
ste-lint.py --prefer repository repo    # one name for one thing
ste-lint.py --triage docs/              # every word to decide, grouped
```

There is no stored list of flagged words. `--triage` computes it from the prose,
so it cannot claim a word is a problem after you delete the sentence.

**3. Install the hook, once.** Merge
`agent-skills/ste-writing/hooks/settings-snippet.json` into
`~/.claude/settings.json` and correct the path. The hook does nothing in a
repository that has no marker file, so a global install switches nothing on by
itself.

### The checks
| Check | What it does | Blocks? |
|---|---|---|
| `ste-lint.py` | Reads prose and reports each finding with its rule id, its `file:line:column`, and the rule in one line. `--rule <id>` prints the full rule | Yes, on an enforced rule |
| `ste-hook.py` | Stop hook. Lints the prose files that differ from `HEAD` and holds the turn open until they pass | Yes, once. It releases on the second pass so it cannot loop |
| `build-dictionary.py` | Turns your copy of the PDF into the word lists and the rule files | Yes, if the extraction falls short |
| `localize.py` | Plans a locale for the dictionary, then checks what the agent wrote | Yes, on a bad locale file |
| `remind.py` | Prints the rules no script can check, after the lint passes | Never |
| `tests/test_ste.py` | Tests over the word counting, the segmentation, every exit code, the locale contract, and the hook | Yes, on a failure |

Run the linter by hand at any time:
```bash
python3 agent-skills/ste-writing/scripts/ste-lint.py README.md
echo $?   # 0 clean · 1 enforced · 2 flagged · 3 could not run
```

Run the tests the same way. The tests that need the dictionary report as skipped
until you build it:
```bash
python3 agent-skills/ste-writing/tests/test_ste.py
```

Exit 3 never becomes exit 0. A linter that passes because it has no dictionary is
worse than no linter, because the gate still looks green.

### Writing in another variety of English
Rule 1.14 asks for American spelling, which is right for the standard and wrong
for a team that does not write it. The skill ships no spelling list. It builds
one instead, once, per language:

```bash
python3 agent-skills/ste-writing/scripts/localize.py --en-GB
python3 agent-skills/ste-writing/scripts/localize.py --en-GB --check
```

The plan gives an agent the words that could differ and names the traps, such as
"programme" for a schedule but "program" for software. The agent decides each
one and writes `data/locale-en-GB.json`. Set `"locale": "en-GB"` in
`.ste-writing.json` to switch it on. Until you do, there is no spelling check.

### One mode, on purpose
ASD wrote the standard for aircraft maintenance procedures. Its dictionary
approves about 800 words, which is enough for a procedure and nowhere near
enough for prose.

Run it as an allowlist over this repository's own README and it reports 279
findings in 1137 words. The unknown words are "so", "way", "every", and "still".
No glossary fixes that, because those are not technical nouns.

So the skill does not run an allowlist. It uses the standard's vocabulary
judgements to find slop, which is the job on the label. There is one mode and no
flag to choose it.

### What it does not do
ASD-STE100 has 53 writing rules. The linter enforces 12 and flags 4 more that it
can see but cannot judge. Four tell it how to count words. The rest need a
person, and `remind.py` prints them when the lint passes.
`scripts/ste_policy.py` says which rule sits where.

This is not a certified STE checker. It fixes the form of the writing. It cannot
make a hollow paragraph true.

## Credits
- **ste-writing** — came from [@woosal1337](https://github.com/woosal1337)'s video, "The Cure for AI Slop is a 1986 Aircraft Manual". I kept the idea and rebuilt the skill around an extractor, a linter with rule ids and exit codes, and a hook. The first skill and linter carry an MIT license, Copyright (c) 2026 Ege Çelebi. [Source](https://github.com/woosal1337/blog/tree/main/videos/ep01-the-cure-for-ai-slop).

