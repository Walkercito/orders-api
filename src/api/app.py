"""Composition root: builds every dependency from Settings and serves the API."""

import uvicorn
from fastapi import FastAPI
from pydantic_ai.exceptions import UserError

from src.api.v1.completion import completion_router
from src.config import Settings
from src.db.reader import OrdersReader
from src.query.sql_generator import SqlGenerator


def create_app(generator: SqlGenerator, reader: OrdersReader) -> FastAPI:
    app = FastAPI(
        title="Orders API",
        description="Preguntas en lenguaje natural sobre los pedidos, respondidas con SQL.",
    )
    app.include_router(completion_router(generator, reader), prefix="/v1")
    return app


def main() -> None:
    settings = Settings()
    if not settings.db_path.exists():
        raise SystemExit(f"No existe {settings.db_path}. Ejecuta primero: uv run etl")
    try:
        generator = SqlGenerator(settings.llm_model, settings.llm_timeout)
    except UserError as exc:
        raise SystemExit(
            f"No se pudo configurar el modelo {settings.llm_model}: {exc}\n"
            "Revisa .env y arranca con: uv run --env-file .env serve"
        ) from exc
    reader = OrdersReader(settings.db_path, settings.query_timeout)
    uvicorn.run(
        create_app(generator, reader), host=settings.api_host, port=settings.api_port
    )
