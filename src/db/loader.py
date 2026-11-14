"""Write side of the database. Only the ETL uses it; the API never writes."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final

import polars as pl

from src.constants import ISO_DATE_FORMAT, ORDER_COLUMNS

SQL_DIR: Final = Path(__file__).parent
# Column names come from a constant, never from CSV values; the values are parameters.
INSERT_ORDER: Final = (
    f"INSERT INTO orders ({', '.join(ORDER_COLUMNS)}) "
    f"VALUES ({', '.join(['?'] * len(ORDER_COLUMNS))})"
)


class OrdersLoader:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def rebuild(self, orders: pl.DataFrame) -> None:
        """Replace the database with `orders`, the schema and the views."""
        # Build a sibling file and swap it in, so readers never see a half-built database.
        staging = self._db_path.with_suffix(".tmp")
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.unlink(missing_ok=True)
        rows = (
            orders.select(ORDER_COLUMNS)
            .with_columns(pl.col("order_date").dt.strftime(ISO_DATE_FORMAT))
            .iter_rows()
        )
        with closing(sqlite3.connect(staging)) as conn:
            conn.executescript(_read_sql("schema.sql"))
            with conn:
                conn.executemany(INSERT_ORDER, rows)
            conn.executescript(_read_sql("views.sql"))
        staging.replace(self._db_path)


def _read_sql(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")
