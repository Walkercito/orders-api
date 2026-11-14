"""Write a seeded orders CSV with deliberate defects for the cleaning step to handle."""

from dataclasses import dataclass
from datetime import date
from typing import Final

import polars as pl
import structlog
from faker import Faker

from src.config import Settings
from src.constants import (
    COUNTRIES,
    DATA_END_DATE,
    DATA_START_DATE,
    DATE_FORMATS,
    ISO_DATE_FORMAT,
    PRODUCTS,
    OrderStatus,
)
from src.pipeline.cleaning import RAW_SCHEMA

logger = structlog.get_logger(__name__)
GENERATE_EVENT: Final = "csv_generated"

SEED: Final = 42
LOCALE: Final = "es_ES"
ORDER_COUNT: Final = 1_200
CUSTOMER_COUNT: Final = 150
AMOUNT_RANGE: Final = (5.0, 2_500.0)
STATUS_WEIGHTS: Final = {
    OrderStatus.COMPLETED: 80,
    OrderStatus.PENDING: 12,
    OrderStatus.CANCELLED: 8,
}

DUPLICATE_RATE: Final = 0.05
ALTERNATE_DATE_RATE: Final = 0.20
BAD_DATE_RATE: Final = 0.02
EMPTY_AMOUNT_RATE: Final = 0.03
BAD_AMOUNT_RATE: Final = 0.01
BAD_STATUS_RATE: Final = 0.01
NOISY_TEXT_RATE: Final = 0.10

UNPARSEABLE_DATES: Final = ("31/02/2025", "2025-13-07", "ayer", "")
INVALID_AMOUNTS: Final = ("N/A", "-35.50", "0")
UNKNOWN_STATUSES: Final = ("refunded", "???")

type RawRow = tuple[str | None, ...]


@dataclass(frozen=True, slots=True)
class Order:
    order_id: int
    order_date: date
    customer: str
    country: str
    product: str
    amount: float
    status: OrderStatus


class OrderGenerator:
    def __init__(self, seed: int = SEED) -> None:
        self._fake = Faker(LOCALE)
        self._fake.seed_instance(seed)
        # Faker's own RNG, so a single seed drives names, dates and defects.
        self._rng = self._fake.random

    def generate(self) -> pl.DataFrame:
        orders = self._orders()
        # Duplicates are rendered again, so a copy can differ in format from its original.
        duplicates = self._rng.sample(orders, k=round(len(orders) * DUPLICATE_RATE))
        rows = [self._render(order) for order in orders + duplicates]
        self._rng.shuffle(rows)
        return pl.DataFrame(rows, schema=RAW_SCHEMA, orient="row")

    def _orders(self) -> list[Order]:
        customers = [
            (self._fake.unique.name(), self._rng.choice(COUNTRIES))
            for _ in range(CUSTOMER_COUNT)
        ]
        buyers = self._rng.choices(customers, k=ORDER_COUNT)
        return [
            Order(
                order_id=order_id,
                order_date=self._fake.date_between(DATA_START_DATE, DATA_END_DATE),
                customer=customer,
                country=country,
                product=self._rng.choice(PRODUCTS),
                amount=round(self._rng.uniform(*AMOUNT_RANGE), 2),
                status=self._rng.choices(
                    list(STATUS_WEIGHTS), weights=list(STATUS_WEIGHTS.values())
                )[0],
            )
            for order_id, (customer, country) in enumerate(buyers, start=1)
        ]

    def _render(self, order: Order) -> RawRow:
        return (
            str(order.order_id),
            self._dirty_date(order.order_date),
            self._noisy(order.customer),
            self._noisy(order.country),
            self._noisy(order.product),
            self._dirty_amount(order.amount),
            self._dirty_status(order.status),
        )

    def _chance(self, rate: float) -> bool:
        return self._rng.random() < rate

    def _dirty_date(self, value: date) -> str:
        if self._chance(BAD_DATE_RATE):
            return self._rng.choice(UNPARSEABLE_DATES)
        if self._chance(ALTERNATE_DATE_RATE):
            return value.strftime(self._rng.choice(DATE_FORMATS[1:]))
        return value.strftime(ISO_DATE_FORMAT)

    def _dirty_amount(self, value: float) -> str | None:
        if self._chance(EMPTY_AMOUNT_RATE):
            return None
        if self._chance(BAD_AMOUNT_RATE):
            return self._rng.choice(INVALID_AMOUNTS)
        return f"{value:.2f}"

    def _dirty_status(self, status: OrderStatus) -> str:
        if self._chance(BAD_STATUS_RATE):
            return self._rng.choice(UNKNOWN_STATUSES)
        return self._noisy(status.upper() if self._chance(NOISY_TEXT_RATE) else status)

    def _noisy(self, text: str) -> str:
        return f"  {text} " if self._chance(NOISY_TEXT_RATE) else text


def main() -> None:
    settings = Settings()
    orders = OrderGenerator().generate()
    settings.csv_path.parent.mkdir(parents=True, exist_ok=True)
    orders.write_csv(settings.csv_path)
    logger.info(GENERATE_EVENT, rows=orders.height, csv_path=str(settings.csv_path))
