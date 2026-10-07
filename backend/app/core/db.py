from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    if not url.startswith("postgresql"):
        return create_engine(url, pool_pre_ping=True)
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3},
                         pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow)


def get_session() -> Iterator[Session]:
    with sessionmaker(bind=get_engine())() as session:
        yield session


@contextmanager
def savepoint(session: Session) -> Iterator[SessionTransaction]:
    """session.begin_nested() that leaves the outer transaction intact on Postgres and SQLite.

    pysqlite only sends BEGIN before the first INSERT/UPDATE/DELETE, so a SAVEPOINT issued after
    reads alone would open the transaction itself and its RELEASE would commit everything. On
    SQLite the real transaction is therefore opened first.
    """
    conn = session.connection()
    if conn.dialect.name == "sqlite":
        raw = conn.connection.dbapi_connection
        if raw is not None and not getattr(raw, "in_transaction", True):
            conn.exec_driver_sql("BEGIN")
    with session.begin_nested() as nested:
        yield nested
