from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "QuantX AI API"
    app_version: str = "0.1.0"
    environment: str = "development"

    database_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 1440

    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    allowed_methods: list[str] = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
    allowed_headers: list[str] = ["Authorization", "Content-Type"]
    allow_credentials: bool = True
    log_level: str = "info"

    # OAuth providers
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/oauth/{provider}/callback"

    # Market data
    binance_ws_base: str = "wss://stream.binance.com:9443"
    binance_rest_base: str = "https://api.binance.com"
    market_reconnect_delay: float = 1.0
    market_reconnect_max_delay: float = 30.0
    market_subscribed_symbols: list[str] = ["btcusdt", "ethusdt", "solusdt", "xrpusdt", "dogeusdt"]

    # Paper trading / live trading
    enable_live_trading: bool = False


settings = Settings()
