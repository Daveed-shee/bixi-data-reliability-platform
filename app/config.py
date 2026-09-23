from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./bixi.db"
    redis_url: str = "redis://localhost:6379/0"
    bixi_gbfs_url: str = "https://gbfs.velobixi.com/gbfs/gbfs.json"
    max_feed_age_minutes: int = 15

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

