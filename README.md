## stage 1 (telegram + mongodb)

### requirements
- python 3.10+
- a mongodb instance (local or atlas)
- a telegram bot token from `@botfather`

### setup
1. create `.env` in the project root:

```
BOT_TOKEN=your_telegram_bot_token
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=trading_bot
ADMIN_TELEGRAM_IDS=123456789,987654321
WEBHOOK_SECRET=change_me_webhook_secret
WEBHOOK_HMAC_SECRET=
WEBHOOK_RATE_LIMIT_PER_MINUTE=120
WEBHOOK_TRUST_X_FORWARDED_FOR=false
GLOBAL_MIN_PAYOUT_PERCENT=0
AFFILIATE_POSTBACK_SECRET=
AFFILIATE_POSTBACK_HMAC_SECRET=
AFFILIATE_TRUST_X_FORWARDED_FOR=false
STRATEGY_ENABLED_GLOBAL=false
STRATEGY_POLL_INTERVAL_SECONDS=1.0
STRATEGY_MIN_LEARNING_TICKS=30
STRATEGY_MIN_CONFIDENCE=0.65
STRATEGY_BUCKET_SECONDS=10
STRATEGY_SIGNAL_EXPIRY_SECONDS=5
STRATEGY_EMIT_COOLDOWN_SECONDS=3
PO_API_BASE_URL=https://example.com
PO_LOGIN_PATH=/api/login
PO_PROFILE_PATH=/api/profile
PO_BALANCE_PATH=/api/balance
PO_PLACE_TRADE_PATH=/api/trades
PO_TRADE_FIELD_ASSET_ID=asset_id
PO_TRADE_FIELD_AMOUNT=amount
PO_TRADE_FIELD_DIRECTION=direction
PO_TRADE_FIELD_EXPIRY=expiry_seconds
PO_TRADE_DIRECTION_UP=up
PO_TRADE_DIRECTION_DOWN=down
PO_TRADE_BODY_EXTRA_JSON=
PO_TRADE_RESPONSE_BROKER_ID_PATH=id
PO_TRADE_RESULT_PATH_TEMPLATE=/api/trades/{id}
PO_TRADE_RESULT_HTTP_METHOD=GET
PO_TRADE_RESULT_POST_JSON=
PO_TRADE_RESULT_PNL_PATH=profit
PO_TRADE_RESULT_STATE_PATH=status
PO_TRADE_RESULT_EXIT_PRICE_PATH=
PO_TRADE_RESULT_WIN_STATES=win,won,success
PO_TRADE_RESULT_LOSS_STATES=loss,lost
PO_TRADE_RESULT_DRAW_STATES=draw,tie,refund
PO_TRADE_RESULT_OPEN_STATES=open,pending,active,running
PO_TRADE_RESULT_POLL_INTERVAL_SECONDS=1.0
PO_TRADE_RESULT_MAX_POLLS=45
PO_TRADE_RESULT_EXTRA_WAIT_SECONDS=0
PO_ASSET_MAP_JSON={"eurusd_otc":{"id":"123","open":true,"payout":92,"otc":true}}
PO_WS_URL=wss://example.com/ws
PO_WS_SUBSCRIBE_ACTION=subscribe
PO_WS_SYMBOL_KEY=symbol
PO_WS_PRICE_KEY=price
PO_WS_TIMESTAMP_KEY=ts
MASTER_KEY=change_me
ADMIN_API_KEY=change_me_too
HTTP_HOST=0.0.0.0
HTTP_PORT=8000
LOG_LEVEL=INFO
SETTLEMENT_POLL_INTERVAL_SECONDS=1.0
```

2. install dependencies:

```bash
python -m pip install -U pip
python -m pip install .
```

3. run:

```bash
python -m app
```

4. run webhook server (separate process):

```bash
python -m app.web
```

