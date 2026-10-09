"""Connexion SQLite et sessions."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .migrations import migrate


def create_db_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    migrate(engine)
    return engine


class Database:
    def __init__(self, path: Path) -> None:
        self.engine = create_db_engine(path)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def session_scope(self) -> Session:
        """Session à utiliser dans un `with` (threads des jobs)."""
        return self._sessions()

    def session(self) -> Iterator[Session]:
        with self._sessions() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
