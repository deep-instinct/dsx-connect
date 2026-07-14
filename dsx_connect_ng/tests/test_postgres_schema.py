from __future__ import annotations

from dsx_connect_ng.control_plane import postgres_repo as control_plane_postgres_repo
from dsx_connect_ng.jobs import postgres_repo


def test_apply_schema_acquires_advisory_lock_before_migrations(monkeypatch, tmp_path) -> None:
    migration = tmp_path / "0001_test.sql"
    migration.write_text("CREATE TABLE IF NOT EXISTS example (id TEXT PRIMARY KEY);", encoding="utf-8")
    calls: list[tuple[str, tuple[int] | None]] = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query: str, params: tuple[int] | None = None) -> None:
            calls.append((query, params))

    class Connection:
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            self.committed = True

    conn = Connection()

    monkeypatch.setattr(postgres_repo, "migration_files", lambda: [migration])
    monkeypatch.setattr(postgres_repo.psycopg, "connect", lambda db_url: conn)

    postgres_repo.apply_schema("postgresql://example")

    assert calls == [
        ("SELECT pg_advisory_lock(%s)", (postgres_repo._SCHEMA_ADVISORY_LOCK_ID,)),
        ("CREATE TABLE IF NOT EXISTS example (id TEXT PRIMARY KEY);", None),
    ]
    assert conn.committed is True


def test_control_plane_schema_uses_locked_job_schema(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(control_plane_postgres_repo, "apply_job_schema", calls.append)

    control_plane_postgres_repo.apply_schema("postgresql://example")

    assert calls == ["postgresql://example"]
