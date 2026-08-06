# ste-writing

Rewrites prose into ASD-STE100 Simplified Technical English. A linter decides
whether the text passes, and a Stop hook holds the agent's turn open until it
does.

`SKILL.md` tells the agent how to work. This file tells you how the parts fit
together.

## Why a linter and not a style guide

ASD-STE100 is a controlled English standard. ASD wrote it in 1986 for aircraft
maintenance manuals, where a wrong sentence gets somebody hurt. It approves about
800 words, bans the passive voice, caps a sentence at 20 words, and gives one
meaning to each word.

Most of what people call AI slop is a form problem: stacked auxiliaries, a
passive with no actor, a marketing adjective, a long Latinate word where a short
plain one would do. The standard already names each of those, and it did so
40 years before the machines came.

An instruction to follow the standard does not hold. The agent drops it under
load. So the rules live in a script that runs, reports a line and a column, and
returns an exit code.

## Setup

Three steps, once.

**1. Build the dictionary.**

This skill ships no content from the standard, because ASD holds the copyright
and its free-use grant covers named organizations, not a public repository. So
you download the standard and build the data on your own machine.

Get ASD-STE100 Issue 9 from [asd-ste100.org](https://asd-ste100.org). It is free,
but you must make an account.

```bash
python3 scripts/build-dictionary.py --pdf ~/Downloads/ASD-STE100_ISSUE9.pdf
```

This needs `pdftotext`, which comes with poppler. It writes `data/`, which
`.gitignore` covers, so rebuild it after you clone. The build takes about one
second.

**2. Mark the repositories you want.**

```bash
cd ~/my-project
python3 ~/.claude/skills/ste-writing/scripts/ste-lint.py --init
```

That writes `.ste-writing.json` at the root. It is the marker the hook looks for
and the place your own words live. Commit it. Delete it to opt out.

**3. Install the hook, once.**

Add this to `~/.claude/settings.json`, and correct the path to your clone:

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "python3 $HOME/Projects/Agent-Kit/agent-skills/ste-writing/scripts/ste-hook.py",
        "timeout": 60,
        "statusMessage": "Checking prose against STE..."
      }
    ]
  }
}
```

Write `$HOME` and not `~`, because `~` expands only in a shell. An absolute path
works too. A Stop hook takes no matcher: it fires on every turn that ends. The
hook does nothing in a repository that has no marker file, so a global install
switches nothing on by itself.

## How the parts fit

```
ASD-STE100 PDF ──build-dictionary.py──> data/ste-dictionary.json   799 approved words
   (yours)                              data/ste-rules.json        53 rules, 175 examples
                                              │
scripts/ste_policy.py ────────────────────────┤   our tiers and slop words
<repo>/.ste-writing.json ─────────────────────┤   your words, and the marker
                                              ▼
                                        ste-lint.py ──> 0 · 1 · 2 · 3
                                              ▲                │
                                        ste-hook.py <──────────┘
                                       (Stop hook, blocks the turn)