### admin api
- health: `GET /health`
- stats: `GET /admin/stats`
- diagnostics: `GET /admin/diagnostics` (mongo ping, settlement worker running, broker flags, trade counts by status, errors last 24h)
- users: `GET /admin/users?limit=50`
- trades: `GET /admin/trades?limit=50&status=opened` (optional `status` filter)
- signals: `GET /admin/signals?limit=50`
- global trading: `GET /admin/system`, `POST /admin/system/global_on`, `POST /admin/system/global_off`

send header `x-api-key: <ADMIN_API_KEY>`

### logging
- `LOG_LEVEL` (e.g. `INFO`, `DEBUG`) — API and bot call `configure_logging` on startup.
- High-signal lines use `event=... k=v` pairs (e.g. `event=trade.opened`, `event=settlement.done`, `event=signal.dispatch`) for grep and log drains.

### webhook auth
- If `WEBHOOK_SECRET` is set, send header `x-webhook-secret: <WEBHOOK_SECRET>`.
- If `WEBHOOK_HMAC_SECRET` is set, send header `x-webhook-signature: sha256=<hex>` where `<hex>` is the lowercase hex digest of **HMAC-SHA256(secret, raw request body)** (same bytes FastAPI reads as JSON).
- If both are set, **both** checks must pass.
- **Rate limit**: per client IP, `WEBHOOK_RATE_LIMIT_PER_MINUTE` requests per rolling 60s window (set `0` to disable). Behind a reverse proxy, set `WEBHOOK_TRUST_X_FORWARDED_FOR=true` and ensure the proxy sets `X-Forwarded-For`.
- **Idempotency**: duplicate `(source, signal_id)` returns `status: duplicate` (unique index in MongoDB); use a stable `signal_id` per signal.

### affiliate tracking (postbacks)
The API exposes `POST /affiliate/postback` so Pocket Partners (or similar) can notify you that an email registered under your link. **Postbacks are used for affiliate verification only**: the handler sets `postback_received` / `last_postback_event` on `affiliate_accounts` and does **not** persist broker balance from the postback (use PocketOption APIs for balance/profile).

- If `AFFILIATE_POSTBACK_SECRET` is set, send header `x-affiliate-secret: <AFFILIATE_POSTBACK_SECRET>`.
- If `AFFILIATE_POSTBACK_HMAC_SECRET` is set, send header `x-affiliate-signature: sha256=<hex>` where `<hex>` is HMAC-SHA256(secret, raw request body).
- The handler stores the full raw payload in `affiliate_events` and merges verification fields into `affiliate_accounts` when `email` / `user_email` is present.

**Trading gate (`AFFILIATE_GATE_REQUIRED`, default `true`)**: auto-trades (webhook + strategy) are allowed only if the user has run `/connect` with the **same email** that received a postback, that email row has `telegram_id` equal to their Telegram id, and `postback_received` is true. Set `AFFILIATE_GATE_REQUIRED=false` for local dev without postbacks. `/status` shows `affiliate: verified` or `not_verified:<reason>`.

**Email confirmation (`AFFILIATE_EMAIL_CONFIRM_REQUIRED`, default `true`)**: when the affiliate gate is on, trading also requires `email_confirmed` on that affiliate row. Configure a separate Pocket Partners postback for the **Email confirmation** event (in addition to registration). Incoming JSON is classified using `AFFILIATE_EMAIL_CONFIRM_EVENTS` (comma-separated substrings matched case-insensitively against the event field), and optional payload keys `email_confirmed` / `email_verified` / `is_email_confirmed`. Set `AFFILIATE_EMAIL_CONFIRM_REQUIRED=false` to skip (e.g. staging).

### trade tokens (deposits → balance; spend per trade)
When **`TOKEN_SYSTEM_ENABLED=true`** (default):

