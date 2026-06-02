from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    postmark_server_token: str = ""
    postmark_from_email: str = "faktura@tvoje-domena.cz"
    inbound_email: str = "prijem@tvoje-domena.cz"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    invoice_price_czk: int = 29
    database_url: str = "postgresql://localhost/fakturobot"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    base_url: str = "http://localhost:8000"
    secret_key: str = "dev-secret-change-in-production"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
