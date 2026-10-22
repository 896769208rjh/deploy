from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/blog"
    internal_token: str = "dev-internal-token"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dim: int = 512


settings = Settings()