- **Credits**: `POST /affiliate/postback` classifies **deposit** events via `TOKEN_DEPOSIT_EVENTS` (substring match on the event field, same style as email confirmation). The handler reads a USD amount from common keys (`amount`, `deposit`, `deposit_amount`, …). Conversion (defaults match the client brief): **below `TOKEN_DEPOSIT_MIN_USD` (20)** → 0 tokens; **$20 up to (but not including) `TOKEN_BRACKET_HIGH_MIN_USD` (100)** → **`TOKEN_BRACKET_LOW_GRANT` (15)** tokens per qualifying postback; **≥ 100** → **`floor(amount) * TOKEN_BRACKET_HIGH_PER_DOLLAR`** (default 1:1). If the postback includes `transaction_id` / `deposit_id` / similar, it is used to **dedupe** ledger rows so the same deposit is not credited twice. If the user has not `/connect`ed yet, tokens are stored as **`pending_tokens`** on `affiliate_accounts` and are applied on connect (**pending** increments are not deduped—prefer sending stable transaction ids in postbacks, or rely on dedupe after the account is linked).
- **Debits**: Each opened trade consumes **`TOKENS_PER_TRADE`** (default 1). Insufficient balance → `token_blocked`. If PocketOption **place** fails after a debit, tokens are **refunded** (`refund_place_failed`).
- **Telegram**: `/tokens` shows balance; `/status` includes `tokens:`. Admins: `/admin_tokens <telegram_id> <delta>` or `POST /admin/tokens/adjust` with JSON `{"telegram_id", "delta", "reason"}`.
- Disable for dev: `TOKEN_SYSTEM_ENABLED=false` or `TOKENS_PER_TRADE=0`.

### Martingale (7-lever stake ladder)
Per-user settings (Telegram **settings** menu):

- **martingale on/off**: after each **settled loss**, `martingale_step` advances (capped at `martingale_max_levels - 1`); stake = `stake` setting × multiplier for that step. After a **settled win**, step resets to **0**.
- **mg levels**: ladder length **1–20** (default **7**).
- **mg multipliers csv**: comma-separated factors vs **base** `stake` (default `1,2,4,8,16,32,64`). Fewer values than levels are padded by doubling the last; empty uses **2^step**.
- **Webhook/signal stake**: when martingale is **enabled**, payload `stake` is **ignored** so the ladder stays consistent for autotrading.
- **max_stake_per_trade** / **max_stake_per_day** still cap cumulative risk after the martingale stake is computed.

### strategy (bot makes decisions)
If `STRATEGY_ENABLED_GLOBAL=true`, the API runs a background worker that:
- scans users with `settings.strategy_enabled=true`
- watches their `assets` using WebSocket ticks
- emits internal `source=strategy` signals when momentum thresholds hit (config via `STRATEGY_*`)

### risk / payout
- Per-user (Telegram settings): **min payout %** (needs `payout` in `PO_ASSET_MAP_JSON`; unknown payout → trade blocked), **max stake per trade**, **max total stake per day** (sum of `stake` on all trades since UTC midnight).
- **GLOBAL_MIN_PAYOUT_PERCENT**: merged with each user’s `min_payout_percent` and **`TRADE_MIN_PAYOUT_FLOOR_PERCENT`** using **`max(...)`**. Set any of them to `0` to drop that term (floor defaults to **90** so OTC maps should list realistic `payout` values).
- **OTC-only (`TRADE_OTC_ONLY`, default `true`)**: each entry in `PO_ASSET_MAP_JSON` should include `"otc": true` for symbols you trade. `"otc": false` or omitting `otc` on a bare `"id"` string marks the row as non-OTC or unknown → **not tradable** while OTC-only is on. `/watch` warns if a symbol fails these checks.
- Strategy worker only runs the engine on symbols that **pass** OTC + payout rules (same floor as global merge; per-user min payout is still enforced again in `TradeEngine` per user).
- **Global trading kill switch**: `/global_off` / `/global_on` (admins) or admin API (unchanged).

