from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "trading_bot"
    admin_telegram_ids: str = ""
    webhook_secret: str = ""
    webhook_hmac_secret: str = ""
    webhook_rate_limit_per_minute: int = 120
    webhook_trust_x_forwarded_for: bool = False
    global_min_payout_percent: float = 0.0
    po_api_base_url: str = ""
    po_login_path: str = ""
    po_profile_path: str = ""
    po_balance_path: str = ""
    po_place_trade_path: str = ""
    po_trade_field_asset_id: str = "asset_id"
    po_trade_field_amount: str = "amount"
    po_trade_field_direction: str = "direction"
    po_trade_field_expiry: str = "expiry_seconds"
    po_trade_direction_up: str = "up"
    po_trade_direction_down: str = "down"
    po_trade_body_extra_json: str = ""
    po_trade_response_broker_id_path: str = "id"
    po_trade_result_path_template: str = ""
    po_trade_result_http_method: str = "GET"
    po_trade_result_post_json: str = ""
    po_trade_result_pnl_path: str = ""
    po_trade_result_state_path: str = "status"
    po_trade_result_exit_price_path: str = ""
    po_trade_result_win_states: str = "win,won,success"
    po_trade_result_loss_states: str = "loss,lost"
    po_trade_result_draw_states: str = "draw,tie,refund"
    po_trade_result_open_states: str = "open,pending,active,running"
    po_trade_result_poll_interval_seconds: float = 1.0
    po_trade_result_max_polls: int = 45
    po_trade_result_extra_wait_seconds: float = 0.0
    po_asset_map_json: str = ""
    po_ws_url: str = ""
    po_ws_subscribe_action: str = "subscribe"
    po_ws_symbol_key: str = "symbol"
    po_ws_price_key: str = "price"
    po_ws_timestamp_key: str = "ts"
    master_key: str = ""
    admin_api_key: str = ""
    http_host: str = "0.0.0.0"
    http_port: int = 8000
    settlement_poll_interval_seconds: float = 1.0
    log_level: str = "INFO"

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

    def optional_webhook_secret(self) -> str:
        return self.webhook_secret.strip()

    def optional_webhook_hmac_secret(self) -> str:
        return self.webhook_hmac_secret.strip()

    def optional_po_asset_map_json(self) -> str:
        return self.po_asset_map_json.strip()

    def pocketoption_place_trade_enabled(self) -> bool:
        return bool(self.po_api_base_url.strip() and self.po_place_trade_path.strip())

    def pocketoption_trade_result_enabled(self) -> bool:
        t = self.po_trade_result_path_template.strip()
        return bool(self.po_api_base_url.strip() and t and "{id}" in t)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

