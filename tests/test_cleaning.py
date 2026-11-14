from datetime import date

import polars as pl
import pytest

from src.constants import ORDER_COLUMNS
from src.pipeline.cleaning import RAW_SCHEMA, CleaningReport, DropReason, clean_orders
from src.pipeline.generate import OrderGenerator

MIN_CLEAN_ORDERS = 1_000  # requirement of the exercise
VALID_ROW = ("1", "2025-03-14", "Ana Ruiz", "España", "Monitor", "120.50", "completed")


def raw_orders(*rows: tuple[str | None, ...]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=RAW_SCHEMA, orient="row")


def row(**overrides: str | None) -> tuple[str | None, ...]:
    values = dict(zip(ORDER_COLUMNS, VALID_ROW, strict=True)) | overrides
    return tuple(values[column] for column in ORDER_COLUMNS)


def report(read: int, kept: int, **dropped: int) -> CleaningReport:
    counts = dict.fromkeys(DropReason, 0) | {DropReason(k): v for k, v in dropped.items()}
    return CleaningReport(read=read, kept=kept, dropped=counts)


@pytest.mark.parametrize(
    "raw_date", ["2025-03-14", "14/03/2025", "14-03-2025", "2025/03/14", " 2025-03-14 "]
)
def test_normalizes_date_formats(raw_date: str) -> None:
    clean, _ = clean_orders(raw_orders(row(order_date=raw_date)))

    assert clean["order_date"].to_list() == [date(2025, 3, 14)]


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("order_id", "abc", DropReason.INVALID_ID),
        ("order_date", "31/02/2025", DropReason.INVALID_DATE),
        ("order_date", "ayer", DropReason.INVALID_DATE),
        ("order_date", None, DropReason.INVALID_DATE),
        ("amount", None, DropReason.INVALID_AMOUNT),
        ("amount", "N/A", DropReason.INVALID_AMOUNT),
        ("amount", "-35.50", DropReason.INVALID_AMOUNT),
        ("amount", "0", DropReason.INVALID_AMOUNT),
        ("status", "refunded", DropReason.UNKNOWN_STATUS),
        ("country", "Narnia", DropReason.UNKNOWN_COUNTRY),
    ],
)
def test_drops_invalid_row(column: str, value: str | None, reason: DropReason) -> None:
    clean, result = clean_orders(raw_orders(row(**{column: value})))

    assert clean.is_empty()
    assert result == report(read=1, kept=0, **{reason: 1})


def test_keeps_first_valid_duplicate_and_normalizes_it() -> None:
    raw = raw_orders(
        row(amount=None),
        row(customer="  Ana Ruiz ", amount=" 99.999 ", status=" COMPLETED"),
        row(amount="1.00"),
    )

    clean, result = clean_orders(raw)

    assert clean.rows() == [
        (1, date(2025, 3, 14), "Ana Ruiz", "España", "Monitor", 100.0, "completed")
    ]
    assert result == report(read=3, kept=1, invalid_amount=1, duplicate=1)


def test_generated_dataset_has_every_defect_and_enough_clean_rows() -> None:
    _, result = clean_orders(OrderGenerator().generate())

    assert result.kept >= MIN_CLEAN_ORDERS
    for reason in (
        DropReason.DUPLICATE,
        DropReason.INVALID_DATE,
        DropReason.INVALID_AMOUNT,
    ):
        assert result.dropped[reason] > 0
