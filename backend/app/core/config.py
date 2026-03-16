from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────
    SECRET_KEY: str = "changeme"
    DATABASE_URL: str = "sqlite+aiosqlite:///./stke.db"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    DEBUG: bool = False

    # ── Ollama (optional — not used for extraction) ───────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"

    # ── NLP ───────────────────────────────────────────────────
    SPACY_MODEL: str = "en_core_web_sm"

    # Deduplication thresholds — tune in .env without touching code
    # SIMILARITY_THRESHOLD       → comparing against saved DB tasks
    # BATCH_SIMILARITY_THRESHOLD → comparing within current extraction batch
    SIMILARITY_THRESHOLD: float = 0.85
    BATCH_SIMILARITY_THRESHOLD: float = 0.90

    # ── Google OAuth ──────────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"   # silently ignore any undeclared .env keys


settings = Settings()