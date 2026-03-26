from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "trading_bot"
    admin_telegram_ids: str = ""
    po_api_base_url: str = ""
    po_login_path: str = ""
    po_profile_path: str = ""
    po_balance_path: str = ""
    po_ws_url: str = ""
    po_ws_subscribe_action: str = "subscribe"
    po_ws_symbol_key: str = "symbol"
    po_ws_price_key: str = "price"
    po_ws_timestamp_key: str = "ts"
    master_key: str = ""
    admin_api_key: str = ""
    http_host: str = "0.0.0.0"
    http_port: int = 8000

    def admin_ids(self) -> set[int]:
        raw = self.admin_telegram_ids.strip()
        if not raw:
            return set()
        out: set[int] = set()
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.add(int(part))
            except ValueError:
                continue
        return out

    def require_master_key(self) -> str:
        if not self.master_key.strip():
            raise ValueError("MASTER_KEY is required for credential encryption")
        return self.master_key.strip()

    def require_bot_token(self) -> str:
        if not self.bot_token.strip():
            raise ValueError("BOT_TOKEN is required to run the telegram bot")
        return self.bot_token.strip()

    def require_admin_api_key(self) -> str:
        if not self.admin_api_key.strip():
            raise ValueError("ADMIN_API_KEY is required for admin api access")
        return self.admin_api_key.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

