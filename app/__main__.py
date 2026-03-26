import asyncio

from pydantic_core import ValidationError

from app.bot.runner import run_bot


def main() -> None:
    try:
        asyncio.run(run_bot())
    except ValidationError as e:
        raise SystemExit(
            "missing config. create .env with BOT_TOKEN, MONGODB_URI, MONGODB_DB.\n"
            "see README.md and .env.example."
        ) from e
    except ValueError as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()

