from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": .env also holds provider keys that PydanticAI reads on its own.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    csv_path: Path = Path("data/orders_raw.csv")
    db_path: Path = Path("data/orders.db")
