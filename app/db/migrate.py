"""Programmatic Alembic access (used by the CLI and tests)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["configure_logger"] = False
    if database_url:
        config.attributes["database_url"] = database_url
    return config


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str | None = None, revision: str = "-1") -> None:
    command.downgrade(alembic_config(database_url), revision)


def current(database_url: str | None = None) -> None:
    command.current(alembic_config(database_url), verbose=False)
