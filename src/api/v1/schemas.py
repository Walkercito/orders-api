from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from src.constants import MAX_QUESTION_LENGTH, ErrorCode
from src.db.reader import SqlValue


class CompletionRequest(BaseModel):
    question: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_LENGTH
        ),
    ]


class CompletionResponse(BaseModel):
    # The LLM can select a BLOB (`x'ff'`, randomblob()); raw bytes are not valid JSON text.
    model_config = ConfigDict(ser_json_bytes="base64")

    question: str
    sql: str
    columns: list[str]
    rows: list[list[SqlValue]]


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail
