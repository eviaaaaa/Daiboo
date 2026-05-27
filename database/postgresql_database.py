from __future__ import annotations

import os
from functools import lru_cache

import dotenv
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine


dotenv.load_dotenv(dotenv_path=os.getenv("NEXUSSURF_ENV_FILE") or os.path.join(os.getcwd(), ".env"))


def _database_config() -> dict[str, str | None]:
    """Read database configuration from the current environment."""
    return {
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }


def _database_url() -> URL:
    config = _database_config()
    return URL.create(
        drivername=os.getenv("DB_DRIVER", "postgresql+psycopg"),
        username=config["user"],
        password=config["password"],
        host=config["host"],
        port=config["port"],
        database=config["dbname"],
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the SQLAlchemy engine lazily.

    Importing modules that reference ``database.engine`` should not eagerly
    import the PostgreSQL driver or print credentials.  The real engine is
    created only when application code opens a connection or session.
    """
    return create_engine(_database_url(), echo=False)


class LazyEngine:
    """Small proxy that preserves ``from database import engine`` call sites."""

    def _engine(self) -> Engine:
        return get_engine()

    def __getattr__(self, name: str):
        return getattr(self._engine(), name)

    def __repr__(self) -> str:
        return "<LazyEngine uninitialized>" if get_engine.cache_info().currsize == 0 else repr(self._engine())


engine = LazyEngine()
