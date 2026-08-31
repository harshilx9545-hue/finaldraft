"""Destructive: replace the migration baseline in one indivisible step.

Phase 1 changes the shape of nearly every model, including making `gym` FKs
non-nullable on tables that already have rows. Rather than ship a chain of
add-column-then-backfill migrations for a database with no production data, the
baseline is regenerated from scratch.

The ordering matters and is the whole point of this being a script rather than
three shell commands: the old migration and the old database are deleted *first*
and both deletions are verified, and only then is `makemigrations` invoked. If
the migration file cannot be removed, nothing is generated, so the tree is never
left holding two competing baselines (9.2).

`core/migrations/__init__.py` is preserved; deleting it would silently turn the
migrations directory back into an unmanaged package.

Usage:
    python tools/rebuild_migration_baseline.py [--yes] [--keep-db]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BASE_DIR / "core" / "migrations"
BASELINE = MIGRATIONS_DIR / "0001_initial.py"
SQLITE_DB = BASE_DIR / "db.sqlite3"
PACKAGE_MARKER = MIGRATIONS_DIR / "__init__.py"


class RebuildAborted(RuntimeError):
    """Raised when a precondition fails, before anything is generated."""


def _remove(path):
    """Delete `path` if present. Returns True when the path is gone afterwards."""
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return not path.exists()


def delete_baseline(migration_path=BASELINE):
    """Delete the existing baseline migration, verifying it is really gone.

    A file held open by another process (a running dev server on Windows, most
    commonly) fails to unlink; that must abort the rebuild rather than proceed.
    """
    if not _remove(Path(migration_path)):
        raise RebuildAborted(
            f"Could not delete {migration_path}. Nothing was generated. Close any "
            "process holding the file (a running runserver) and retry."
        )
    if Path(migration_path).exists():
        raise RebuildAborted(
            f"{migration_path} still exists after deletion. Aborting before "
            "generating a replacement."
        )


def superseded_migrations(migrations_dir=MIGRATIONS_DIR, baseline=BASELINE):
    """Every generated migration other than the baseline, in reverse order.

    Requirement 9.1 asks for *one* replacement baseline, and the deployment gate
    asserts exactly one migration file exists. Any follow-on migration in the tree
    (0002, 0003, ...) describes a change the regenerated baseline already contains,
    so leaving it behind would both break that assertion and re-apply an operation
    the baseline has folded in. They are removed with the same verify-then-proceed
    discipline as the baseline, newest first, so a failure part-way through cannot
    leave a migration whose dependency has already gone.
    """
    migrations_dir = Path(migrations_dir)
    baseline = Path(baseline)
    if not migrations_dir.is_dir():
        return []
    return sorted(
        (
            path
            for path in migrations_dir.glob("*.py")
            if path.name != "__init__.py" and path.resolve() != baseline.resolve()
        ),
        key=lambda path: path.name,
        reverse=True,
    )


def delete_superseded_migrations(migrations_dir=MIGRATIONS_DIR, baseline=BASELINE):
    """Delete the non-baseline migrations, verifying each one is really gone."""
    removed = []
    for path in superseded_migrations(migrations_dir, baseline):
        if not _remove(path):
            raise RebuildAborted(
                f"Could not delete {path}. Nothing was generated. Close any process "
                "holding the file and retry."
            )
        removed.append(path)
    return removed


def delete_database(db_path=SQLITE_DB):
    """Delete the local SQLite database, verifying it is really gone."""
    if not _remove(Path(db_path)):
        raise RebuildAborted(
            f"Could not delete {db_path}. Nothing was generated. Stop any process "
            "holding the database open and retry."
        )
    if Path(db_path).exists():
        raise RebuildAborted(f"{db_path} still exists after deletion. Aborting.")


def assert_package_intact(marker=PACKAGE_MARKER):
    """`core/migrations` must remain an importable package."""
    marker = Path(marker)
    if not marker.exists():
        marker.write_text("", encoding="utf-8")


def generate_baseline():
    """Invoke `makemigrations core`. Only ever called after both deletions pass."""
    import django
    from django.core.management import call_command

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gymapp.settings")
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    django.setup()
    call_command("makemigrations", "core", verbosity=1)


def rebuild(*, keep_db=False, generate=generate_baseline):
    """Delete, verify, then generate. `generate` is injectable so the atomicity
    test can assert that a failed deletion never reaches it.
    """
    assert_package_intact(PACKAGE_MARKER)
    # Deletion order: the migrations first. They are the artefacts that must not
    # survive; a leftover database is recoverable, a leftover baseline is not.
    # Superseded migrations go before the baseline so the tree never holds a
    # migration whose dependency has already been removed.
    #
    # The directory is derived from BASELINE rather than read from the module-level
    # MIGRATIONS_DIR so that redirecting BASELINE redirects the whole operation.
    # Reading the global here would let a caller that pointed BASELINE elsewhere
    # still sweep the real migrations directory.
    delete_superseded_migrations(Path(BASELINE).parent, BASELINE)
    delete_baseline(BASELINE)
    if not keep_db:
        delete_database(SQLITE_DB)
    generate()
    if not BASELINE.exists():
        raise RebuildAborted(
            "makemigrations completed but produced no 0001_initial.py. Check that "
            "`core` is in INSTALLED_APPS."
        )
    return BASELINE


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (for CI).",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Regenerate the migration but leave db.sqlite3 in place.",
    )
    args = parser.parse_args(argv)

    targets = (
        superseded_migrations(MIGRATIONS_DIR, BASELINE)
        + [BASELINE]
        + ([] if args.keep_db else [SQLITE_DB])
    )
    print("This will irreversibly delete:")
    for target in targets:
        print(f"  - {target} {'(exists)' if target.exists() else '(absent)'}")

    if not args.yes:
        answer = input("Type 'rebuild' to continue: ").strip()
        if answer != "rebuild":
            print("Aborted; nothing was deleted or generated.")
            return 1

    try:
        created = rebuild(keep_db=args.keep_db)
    except RebuildAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2

    print(f"Regenerated baseline: {created}")
    print("Next: python manage.py migrate")
    print("Then: python manage.py makemigrations --check --dry-run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
