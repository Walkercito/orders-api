"""POST /v1/completion: question → LLM SQL → validate_sql → read-only query."""

import time
from typing import Final

import structlog
from fastapi import APIRouter, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from src.api.v1.schemas import (
    CompletionRequest,
    CompletionResponse,
    ErrorDetail,
    ErrorResponse,
)
from src.constants import ErrorCode
from src.db.reader import OrdersReader
from src.errors import AppError
from src.query.sql_generator import SqlGenerator
from src.query.sql_guard import validate_sql

logger = structlog.get_logger(__name__)

# The one wide event per request: question, SQL, status, error and duration in one entry.
COMPLETION_EVENT: Final = "completion_handled"

HTTP_STATUS: Final = {
    ErrorCode.LLM_UNAVAILABLE: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.LLM_INVALID_OUTPUT: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.UNSAFE_QUERY: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.QUERY_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
}
ERROR_RESPONSES: Final[dict[int | str, dict[str, object]]] = {
    code: {"model": ErrorResponse} for code in set(HTTP_STATUS.values())
}


def completion_router(generator: SqlGenerator, reader: OrdersReader) -> APIRouter:
    router = APIRouter()

    @router.post("/completion", responses=ERROR_RESPONSES)
    async def completion(request: CompletionRequest) -> CompletionResponse:
        started = time.perf_counter()
        log = logger.bind(question=request.question)
        sql: str | None = None
        try:
            sql = await generator.generate(request.question)
            sql = validate_sql(sql)
            # sqlite3 blocks; keep it off the event loop.
            result = await run_in_threadpool(reader.run, sql)
        except AppError as exc:
            # `sql` is the raw LLM text when the guard rejected it, else the validated SQL.
            log.warning(
                COMPLETION_EVENT,
                sql=sql,
                status_code=HTTP_STATUS[exc.code],
                error_code=exc.code,
                error=str(exc),
                cause=repr(exc.__cause__),
                duration_ms=_elapsed_ms(started),
            )
            detail = ErrorDetail(code=exc.code, message=str(exc))
            raise HTTPException(HTTP_STATUS[exc.code], detail.model_dump()) from exc
        log.info(
            COMPLETION_EVENT,
            sql=sql,
            status_code=status.HTTP_200_OK,
            rows=len(result.rows),
            duration_ms=_elapsed_ms(started),
        )
        return CompletionResponse(
            question=request.question,
            sql=sql,
            columns=result.columns,
            rows=[list(row) for row in result.rows],
        )

    return router


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
