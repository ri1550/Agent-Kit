# Agent-Kit

Skills, scripts, and workflows that make coding agents work in a structured
manner.

## The idea

Most skills and MCP servers are heuristics. They tell the agent what to do and
trust it to remember and apply the rules the same way every time. That trust does
not hold. An agent under load drops the rule, or applies half of it, or reasons
its way around it.

Better instructions do not fix this. Structure does. Put the rule where the agent
must meet it, and add scripts that check the result.

The instruction guides the work. The scripts decide whether the work passes. An
agent can talk its way past a guideline. It cannot talk its way past a script.
The goal is agent work that is repeatable.

### What the structure looks like

Each skill here has three parts:

1. A `SKILL.md` file that tells the agent how to work.
2. One or more scripts that test the output against the same rules.
3. A hook that runs the scripts, so nothing depends on the agent choosing to.

The scripts are the part that runs the same way every time.

## Contents

### agent-skills/

Each skill is a directory that holds a `SKILL.md` file, the scripts the skill
needs, and a `README.md` with the technical detail.

| Skill | What it does |
|---|---|
| [ste-writing](agent-skills/ste-writing/) | Rewrites prose into ASD-STE100 Simplified Technical English. Use it on documentation, READMEs, pull request text, error messages, and release notes. It does not apply to code |

## How to install

Each skill in `agent-skills` is one directory. Take the whole directory, never
the `SKILL.md` file alone. The directory keeps `SKILL.md` and `scripts/`
together, so the script paths still resolve.

Claude Code uses `~/.claude/skills/` for personal skills, and `.claude/skills/`
for project skills. Other agents use their own location, so read the
documentation for the agent you use.

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

Some skills need a setup step after you install them. Read the `README.md` in the
skill directory.
