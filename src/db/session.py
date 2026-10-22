"""
db/session.py — SQLAlchemy engine and session factory.

Provides both sync and async session factories.
All database access should go through these helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings
from src.db.models import Base


def _make_engine():
    """Create the SQLAlchemy engine from configured DATABASE_URL."""
    db_url = settings.database_url

    # Ensure data/ directory exists for SQLite
    if db_url.startswith("sqlite:///"):
        db_path_str = db_url.replace("sqlite:///", "")
        Path(db_path_str).parent.mkdir(parents=True, exist_ok=True)

    connect_args = {}
    if "sqlite" in db_url:
        connect_args = {"check_same_thread": False}

    engine = create_engine(
        db_url,
        connect_args=connect_args,
        echo=settings.debug,
    )

    # Enable WAL mode and foreign keys for SQLite
    if "sqlite" in db_url:
        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine = _make_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def init_db() -> None:
    """Create all tables. Safe to call multiple times (uses CREATE IF NOT EXISTS)."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a database session and ensures closure."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
