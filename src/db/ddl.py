"""SQL scripts that define the database. The ETL runs them; the LLM prompt quotes them."""

from enum import StrEnum
from pathlib import Path
from typing import Final

SQL_DIR: Final = Path(__file__).parent


class DdlScript(StrEnum):
    SCHEMA = "schema.sql"
    VIEWS = "views.sql"

    def read(self) -> str:
        return (SQL_DIR / self).read_text(encoding="utf-8")
