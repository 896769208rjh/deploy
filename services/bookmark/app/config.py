from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bookmark"
    internal_token: str = "dev-internal-token"
    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_access_key: str = "minio"
    minio_secret_key: str = "minio123456"
    minio_bucket: str = "bookmarks"
    local_storage: str = "/data/objects"


settings = Settings()
