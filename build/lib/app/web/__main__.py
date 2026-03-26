from app.config import get_settings
import uvicorn


def main() -> None:
    s = get_settings()
    uvicorn.run("app.web.app:app", host=s.http_host, port=int(s.http_port), reload=False)


if __name__ == "__main__":
    main()

