from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/workflow"
    checkpoint_database_url: str = "postgresql://postgres:postgres@localhost:5432/agent"
    internal_token: str = "dev-internal-token"
    jwt_secret: str = "dev-jwt-secret"
    media_url: str = "http://localhost:8003"


settings = Settings()
