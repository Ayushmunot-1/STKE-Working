"""
STKE Ollama Service — Health check only
Extraction is handled by the fast rule engine
"""

import httpx
import logging

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434"
MODEL = "llama3.2"


class OllamaService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10.0)

    async def check_health(self) -> dict:
        try:
            resp = await self.client.get(f"{OLLAMA_BASE}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            names = [m.get("name", "") for m in models]
            has_model = any(MODEL.split(":")[0] in n for n in names)
            return {
                "ollama_running": True,
                "model_available": has_model,
                "model": MODEL,
                "available_models": names,
            }
        except Exception as e:
            return {
                "ollama_running": False,
                "model_available": False,
                "model": MODEL,
                "error": str(e),
            }


ollama_service = OllamaService()