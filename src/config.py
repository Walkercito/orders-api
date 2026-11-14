from pathlib import Path

from pydantic import PositiveFloat
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": .env also holds provider keys that PydanticAI reads on its own.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    csv_path: Path = Path("data/orders_raw.csv")
    db_path: Path = Path("data/orders.db")

    # PydanticAI model string; another vendor needs only its extra and a new string.
    llm_model: str = "openrouter:anthropic/claude-sonnet-5.5"
    # Seconds for the whole model request, SDK retries included.
    llm_timeout: PositiveFloat = 30.0
    # Seconds a validated query may run before SQLite interrupts it.
    query_timeout: PositiveFloat = 5.0

    api_host: str = "127.0.0.1"
    api_port: int = 8000
