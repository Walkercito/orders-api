from datetime import date
from enum import StrEnum
from typing import Final


class OrderStatus(StrEnum):
    COMPLETED = "completed"
    PENDING = "pending"
    CANCELLED = "cancelled"


COUNTRIES: Final = ("España", "México", "Argentina", "Colombia", "Chile", "Perú")

PRODUCTS: Final = (
    "Portátil",
    "Monitor",
    "Teclado",
    "Ratón",
    "Auriculares",
    "Impresora",
    "Tablet",
    "Webcam",
    "Disco SSD",
    "Router",
)

# Single source for column order: CSV header, cleaning output and INSERT statement.
ORDER_COLUMNS: Final = (
    "order_id",
    "order_date",
    "customer",
    "country",
    "product",
    "amount",
    "status",
)

ISO_DATE_FORMAT: Final = "%Y-%m-%d"
# ISO first, then day-first: the data is from Spanish-speaking markets, so "03/04/2025" is
# 3 April, never 4 March.
DATE_FORMATS: Final = (ISO_DATE_FORMAT, "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")

DATA_START_DATE: Final = date(2025, 1, 1)
DATA_END_DATE: Final = date(2025, 12, 31)