Broker-side **live asset lists** are not auto-synced yet: fill `PO_ASSET_MAP_JSON` with your OTC symbols, broker `id`, `payout`, and `otc: true`. When PocketOption exposes a stable assets API in your deployment, a sync job can be added without changing the catalog schema.

### pocketoption trade result (settlement)
After expiry, if `PO_TRADE_RESULT_PATH_TEMPLATE` is set (must include `{id}`), the bot polls the broker until it can read **`PO_TRADE_RESULT_PNL_PATH`** (preferred) or a terminal **`PO_TRADE_RESULT_STATE_PATH`** value (matched against the `*_STATES` lists). If the result endpoint is not configured, settlement falls back to the local price-compare simulation.

### docker deployment
1. Copy `.env.example` to `.env` and set secrets (`BOT_TOKEN`, `MASTER_KEY`, `ADMIN_API_KEY`, etc.).
2. For services running **inside** Compose, point Mongo at the `mongo` hostname (not `localhost`):

```
MONGODB_URI=mongodb://mongo:27017
```

3. Start stack:

```bash
docker compose up --build
```

This runs **three** containers: `mongo`, `bot` (`python -m app`), and `api` (`python -m app.web` on port **8000**). The settlement worker runs inside the **api** process.

4. Health check:

```bash
curl -s http://localhost:8000/health
```

### example webhook payload
Minimal JSON body for `POST /webhook` (`Content-Type: application/json`):

```json
{
  "signal_id": "unique-id-per-signal",
  "symbol": "eurusd",
  "direction": "UP",
  "source": "webhook",
  "payload": {
    "stake": 5.0,
    "expiry_seconds": 60
  }
}
```

- **`signal_id`**: idempotency key (duplicate `(source, signal_id)` is rejected without re-trading).
- **`symbol`**: must match a user’s asset list and your `PO_ASSET_MAP_JSON` keys (lowercase).
- **`direction`**: `UP` or `DOWN`.
- **`payload`**: optional; stake / expiry override user defaults when present.

### curl examples (bash)
Replace placeholders. If `WEBHOOK_SECRET` is set:

```bash
curl -s -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "x-webhook-secret: YOUR_WEBHOOK_SECRET" \
  -d '{"signal_id":"demo-1","symbol":"eurusd","direction":"UP"}'
```

If `WEBHOOK_HMAC_SECRET` is set, sign the **exact** body bytes. Example (Linux/macOS with OpenSSL):

```bash
BODY='{"signal_id":"demo-2","symbol":"eurusd","direction":"DOWN"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "YOUR_HMAC_SECRET" | awk '{print $2}')
curl -s -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "x-webhook-signature: sha256=$SIG" \
  -d "$BODY"
```

Admin diagnostics (requires `ADMIN_API_KEY`):

```bash
curl -s http://localhost:8000/admin/diagnostics -H "x-api-key: YOUR_ADMIN_API_KEY"
```

### powershell (Windows) webhook example
```powershell
$body = '{"signal_id":"demo-ps-1","symbol":"eurusd","direction":"UP"}'
Invoke-RestMethod -Uri "http://localhost:8000/webhook" -Method Post `
  -ContentType "application/json" `
  -Headers @{ "x-webhook-secret" = "YOUR_WEBHOOK_SECRET" } `
  -Body $body
```

### smoke tests (pytest)
Install dev extras and run unit checks (no live MongoDB required):

```bash
python -m pip install -U pip
python -m pip install ".[dev]"
python -m pytest tests/ -q
```

### features
- telegram onboarding
- per-user settings stored in mongodb
- enable/disable trading toggle (stage 1 only stores state)
- pocketoption connect/disconnect + account check (stage 2)
- websocket market data watcher + latest prices (stage 3)
- webhook receiver + trade scheduling (stage 4)
- risk controls + global kill switch (stage 5)
- background settlement worker (api process polls due `opened` / `created` trades; no per-trade sleep on webhook)
- admin commands: list users, block/unblock user
- event logging to mongodb

