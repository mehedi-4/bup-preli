import os
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

class Config:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()

    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

    PRIMARY_PROVIDER: str = os.getenv(
        "PRIMARY_PROVIDER", 
        "openai" if os.getenv("OPENAI_API_KEY", "").strip() else "gemini"
    ).strip().lower()

    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "25.0"))

settings = Config()
