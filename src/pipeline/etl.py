"""Read the raw CSV, clean it and rebuild the SQLite database with its views."""

import polars as pl

from src.config import Settings
from src.db.loader import OrdersLoader
from src.pipeline.cleaning import RAW_SCHEMA, clean_orders


def main() -> None:
    settings = Settings()
    if not settings.csv_path.exists():
        raise SystemExit(f"No existe {settings.csv_path}. Ejecuta primero: uv run generate")

    raw = pl.read_csv(settings.csv_path, schema=RAW_SCHEMA)
    orders, report = clean_orders(raw)
    OrdersLoader(settings.db_path).rebuild(orders)

    print(f"Filas leídas: {report.read}")
    for reason, count in report.dropped.items():
        print(f"  descartadas ({reason}): {count}")
    print(f"Filas cargadas: {report.kept} en {settings.db_path}")
