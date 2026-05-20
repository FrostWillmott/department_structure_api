from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/department_api"
    )

    model_config = {"env_file": ".env"}


settings = Settings()
