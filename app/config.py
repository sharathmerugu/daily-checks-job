from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Defaults point at the compose stack's Postgres from the host (see README).
    database_url: str = "postgresql+psycopg://checks:checks@localhost:55432/checks"
    test_database_url: str = "postgresql+psycopg://checks:checks@localhost:55432/checks_test"
    redis_url: str = "redis://localhost:6379/0"


settings = Settings()
