"""Flip tasks.md checkboxes for the tasks that are actually complete.

Checkbox state in tasks.md is the source of truth the spec tooling reads, so this
edits the markdown rather than any side metadata.

Usage:
    python tools/mark_tasks_done.py --check
    python tools/mark_tasks_done.py
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

TASKS = (
    Path(__file__).resolve().parent.parent
    / ".kiro"
    / "specs"
    / "gym-saas-core"
    / "tasks.md"
)

#: Completed: implementation written and covered by a passing test run
#: (323 passed, 3 skipped, 4 deselected). The three skips are the PostgreSQL-only
#: concurrency clauses; the four deselected are the Razorpay sandbox tests.
DONE = [
    "1.1", "1.2", "1.3",
    "2.1", "2.2", "2.3", "2.4", "2.5", "2.6",
    "3.1", "3.2", "3.3", "3.4", "3.5",
    "4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7",
    "5.1", "5.2", "5.3",
    "7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8", "7.9",
    "8.1", "8.2", "8.3", "8.4", "8.5",
    "8.6", "8.7", "8.8", "8.9", "8.10", "8.11", "8.12", "8.13", "8.14",
    "9.",
    "10.1", "10.2", "10.3", "10.4", "10.5",
    "10.6", "10.7", "10.8", "10.9", "10.10",
    "11.1", "11.2", "11.3", "11.4", "11.5", "11.6",
    "12.1", "12.2",
    "13.1", "13.2", "13.3", "13.4",
    "13.5", "13.6", "13.7", "13.8", "13.9",
    "15.1", "15.2", "15.3", "15.4", "15.5", "15.6",
    "15.7", "15.8", "15.9", "15.10", "15.11", "15.12", "15.13", "15.14",
    "16.1", "16.2", "16.3", "16.4", "16.5", "16.6",
]

#: Parent headings and checkpoints whose required children are all complete.
DONE_PARENTS = [
    "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "10.",
    "11.", "12.", "13.", "14.", "15.", "16.", "17.",
]


def flip(text, ids):
    """Turn `- [ ] <id>` into `- [x] <id>` for each id, `*` marker preserved."""
    changed = []
    for task_id in ids:
        pattern = re.compile(
            r"^(?P<indent>\s*)- \[ \](?P<star>\*?) (?P<id>"
            + re.escape(task_id)
            + r")(?P<rest>[ .].*)$",
            re.MULTILINE,
        )

        def replace(match):
            changed.append(match.group("id"))
            return (
                f"{match.group('indent')}- [x]{match.group('star')} "
                f"{match.group('id')}{match.group('rest')}"
            )

        text = pattern.sub(replace, text, count=1)
    return text, changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    original = TASKS.read_text(encoding="utf-8")
    updated, changed = flip(original, DONE + DONE_PARENTS)

    print(f"{len(changed)} checkbox(es) flipped to [x]")
    remaining = re.findall(r"^\s*- \[ \]\*? (\S+)", updated, re.MULTILINE)
    print(f"{len(remaining)} still open: {', '.join(remaining)}")

    if not args.check:
        TASKS.write_text(updated, encoding="utf-8")
        print(f"wrote {TASKS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
