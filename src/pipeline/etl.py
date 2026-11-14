"""Read the raw CSV, clean it and rebuild the SQLite database with its views."""

from typing import Final

import polars as pl
import structlog

from src.config import Settings
from src.db.loader import OrdersLoader
from src.pipeline.cleaning import RAW_SCHEMA, clean_orders

logger = structlog.get_logger(__name__)
# One event per run: every count of the cleaning report in one entry.
ETL_EVENT: Final = "etl_finished"


def main() -> None:
    settings = Settings()
    if not settings.csv_path.exists():
        raise SystemExit(f"No existe {settings.csv_path}. Ejecuta primero: uv run generate")

    raw = pl.read_csv(settings.csv_path, schema=RAW_SCHEMA)
    orders, report = clean_orders(raw)
    OrdersLoader(settings.db_path).rebuild(orders)

    logger.info(
        ETL_EVENT,
        read=report.read,
        kept=report.kept,
        db_path=str(settings.db_path),
        **{f"dropped_{reason}": count for reason, count in report.dropped.items()},
    )
