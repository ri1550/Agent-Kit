#!/usr/bin/env python3
"""Stop hook: hold the turn open until the prose in this repository passes.

Installed once, globally, and inert everywhere by default. The hook does nothing
at all unless it finds `.ste-writing.json` at the root of the repository it is
running in. The ste-writing skill writes that file, so opting in happens in the
repository it applies to, and is done by the skill rather than by editing
settings.json for every project.

Scope comes from git: prose files that differ from HEAD, staged, unstaged, or
untracked. Nothing to maintain, new files are covered the moment they exist, and
a repository with a large back catalogue of prose does not fail on day one.

Exit codes are translated, never propagated. Claude Code reads exit 2 as "block"
and the linter reads 1 as "an enforced rule was broken", so passing the linter's
code straight through would invert the gate. This hook always exits 0 and says
what it means in JSON.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINTER = HERE.parent / "scripts" / "ste-lint.py"
REMINDER = HERE.parent / "scripts" / "remind.py"
MARKER = ".ste-writing.json"
PROSE_SUFFIXES = {".md", ".txt", ".markdown", ".mdx", ".rst"}

LINT_CLEAN, LINT_ENFORCED, LINT_FLAGGED, LINT_ERROR = 0, 1, 2, 3
MAX_REPORTED = 25


def respond(**payload) -> None:
    """Answer Claude Code and stop. Always exit 0, the JSON carries the verdict."""
    print(json.dumps(payload))
    raise SystemExit(0)


def allow(**payload) -> None:
    respond(**payload)


def block(reason: str) -> None:
    respond(decision="block", reason=reason)


def repository_root(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        if (directory / MARKER).is_file():
            return directory
    return None


def git(root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, timeout=20
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def changed_prose(root: Path) -> list[Path]:
    """Prose files that differ from HEAD, including ones never committed."""
    names = set(git(root, "diff", "--name-only", "HEAD"))
    names |= set(git(root, "diff", "--name-only", "--cached"))
    names |= set(git(root, "ls-files", "--others", "--exclude-standard"))
    if not names and not git(root, "rev-parse", "HEAD"):
        # A repository with no commits yet: everything tracked counts as new.
        names = set(git(root, "ls-files"))

    files = []
    for name in sorted(names):
        path = root / name
        if path.suffix.lower() in PROSE_SUFFIXES and path.is_file():
            files.append(Path(name))  # relative to the root, so findings read cleanly
    return files


def summarize(report: dict, limit: int = MAX_REPORTED) -> str:
    lines = []
    shown = 0
    for path, findings in report.get("files", {}).items():
        enforced = [f for f in findings if f.get("tier") == "enforced"]
        if not enforced:
            continue
        for finding in enforced:
            if shown >= limit:
                break
            lines.append(
                f"  {path}:{finding['line']}:{finding['column']}  "
                f"rule {finding['rule']}  {finding['message']} "
                f"“{finding['text']}”"
                + (f" -> {finding['suggestion']}" if finding.get("suggestion") else "")
            )
            shown += 1
    total = report.get("enforced", 0)
    if total > shown:
        lines.append(f"  ... and {total - shown} more")
    return "\n".join(lines)


def reminder() -> str:
    try:
        result = subprocess.run(
            [sys.executable, str(REMINDER)], capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()

    # A blocking Stop hook re-invokes the agent. If the prose cannot be made to
    # pass, that is a loop. Release on the second pass and say why.
    if payload.get("stop_hook_active"):
        allow(systemMessage="ste-writing: lint still failing, releasing the turn.")

    start = Path(payload.get("cwd") or Path.cwd()).resolve()
    root = repository_root(start)
    if root is None:
        allow()  # Not an opted-in repository. Do nothing, quietly.

    try:
        config = json.loads((root / MARKER).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        allow(systemMessage=f"ste-writing: cannot read {MARKER} ({error}). Skipped.")

    files = changed_prose(root)
    if not files:
        allow()

    mode = config.get("mode", "ste-general")
    try:
        result = subprocess.run(
            [
                sys.executable, str(LINTER),
                "--mode", mode,
                "--format", "json",
                "--config", str(root / MARKER),
                *[str(path) for path in files],
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        allow(systemMessage=f"ste-writing: could not run the linter ({error}). Skipped.")

    if result.returncode == LINT_ERROR:
        block(
            "ste-writing is switched on in this repository, but the linter cannot "
            "run:\n\n"
            f"{result.stderr.strip()}\n\n"
            "Build the dictionary from your own copy of ASD-STE100, or remove "
            f"{MARKER} to opt this repository out."
        )

    if result.returncode == LINT_CLEAN:
        # The lint passed. Put the judgment-tier checklist in front of the agent
        # here, at the decision point, because no script can check those rules.
        note = reminder()
        if not note:
            allow()
        allow(
            hookSpecificOutput={"hookEventName": "Stop", "additionalContext": note}
        )

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        allow(systemMessage="ste-writing: unreadable linter output. Skipped.")

    if result.returncode == LINT_FLAGGED:
        # Flagged findings are advice, not a gate. Say so and let the turn end.
        allow(
            systemMessage=f"ste-writing: {report.get('flagged', 0)} flagged finding(s).",
            hookSpecificOutput={
                "hookEventName": "Stop",
                "additionalContext": (
                    "ste-writing raised flagged findings. They do not block the turn. "
                    "Resolve them or say why not:\n" + summarize(report, MAX_REPORTED)
                ),
            },
        )

    block(
        f"ste-writing ({mode}): {report.get('enforced', 0)} enforced violation(s) in "
        "prose changed in this turn.\n\n"
        f"{summarize(report)}\n\n"
        "Fix each one, then check your work:\n"
        f"  python3 {LINTER} --mode {mode} <file>\n"
        "For any rule id above, read only that rule in "
        "agent-skills/ste-writing/data/rule-index.md."
    )
    return 0


if __name__ == "__main__":
    main()
