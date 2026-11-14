"""Read side of the database: runs validated SQL on a read-only connection."""

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from src.constants import ErrorCode
from src.errors import AppError

# SQLite VM steps between two deadline checks: often enough to stop on time, rare enough
# to cost nothing.
PROGRESS_STEPS: Final = 1_000
# The clock does not bound memory: zeroblob(N) or a long printf builds a huge value in one
# step. These caps keep one row and the whole result small; a group_concat of every
# customer name still fits.
MAX_VALUE_BYTES: Final = 100_000
MAX_COLUMNS: Final = 64
MAX_RESULT_BYTES: Final = 5_000_000

type SqlValue = int | float | str | bytes | None


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[SqlValue, ...]]


class QueryError(AppError):
    """SQLite rejected the query or it ran out of time."""

    code = ErrorCode.QUERY_FAILED


class OrdersReader:
    def __init__(self, db_path: Path, timeout: float) -> None:
        # as_uri() percent-encodes the path, so a `?` or `#` in it cannot change the URI.
        self._uri = f"{db_path.resolve().as_uri()}?mode=ro"
        self._timeout = timeout

    def run(self, sql: str) -> QueryResult:
        """Run `sql`, which must come from validate_sql, and return every row."""
        deadline = time.monotonic() + self._timeout
        with closing(sqlite3.connect(self._uri, uri=True)) as conn:
            # A true return aborts the statement. The LIMIT does not bound a cross join or a
            # COUNT over a recursive CTE, so the clock does.
            conn.set_progress_handler(lambda: time.monotonic() > deadline, PROGRESS_STEPS)
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
            conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, MAX_COLUMNS)
            try:
                cursor = conn.execute(sql)
                rows = _fetch_capped(cursor)
            except sqlite3.Error as exc:
                if time.monotonic() > deadline:
                    message = f"La consulta superó el tiempo máximo de {self._timeout:g} s."
                    raise QueryError(message) from exc
                raise QueryError(f"La base de datos rechazó la consulta: {exc}") from exc
        columns = [column[0] for column in cursor.description or ()]
        return QueryResult(columns=columns, rows=rows)


def _fetch_capped(cursor: sqlite3.Cursor) -> list[tuple[SqlValue, ...]]:
    rows: list[tuple[SqlValue, ...]] = []
    size = 0
    for row in cursor:
        size += sum(len(value) for value in row if isinstance(value, str | bytes))
        if size > MAX_RESULT_BYTES:
            limit_mb = MAX_RESULT_BYTES / 1_000_000
            raise QueryError(f"El resultado supera el tamaño máximo de {limit_mb:g} MB.")
        rows.append(row)
    return rows
