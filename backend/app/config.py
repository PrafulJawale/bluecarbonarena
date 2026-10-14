from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "BLUECARBON ARENA"
    database_url: str = "sqlite:///./bluecarbon.db"
    secret_key: str = "dev-only-change-me-please-32chars-minimum"
    access_token_minutes: int = 480
    cors_origins: str = ("http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,"
                         "http://localhost:4173,http://127.0.0.1:4173")
    upload_dir: str = "./uploads"
    demo_mode: bool = True          # enables seed/demo shortcuts; MUST be false in production
    allow_registration: bool = True
    rate_limit_enabled: bool = True   # tests may set RATE_LIMIT_ENABLED=false
    rate_limit_login: str = "10/minute"
    rate_limit_register: str = "5/hour"


settings = Settings()
if settings.secret_key.startswith("dev-only"):
    import warnings
    warnings.warn("Using the built-in development SECRET_KEY. Set SECRET_KEY in .env for any non-local deployment.")
