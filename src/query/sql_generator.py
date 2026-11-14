"""Natural-language question → one SQLite SELECT, written by an LLM through PydanticAI."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError, ModelAPIError
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from src.constants import (
    ALLOWED_TABLES,
    COUNTRIES,
    DATA_END_DATE,
    DATA_START_DATE,
    PRODUCTS,
    ErrorCode,
    OrderStatus,
)
from src.db.ddl import DdlScript
from src.errors import AppError


class GeneratedQuery(BaseModel):
    sql: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        description="One SQLite SELECT statement that answers the question."
    )


class LLMUnavailableError(AppError):
    code = ErrorCode.LLM_UNAVAILABLE


class LLMInvalidOutputError(AppError):
    code = ErrorCode.LLM_INVALID_OUTPUT


class SqlGenerator:
    def __init__(self, model: Model | str, timeout: float) -> None:
        # No `str` in output_type: a plain-text reply must not end the run as an answer.
        self._agent = Agent(
            model,
            name="sql_generator",
            output_type=GeneratedQuery,
            instructions=_instructions(),
            model_settings=ModelSettings(request_timeout=timeout),
        )

    async def generate(self, question: str) -> str:
        try:
            result = await self._agent.run(question)
        except ModelAPIError as exc:
            raise LLMUnavailableError(
                "El modelo de lenguaje no responde. Inténtalo de nuevo más tarde."
            ) from exc
        except AgentRunError as exc:
            # Refusal, text instead of SQL, empty SQL after retries, token or usage limit.
            raise LLMInvalidOutputError(
                "El modelo de lenguaje no devolvió una consulta SQL utilizable."
            ) from exc
        return result.output.sql


def _instructions() -> str:
    return f"""\
You write SQLite queries that answer questions about sales orders. The questions are usually
in Spanish.

Write exactly one read-only SELECT statement (WITH and UNION are allowed). Read only these
tables and views: {", ".join(sorted(ALLOWED_TABLES))}. Their definitions:

{DdlScript.SCHEMA.read()}
{DdlScript.VIEWS.read()}
Facts about the data:
- Sales means orders with status = '{OrderStatus.COMPLETED}'. The views already apply this
  rule; apply it yourself when you query `orders` about sales or revenue.
- `order_date` is ISO text 'YYYY-MM-DD' from {DATA_START_DATE} to {DATA_END_DATE}. Use
  substr(order_date, 1, 7) for the month.
- `country` is one of: {", ".join(COUNTRIES)}. Write these values exactly, with accents.
- `product` is one of: {", ".join(PRODUCTS)}.

Give computed columns short aliases. Round money to 2 decimals.
"""
