from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    SECRET_KEY: str = "changeme"
    DATABASE_URL: str = "sqlite+aiosqlite:///./stke.db"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"

    SPACY_MODEL: str = "en_core_web_sm"
    SIMILARITY_THRESHOLD: float = 0.85

    DEBUG: bool = False

    class Config:
        env_file = ".env"


settings = Settings()