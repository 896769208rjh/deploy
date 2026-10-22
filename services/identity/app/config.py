from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/identity"
    jwt_secret: str = "dev-jwt-secret"
    jwt_ttl_minutes: int = 60 * 24
    internal_token: str = "dev-internal-token"
    admin_email: str = ""
    admin_password: str = ""


settings = Settings()
