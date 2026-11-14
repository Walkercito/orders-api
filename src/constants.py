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

# The only tables and views that LLM-written SQL may read.
ALLOWED_TABLES: Final = frozenset({"orders", "monthly_sales_by_country", "top_customers"})
# Upper bound on rows per API query; validate_sql adds or lowers LIMIT to it.
MAX_ROWS: Final = 500
# Longest question POST /v1/completion accepts.
MAX_QUESTION_LENGTH: Final = 500


class ErrorCode(StrEnum):
    """`detail.code` of an API error response."""

    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_INVALID_OUTPUT = "llm_invalid_output"
    UNSAFE_QUERY = "unsafe_query"
    QUERY_FAILED = "query_failed"
