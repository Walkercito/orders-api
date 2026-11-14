from typing import ClassVar

from src.constants import ErrorCode


class AppError(Exception):
    """A step of /v1/completion failed. The Spanish message goes to the API response."""

    code: ClassVar[ErrorCode]
