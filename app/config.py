from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/department_api"
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
