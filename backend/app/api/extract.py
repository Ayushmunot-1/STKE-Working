"""
STKE Extract API
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.schemas import ExtractionRequest, ExtractionResponse
from app.services.extraction_service import extraction_service
from app.services.ollama_service import ollama_service
from app.nlp.rule_engine import detect_context_from_text

router = APIRouter()


@router.post("/", response_model=ExtractionResponse)
async def extract_tasks(
    payload: ExtractionRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    context = payload.source_context
    if not context or context in ("webpage", "auto"):
        context = detect_context_from_text(payload.text)

    try:
        return await extraction_service.extract_and_save(
            text=payload.text,
            user_id=user_id,
            source_url=payload.source_url,
            source_context=context,
            auto_create=payload.auto_create_tasks,
            db=db,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@router.get("/health")
async def health():
    return await ollama_service.check_health()