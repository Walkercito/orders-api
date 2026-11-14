"""Pure cleaning of raw order rows: parse, validate, deduplicate. No I/O."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import polars as pl

from src.constants import COUNTRIES, DATE_FORMATS, ORDER_COLUMNS, OrderStatus

# Input contract: every column is text. Cleaning owns all parsing.
RAW_SCHEMA: Final = pl.Schema(dict.fromkeys(ORDER_COLUMNS, pl.String))


class DropReason(StrEnum):
    INVALID_ID = "invalid_id"
    INVALID_DATE = "invalid_date"
    INVALID_AMOUNT = "invalid_amount"
    UNKNOWN_STATUS = "unknown_status"
    UNKNOWN_COUNTRY = "unknown_country"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class CleaningReport:
    read: int
    kept: int
    dropped: dict[DropReason, int]


# Applied in order; a row is counted under the first rule it fails. A null comparison
# result counts as a failure, which covers empty and unparseable values.
RULES: Final = (
    (DropReason.INVALID_ID, pl.col("order_id").is_not_null()),
    (DropReason.INVALID_DATE, pl.col("order_date").is_not_null()),
    (DropReason.INVALID_AMOUNT, pl.col("amount") > 0),
    (DropReason.UNKNOWN_STATUS, pl.col("status").is_in([s.value for s in OrderStatus])),
    (DropReason.UNKNOWN_COUNTRY, pl.col("country").is_in(COUNTRIES)),
)


def clean_orders(raw: pl.DataFrame) -> tuple[pl.DataFrame, CleaningReport]:
    """Return the valid, deduplicated orders and how many rows each rule dropped."""
    orders = _parse(raw)
    dropped: dict[DropReason, int] = {}
    for reason, is_valid in RULES:
        valid = orders.filter(is_valid)
        dropped[reason] = orders.height - valid.height
        orders = valid
    # Dedupe after validation, so an invalid first copy does not hide a valid later one.
    unique = orders.unique(subset="order_id", keep="first", maintain_order=True)
    dropped[DropReason.DUPLICATE] = orders.height - unique.height
    return unique, CleaningReport(read=raw.height, kept=unique.height, dropped=dropped)


def _parse(raw: pl.DataFrame) -> pl.DataFrame:
    raw_date = pl.col("order_date").str.strip_chars()
    return raw.select(
        pl.col("order_id").str.strip_chars().cast(pl.Int64, strict=False),
        pl.coalesce(
            [raw_date.str.to_date(fmt, strict=False) for fmt in DATE_FORMATS]
        ).alias("order_date"),
        pl.col("customer", "country", "product").str.strip_chars(),
        pl.col("amount").str.strip_chars().cast(pl.Float64, strict=False).round(2),
        pl.col("status").str.strip_chars().str.to_lowercase(),
    )
