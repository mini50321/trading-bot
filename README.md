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
PO_API_BASE_URL=https://example.com
PO_LOGIN_PATH=/api/login
PO_PROFILE_PATH=/api/profile
PO_BALANCE_PATH=/api/balance
PO_WS_URL=wss://example.com/ws
PO_WS_SUBSCRIBE_ACTION=subscribe
PO_WS_SYMBOL_KEY=symbol
PO_WS_PRICE_KEY=price
PO_WS_TIMESTAMP_KEY=ts
MASTER_KEY=change_me
ADMIN_API_KEY=change_me_too
HTTP_HOST=0.0.0.0
HTTP_PORT=8000
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
- users: `GET /admin/users?limit=50`
- trades: `GET /admin/trades?limit=50`
- global trading: `GET /admin/system`, `POST /admin/system/global_on`, `POST /admin/system/global_off`

send header `x-api-key: <ADMIN_API_KEY>`

### docker
```bash
docker compose up --build
```

### features
- telegram onboarding
- per-user settings stored in mongodb
- enable/disable trading toggle (stage 1 only stores state)
- pocketoption connect/disconnect + account check (stage 2)
- websocket market data watcher + latest prices (stage 3)
- webhook receiver + trade scheduling (stage 4)
- risk controls + global kill switch (stage 5)
- admin commands: list users, block/unblock user
- event logging to mongodb