```

Three sources of words, and they do not mix:

| Source | Holds | Committed? |
|---|---|---|
| `data/ste-dictionary.json` | The words ASD approved | No. Built from your PDF |
| `data/ste-rules.json` | The rules ASD wrote | No. Built from your PDF |
| `scripts/ste_policy.py` | What this skill decided | Yes |
| `.ste-writing.json` | What your project decided | Yes, in your project |

The skill's own judgements are code, not data. A rule tier names a check in the
linter, and a slop word only means something to the check that reads it. So a
rule record carries no tier. `--rule` joins the two when it prints the rule, and
the tier can change without a rebuild.

## The scripts

| Script | What it does |
|---|---|
| `ste-lint.py` | The gate. Reads prose, reports findings, returns an exit code |
| `build-dictionary.py` | Turns your PDF into `data/` |
| `localize.py` | Plans a locale, then checks what the agent wrote |
| `ste_data.py` | The shapes of the built data, and the word lists |
| `ste_policy.py` | The rule table, and the words STE never documents |
| `ste-hook.py` | Stop hook. Inert without a marker file |
| `remind.py` | Prints the rules no script can check |

### build-dictionary.py

Runs `pdftotext -layout`, then reads the result page by page.

The word list is a four-column table, and the columns move by a few characters
from page to page. So each page reports its own geometry from the header row it
repeats.

An entry can continue across a page break. The script joins the pages first, then
cuts the result into entries. A headword can wrap over two lines, and the
typesetter breaks a long one with a hyphen, so `ELECTROMAG-` and `NETIC (adj)`
join into one word.

The script checks its own work and writes nothing if the extraction falls short:
minimum counts, and one spot check per parsing hazard that has bitten before. A
dictionary that is quietly half complete is worse than no dictionary. The linter
would then pass text that nobody examined.

Issue 9 yields 799 approved lemmas and 1222 non-approved lemmas, each with the
replacement the standard suggests. It also yields all 53 rules, the 8 general
recommendations, 175 worked examples, and 112 index subjects.

The rules go to `data/ste-rules.json` as one record each: the id, the section,
the statement, the text, and the examples. Nine markdown files held them before,
and the only way in was a regular expression over a heading. The build wrote the
subject index to disk for two releases, and no code ever opened it.

The build refuses to write when the rules it found are not the rules the table
names. A count of 53 passes while a rule arrives under the wrong id, and a rule
the table does not name has no tier at all.

### ste-lint.py

```bash
python3 scripts/ste-lint.py README.md                # check a file
python3 scripts/ste-lint.py --format json docs/*.md  # for a machine
cat draft.md | python3 scripts/ste-lint.py -         # from standard input
python3 scripts/ste-lint.py --rule 3.6               # the rule and its examples
python3 scripts/ste-lint.py --rule 3.6 --full        # the text of the rule
python3 scripts/ste-lint.py --subject hyphen         # which rule covers this?
python3 scripts/ste-lint.py --rules                  # every rule and its tier
python3 scripts/ste-lint.py --triage docs/*.md       # every word to decide
python3 scripts/ste-lint.py --fail-on-flagged x.md   # exit 1 on flagged too
```

`--fail-on-flagged` turns the warnings into a gate. The hook never passes it: the
flagged tier is advice, and a rule that only warns is one the agent answers
rather than obeys.

`--rule` gives the statement and the worked examples, which is what an agent
fixes a finding from. The text of the rule is 60 lines of prose, so it comes
only when asked for. `--subject` answers from the standard's own index, and
reaches the general recommendations (`GR-1` thru `GR-8`) as well as the rules.
These three read the rules and nothing else, so they answer before the linter
loads the dictionary.

Findings carry the rule id, the `file:line:column`, the text, the rule in one
line, and the replacement the standard suggests:

```
README.md
  error README.md:38:12  rule 3.6  Passive voice.
        "was designed"
        Use the active voice
        -> Name the actor and put it first.
```

Two parts of this are easy to get wrong and are worth knowing about.

**Masking.** Code, inline code, link targets, URLs, and front matter are out of
scope, so the linter blanks each one before it reads. It replaces each one with
spaces of the same length, which is what lets a finding report a true line and
column.

**Word counting.** Rules 8.4 thru 8.7 say how STE counts words:

- parenthetical text counts as one word
- a number with its unit counts as one word
- a hyphenated word counts as one word
- a colon ends a sentence in a vertical list

The counter obeys them, so the 20 and 25 word limits report a length you can
reproduce by hand.

### localize.py

Rule 1.14 asks for American spelling. That is right for the standard and wrong
for a team that does not write it, so the skill ships no spelling list. It builds
one instead, once, per language.

```bash
python3 scripts/localize.py --en-GB           # the work plan
python3 scripts/localize.py --en-GB --check   # check what you wrote
```

The plan reads the built dictionary, finds the words a spelling rule could touch,
and names the traps: `programme` for a schedule but `program` for software,
`practise` for the verb but `practice` for the noun, `advise` which is not an
`-ize` word at all. An agent decides each one and writes `data/locale-en-GB.json`.

`--check` holds that file to the contract, and it checks which way the map goes.
A backwards entry would tell writers to undo correct work, and it is the mistake
this pass makes most easily.

Set `"locale": "en-GB"` in `.ste-writing.json` to switch rule 1.14 on. Until you
do, there is no spelling check at all.

### ste-hook.py

A Stop hook, installed once and inert everywhere by default. It exits at once
unless it finds `.ste-writing.json` at the root of the repository it runs in.

Scope comes from git: prose files that differ from `HEAD`, staged, unstaged, or
untracked. You keep no list, and a new file counts the moment it exists. A
repository with a large back catalogue of prose does not fail on day one.

It translates the linter's exit codes and never passes them through. Claude Code
reads exit 2 as "block", and the linter reads 1 as "the text breaks an enforced
rule". A straight pass would invert the gate. The hook always exits 0 and says
what it means in JSON.

A blocking Stop hook re-invokes the agent, so text the agent cannot fix would
loop. The hook reads `stop_hook_active` and releases on the second pass.

## .ste-writing.json

Same shape as the dictionary: `meta` first, so `head` on the file says what wrote
it, then named sections.

```json
{
  "meta":     { "written_by": "ste-lint.py --init", "version": "v1.1.0" },
  "settings": { "locale": "", "exclude": ["LICENSE"] },
  "words":    { "allow": [], "deny": {}, "prefer": {} }
}
```

The linter reads the three word sections in this order:

| Section | Effect | Command |
|---|---|---|
| `deny` | Refuses a word here, even one the standard approves | `--deny utilise use` |
| `allow` | Lets you use a word the dictionary lacks, and gives the linter its part of speech | `--add-word endpoint` |
| `prefer` | One name for one thing, per rule 1.11 | `--prefer repository repo` |

The linter reads `deny` first, so a project decision beats every other check. A
word in both `allow` and `deny` is a contradiction, and the linter refuses the
file rather than pick one.

Base forms only. The plural and the possessive of a declared word match for you.

An `allow` entry is a word, or an object that gives its part of speech:

```json
"allow": ["artifact", { "word": "cache", "pos": ["n", "v"] }]
```

A plain word is a noun, which is what rule 2.1 counts. Tag a word that is also a
verb, or rule 2.1 reads `Cache the config file` as a noun cluster.

Tagging also switches on two rules that a bare list never raises. A word you tag
a noun and not a verb is rule 1.7 when it appears as a verb, and a word you tag a
verb and not a noun is rule 1.13 when it appears as a noun. `--add-word cache:n,v`
writes the object form.

A word that is honestly both, as `cache` and `commit` are, gets both tags. Rule
2.1 then leaves it alone where a sentence opens on it, because that position is
the imperative.

There is no stored list of flagged words. `--triage` computes it from the prose,
so it cannot claim a word is a problem after you delete the sentence.

## Rules, and what the linter does about each

ASD-STE100 has 53 writing rules. This skill adds four house rules, which carry an
`H` id, for the words a 1986 aircraft manual had no reason to name.

| Tier | Count | Meaning |
|---|---|---|
| enforced | 13 | The linter decides. A violation returns exit 1 |
| flagged | 7 | The linter warns. The agent resolves it or says why not |
| counting | 4 | Not a fault. Rules 8.4 thru 8.7 shape the word count |
| judgment | 17 | No machine can decide it. `remind.py` prints these |

The other rules have no check. The table still holds them, for `--rule` and for
the checklist. `scripts/ste_policy.py` is the source of the counts above.

ASD also gives 8 general recommendations, `GR-1` thru `GR-8`. They are not rules
and they carry no tier, and the linter never raises one. They are readable
because the standard's own index sends the reader to them.

The 13 enforced:

- `1.14` spelling, `3.4` stacked auxiliaries, `3.5` "-ing" as the main verb
- `3.6` passive voice, `4.2` contractions, `8.1` semicolons, `9.3` phrasal verbs
- `5.1` instructions over 20 words, `6.3` description over 25 words
- `6.6` paragraphs over six sentences
- `H.1` marketing adjectives, `H.2` slop words, `H.4` words this project denied

The 7 flagged:

- `1.2` an approved word used as a part of speech it does not have
- `1.7` a technical noun used as a verb
- `1.11` two names for one thing
- `1.13` a technical verb used as a noun
- `2.1` noun clusters
- `3.7` an action written as a noun
- `H.3` hedging preambles

Rules 1.7 and 1.13 read the parts of speech in `words.allow`. A project that
lists only bare words never sees either one: a bare entry counts as a noun, but
that is silence, and neither rule reads silence as a decision.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Clean |
| 1 | The text breaks an enforced rule |
| 2 | Flagged findings only |
| 3 | The check could not run |

Exit 3 never becomes exit 0. A linter that passes because it has no dictionary is
worse than no linter, because the gate still looks green.

## What it does not do

This is not a certified STE checker. Certification needs a person.

The linter covers the mechanical subset, which is where slop lives. It cannot
tell you that a technical noun was the wrong choice. It cannot tell you that the
information arrives in the wrong order, or that a paragraph is true.

`remind.py` prints those rules when the lint passes. The point is to name them,
not to pretend the script reads them.

Rule 2.1 is honest but nearly blind: it can only see a noun cluster made of words
it knows are nouns, and the standard names 239 of them. Your `allow` list is what
makes it sharper.

## Credits

Came from [@woosal1337](https://github.com/woosal1337)'s video, "The Cure for AI
Slop is a 1986 Aircraft Manual". The first skill and linter carry an MIT license,
Copyright (c) 2026 Ege Çelebi.
[Source](https://github.com/woosal1337/blog/tree/main/videos/ep01-the-cure-for-ai-slop).
