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
            try:
                cursor = conn.execute(sql)
                rows = cursor.fetchall()
            except sqlite3.Error as exc:
                if time.monotonic() > deadline:
                    message = f"La consulta superó el tiempo máximo de {self._timeout:g} s."
                    raise QueryError(message) from exc
                raise QueryError(f"La base de datos rechazó la consulta: {exc}") from exc
        columns = [column[0] for column in cursor.description or ()]
        return QueryResult(columns=columns, rows=rows)
