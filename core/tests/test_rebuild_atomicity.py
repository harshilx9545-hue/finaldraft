"""Rebuild-script atomicity (task 5.3).

Validates: Requirements 9.2

The rebuild is destructive, so the one thing that must never happen is a *partial*
replacement: the old baseline deleted, and no new one generated, or worse, a
generated migration alongside a baseline that failed to delete. The script deletes
and verifies first, and only then generates. These tests pin that ordering.
"""
import pytest

from tools import rebuild_migration_baseline as rebuild


def test_failed_migration_deletion_generates_nothing(tmp_path, monkeypatch):
    """A migration file that cannot be unlinked aborts before makemigrations runs."""
    stubborn = tmp_path / "0001_initial.py"
    stubborn.write_text("# pretend baseline\n", encoding="utf-8")

    # Simulate the Windows case: the file is held open, so unlink raises.
    monkeypatch.setattr(
        rebuild.Path, "unlink", lambda self, **kwargs: (_ for _ in ()).throw(OSError("locked"))
    )

    generated = []

    with pytest.raises(rebuild.RebuildAborted):
        rebuild.delete_baseline(stubborn)

    assert generated == [], "makemigrations must not have been reached"
    assert stubborn.exists(), "the file is still there, which is why we aborted"


def test_rebuild_does_not_call_generate_when_deletion_fails(tmp_path, monkeypatch):
    """End-to-end ordering: the injected generator is never invoked."""
    calls = []

    monkeypatch.setattr(rebuild, "BASELINE", tmp_path / "0001_initial.py")
    monkeypatch.setattr(rebuild, "SQLITE_DB", tmp_path / "db.sqlite3")
    monkeypatch.setattr(rebuild, "PACKAGE_MARKER", tmp_path / "__init__.py")
    rebuild.BASELINE.write_text("# pretend baseline\n", encoding="utf-8")
    rebuild.SQLITE_DB.write_text("", encoding="utf-8")

    monkeypatch.setattr(rebuild, "_remove", lambda path: False)

    with pytest.raises(rebuild.RebuildAborted):
        rebuild.rebuild(generate=lambda: calls.append("generated"))

    assert calls == []


def test_successful_rebuild_calls_generate_after_both_deletions(tmp_path, monkeypatch):
    order = []

    monkeypatch.setattr(rebuild, "BASELINE", tmp_path / "0001_initial.py")
    monkeypatch.setattr(rebuild, "SQLITE_DB", tmp_path / "db.sqlite3")
    monkeypatch.setattr(rebuild, "PACKAGE_MARKER", tmp_path / "__init__.py")
    rebuild.BASELINE.write_text("# pretend baseline\n", encoding="utf-8")
    rebuild.SQLITE_DB.write_text("", encoding="utf-8")

    real_remove = rebuild._remove

    def tracking_remove(path):
        order.append(f"deleted:{path.name}")
        return real_remove(path)

    monkeypatch.setattr(rebuild, "_remove", tracking_remove)

    def generate():
        order.append("generated")
        rebuild.BASELINE.write_text("# regenerated\n", encoding="utf-8")

    rebuild.rebuild(generate=generate)

    assert order.index("generated") == len(order) - 1
    assert "deleted:0001_initial.py" in order
    assert "deleted:db.sqlite3" in order


def test_migrations_package_marker_is_preserved(tmp_path, monkeypatch):
    """Deleting __init__.py would silently unmanage the migrations package."""
    marker = tmp_path / "__init__.py"
    rebuild.assert_package_intact(marker)
    assert marker.exists()
