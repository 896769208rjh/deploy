from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    jwt_secret: str = "dev-jwt-secret"
    internal_token: str = "dev-internal-token"
    identity_url: str = "http://localhost:8001"
    workflow_url: str = "http://localhost:8002"
    media_url: str = "http://localhost:8003"
    blog_url: str = "http://localhost:8004"
    bookmark_url: str = "http://localhost:8005"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"


settings = Settings()
