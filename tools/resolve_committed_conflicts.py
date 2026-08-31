"""One-off: strip committed merge-conflict markers, keeping the HEAD side.

Commit 54c1222 ("merge remote and update backend fixes") was created while the
working tree still held unresolved conflicts, so the markers themselves were
committed into 15 files. `git status` is therefore clean and git offers no
resolution path: the markers are ordinary file content now.

The HEAD side of every hunk comes from b260ad4 ("fix: update backend test fixes"),
which was written after an actual test run. The other side is the earlier
unverified version. So the resolution rule is uniform: keep HEAD, drop the other.

Run with --check first to see what would change.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

START = "<<<<<<< "
MIDDLE = "======="
END = ">>>>>>> "


class UnbalancedConflict(RuntimeError):
    """The markers do not nest as expected; refuse to guess."""


def resolve_text(text, *, keep="head"):
    """Return (resolved_text, hunks_resolved)."""
    out = []
    hunks = 0
    state = "body"

    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = line.rstrip("\r\n")

        if stripped.startswith(START):
            if state != "body":
                raise UnbalancedConflict(f"nested {START!r} at line {number}")
            state = "head"
            hunks += 1
            continue

        if stripped == MIDDLE and state == "head":
            state = "other"
            continue

        if stripped.startswith(END):
            if state not in {"head", "other"}:
                raise UnbalancedConflict(f"unexpected {END!r} at line {number}")
            state = "body"
            continue

        if state == "body" or state == keep:
            out.append(line)

    if state != "body":
        raise UnbalancedConflict("file ends inside a conflict hunk")

    return "".join(out), hunks


def iter_conflicted(root=BASE_DIR):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in {".git", "venv", "__pycache__", "node_modules"} for part in path.parts):
            continue
        if path.suffix not in {".py", ".txt", ".ini", ".md", ".cfg", ".toml", ".example"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if START in text:
            yield path, text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report without writing.")
    parser.add_argument(
        "--keep",
        choices=["head", "other"],
        default="head",
        help="Which side of each hunk to keep (default: head).",
    )
    args = parser.parse_args(argv)

    total_files = 0
    total_hunks = 0
    failures = []

    for path, text in iter_conflicted():
        try:
            resolved, hunks = resolve_text(text, keep=args.keep)
        except UnbalancedConflict as exc:
            failures.append(f"{path.relative_to(BASE_DIR)}: {exc}")
            continue

        total_files += 1
        total_hunks += hunks
        action = "would resolve" if args.check else "resolved"
        print(f"{action} {hunks:>2} hunk(s)  {path.relative_to(BASE_DIR)}")

        if not args.check:
            path.write_text(resolved, encoding="utf-8")

    for message in failures:
        print(f"SKIPPED {message}", file=sys.stderr)

    print(f"\n{total_files} file(s), {total_hunks} hunk(s), keeping the {args.keep!r} side.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
