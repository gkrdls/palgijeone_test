"""Load local prototype settings without overriding process environment variables."""

from pathlib import Path


PROJECT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


def load_project_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError(
            "python-dotenv is missing. Install requirements.txt first."
        ) from exc

    load_dotenv(
        dotenv_path=PROJECT_ENV_FILE,
        override=False,
        interpolate=False,
        encoding="utf-8-sig",
    )
