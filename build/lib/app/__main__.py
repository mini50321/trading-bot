import asyncio

from pydantic_core import ValidationError

from app.bot.runner import run_bot


def main() -> None:
    try:
        asyncio.run(run_bot())
    except ValidationError as e:
        if "bot_token" in str(e):
            raise SystemExit(
                "missing config. create .env with BOT_TOKEN, MONGODB_URI, MONGODB_DB.\n"
                "see README.md and .env.example."
            ) from e
        raise


if __name__ == "__main__":
    main()

