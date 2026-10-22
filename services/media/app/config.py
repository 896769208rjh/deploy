from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/media"
    internal_token: str = "dev-internal-token"
    jwt_secret: str = "dev-jwt-secret"
    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_access_key: str = "minio"
    minio_secret_key: str = "minio123456"
    minio_bucket: str = "media"
    sample_path: str = "/app/sample.mp4"
    local_storage: str = "/data/objects"


settings = Settings()
