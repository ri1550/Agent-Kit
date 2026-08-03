#!/usr/bin/env python3
"""Print the STE rules no script can check. Never blocks.

The linter enforces structure. This covers what it cannot: the rules that need a
person to decide whether the text is right. It runs when the lint passes, so the
list lands at the point where the work is about to be called done.
"""


def main() -> int:
    print(
        "ste-writing: the lint passed. It cannot check these, so confirm them "
        "yourself:\n"
        "  1.8  Technical nouns come from this project's glossary, not invented "
        "on the spot.\n"
        "  1.9  Each technical noun is short and easy to understand.\n"
        "  4.1  Every sentence says one thing, and says it plainly.\n"
        "  6.1  Information arrives in the order the reader needs it.\n"
        "  6.4  Each paragraph holds one topic.\n"
        "  9.2  Every approved word is used with its approved meaning.\n"
        "  9.4  Terminology matches the rest of the document.\n"
        "The linter fixes the form of the writing. It cannot make a hollow "
        "paragraph true."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
