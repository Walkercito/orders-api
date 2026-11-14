from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx2
import polars as pl
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pydantic_ai import models
from pydantic_ai.exceptions import ContentFilterError, ModelAPIError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from structlog.testing import capture_logs

from src.api.app import create_app
from src.api.v1.completion import COMPLETION_EVENT
from src.constants import (
    ALLOWED_TABLES,
    COUNTRIES,
    MAX_QUESTION_LENGTH,
    MAX_ROWS,
    PRODUCTS,
    ErrorCode,
    OrderStatus,
)
from src.db.loader import OrdersLoader
from src.db.reader import MAX_COLUMNS, MAX_VALUE_BYTES, OrdersReader
from src.query.sql_generator import SQL_TOOL, UNANSWERABLE_TOOL, SqlGenerator
from src.query.sql_guard import validate_sql

type Reply = Callable[[list[ModelMessage], AgentInfo], ModelResponse]

# Only the FunctionModels below may answer: a real provider call fails the test.
models.ALLOW_MODEL_REQUESTS = False

LLM_TIMEOUT = 1.0
QUERY_TIMEOUT = 0.1
QUESTION = "¿Quiénes son los mejores clientes?"
TOP_CUSTOMERS_SQL = "SELECT customer, total_amount FROM top_customers"
REASON = "No hay datos del clima."
# COUNT never ends on an endless CTE and LIMIT does not stop it: only the deadline does.
ENDLESS_SQL = (
    "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) "
    "SELECT COUNT(*) FROM n, orders"
)
# Each value is under MAX_VALUE_BYTES; MAX_ROWS of them pass MAX_RESULT_BYTES.
HUGE_RESULT_SQL = (
    f"WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < {MAX_ROWS}) "
    f"SELECT zeroblob({MAX_VALUE_BYTES // 2}) FROM n, orders"
)
ORDERS = pl.DataFrame(
    {
        "order_id": [1, 2, 3],
        "order_date": [date(2025, 1, 5), date(2025, 1, 20), date(2025, 2, 3)],
        "customer": ["Ana Ruiz", "Luis Gómez", "Ana Ruiz"],
        "country": [COUNTRIES[0], COUNTRIES[1], COUNTRIES[0]],
        "product": [PRODUCTS[0], PRODUCTS[1], PRODUCTS[0]],
        "amount": [100.0, 50.5, 20.0],
        "status": [OrderStatus.COMPLETED, OrderStatus.COMPLETED, OrderStatus.CANCELLED],
    }
)


def calls(tool: str, **args: str) -> Reply:
    def reply(_: list[ModelMessage], __: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(tool, args)])

    return reply


def returns_sql(sql: str) -> Reply:
    return calls(SQL_TOOL, sql=sql)


def returns_text(_: list[ModelMessage], __: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("No puedo responder a eso.")])


def is_down(_: list[ModelMessage], __: AgentInfo) -> ModelResponse:
    raise ModelAPIError("function", "Servicio no disponible")


def is_filtered(_: list[ModelMessage], __: AgentInfo) -> ModelResponse:
    raise ContentFilterError("Content filter triggered")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "orders.db"
    OrdersLoader(path).rebuild(ORDERS)
    return path


def ask(db_path: Path, reply: Reply, question: str = QUESTION) -> httpx2.Response:
    generator = SqlGenerator(FunctionModel(reply), LLM_TIMEOUT)
    app = create_app(generator, OrdersReader(db_path, QUERY_TIMEOUT))
    return TestClient(app).post("/v1/completion", json={"question": question})


@pytest.mark.parametrize(
    ("sql", "columns", "rows"),
    [
        # The cancelled order is not a sale, so Ana Ruiz has 100.0, not 120.0.
        pytest.param(
            TOP_CUSTOMERS_SQL,
            ["customer", "total_amount"],
            [["Ana Ruiz", 100.0], ["Luis Gómez", 50.5]],
            id="sales-view",
        ),
        pytest.param(
            "SELECT x'ff00' AS b FROM orders LIMIT 1",
            ["b"],
            [["_wA="]],
            id="blob-as-base64",
        ),
    ],
)
def test_answers_with_validated_sql_and_rows(
    db_path: Path, sql: str, columns: list[str], rows: list[list[object]]
) -> None:
    with capture_logs() as logs:
        response = ask(db_path, returns_sql(sql))

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "question": QUESTION,
        "sql": validate_sql(sql),
        "columns": columns,
        "rows": rows,
    }
    [event] = logs
    assert event["event"] == COMPLETION_EVENT
    assert event["rows"] == len(response.json()["rows"])


@pytest.mark.parametrize(
    ("reply", "status_code", "code"),
    [
        pytest.param(
            returns_sql("DELETE FROM orders"),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.UNSAFE_QUERY,
            id="unsafe-sql",
        ),
        pytest.param(
            returns_sql("SELECT nope FROM orders"),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.QUERY_FAILED,
            id="unknown-column",
        ),
        pytest.param(
            returns_sql(ENDLESS_SQL),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.QUERY_FAILED,
            id="query-timeout",
        ),
        pytest.param(
            returns_sql(f"SELECT zeroblob({MAX_VALUE_BYTES + 1}) FROM orders"),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.QUERY_FAILED,
            id="value-too-big",
        ),
        pytest.param(
            returns_sql(f"SELECT {', '.join(['1'] * (MAX_COLUMNS + 1))} FROM orders"),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.QUERY_FAILED,
            id="too-many-columns",
        ),
        pytest.param(
            returns_sql(HUGE_RESULT_SQL),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.QUERY_FAILED,
            id="result-too-big",
        ),
        pytest.param(
            calls(UNANSWERABLE_TOOL, reason=REASON),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.UNANSWERABLE,
            id="cannot-answer",
        ),
        pytest.param(
            is_filtered,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.UNANSWERABLE,
            id="content-filter",
        ),
        pytest.param(
            is_down, status.HTTP_502_BAD_GATEWAY, ErrorCode.LLM_UNAVAILABLE, id="model-down"
        ),
        pytest.param(
            returns_text,
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.LLM_INVALID_OUTPUT,
            id="text-instead-of-sql",
        ),
        pytest.param(
            returns_sql("   "),
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.LLM_INVALID_OUTPUT,
            id="blank-sql",
        ),
    ],
)
def test_maps_each_failure_to_an_error_code(
    db_path: Path, reply: Reply, status_code: int, code: ErrorCode
) -> None:
    with capture_logs() as logs:
        response = ask(db_path, reply)

    assert response.status_code == status_code
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["message"]
    [event] = logs
    assert event["event"] == COMPLETION_EVENT
    assert event["error_code"] == code
    assert event["status_code"] == status_code


def test_cannot_answer_returns_the_model_reason(db_path: Path) -> None:
    response = ask(db_path, calls(UNANSWERABLE_TOOL, reason=f"  {REASON} "))

    assert response.json()["detail"]["message"] == REASON


def test_prompt_describes_the_data(db_path: Path) -> None:
    seen: list[str | None] = []

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info.instructions)
        return returns_sql(TOP_CUSTOMERS_SQL)(messages, info)

    ask(db_path, reply)

    [instructions] = seen
    assert instructions
    for term in [*ALLOWED_TABLES, *COUNTRIES, *PRODUCTS, OrderStatus.COMPLETED]:
        assert term in instructions


@pytest.mark.parametrize("question", ["", "   ", "x" * (MAX_QUESTION_LENGTH + 1)])
def test_rejects_invalid_question_before_the_model(db_path: Path, question: str) -> None:
    # is_down would give 502 if the model were called.
    response = ask(db_path, is_down, question)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
