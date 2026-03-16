# """
# STKE Extract API — v2.0

# Changes from v1:
#   - Fetches current user's full_name/username from DB to pass into
#     extraction service for ownership resolution
#   - detect_context_from_text() called HERE once — not duplicated in service
#   - /health endpoint fixed: checks DB + spaCy, removes dead Ollama check
#   - Input validation now enforced via ExtractionRequest schema (max 50k chars)
#   - Specific exception handling instead of bare except
# """

# import logging
# from fastapi import APIRouter, Depends, HTTPException
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select

# from app.core.database import get_db
# from app.core.security import get_current_user_id
# from app.models.models import User
# from app.models.schemas import ExtractionRequest, ExtractionResponse
# from app.services.extraction_service import extraction_service
# from app.nlp.rule_engine import detect_context_from_text, nlp

# router = APIRouter()
# logger = logging.getLogger(__name__)


# @router.post("/", response_model=ExtractionResponse)
# async def extract_tasks(
#     payload: ExtractionRequest,
#     user_id: int = Depends(get_current_user_id),
#     db: AsyncSession = Depends(get_db),
# ):
#     """
#     Extract tasks, decisions, and dependencies from text.

#     Ownership resolution requires knowing the current user's name
#     so that pronouns (I/we/my) and chain inference work correctly.
#     """
#     # ── Resolve current user's display name ──────────────────
#     # We fetch the user once here and pass their name into the
#     # extraction service — this is the single source of truth
#     # for "who is the current user" throughout the pipeline.
#     user_result = await db.execute(select(User).where(User.id == user_id))
#     user = user_result.scalar_one_or_none()
#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")

#     # Prefer full_name for NER matching (e.g. "Ayush Munot"),
#     # fall back to username if full_name not set
#     current_user_name = user.full_name or user.username

#     # ── Detect context ONCE here ─────────────────────────────
#     # Previously this was called both here AND in extraction_service.
#     # Now it's called once and passed through cleanly.
#     context = payload.source_context
#     if not context or context in ("webpage", "auto"):
#         context = detect_context_from_text(payload.text)

#     # ── Run extraction pipeline ───────────────────────────────
#     try:
#         return await extraction_service.extract_and_save(
#             text=payload.text,
#             user_id=user_id,
#             current_user_name=current_user_name,
#             source_url=payload.source_url,
#             source_context=context,
#             auto_create=payload.auto_create_tasks,
#             db=db,
#         )
#     except ValueError as e:
#         # Input validation errors (e.g. text too short after preprocessing)
#         raise HTTPException(status_code=422, detail=str(e))
#     except RuntimeError as e:
#         # NLP pipeline errors (e.g. spaCy model not loaded)
#         logger.error("NLP pipeline error for user %d: %s", user_id, e)
#         raise HTTPException(status_code=503, detail="NLP service unavailable")
#     except Exception as e:
#         # Unexpected errors — log full details, return generic message
#         logger.exception("Unexpected extraction error for user %d: %s", user_id, e)
#         raise HTTPException(status_code=500, detail="Extraction failed. Please try again.")


# @router.get("/health")
# async def health(db: AsyncSession = Depends(get_db)):
#     """
#     Real health check endpoint.

#     FIXED in v2.0:
#       Previously called ollama_service.check_health() which always failed
#       because Ollama is not installed. Now checks the two things that
#       actually matter for extraction to work: DB connection and spaCy model.
#     """
#     status = {
#         "status": "ok",
#         "spacy_model": None,
#         "database": None,
#     }

#     # ── Check spaCy model ─────────────────────────────────────
#     if nlp is not None:
#         status["spacy_model"] = "loaded"
#     else:
#         status["spacy_model"] = "not_loaded"
#         status["status"] = "degraded"

#     # ── Check DB connection ───────────────────────────────────
#     try:
#         await db.execute(select(1))
#         status["database"] = "connected"
#     except Exception as e:
#         logger.error("Health check: DB connection failed: %s", e)
#         status["database"] = "error"
#         status["status"] = "degraded"

#     # Return 503 if anything is degraded so monitoring tools catch it
#     if status["status"] != "ok":
#         raise HTTPException(status_code=503, detail=status)

#     return status
"""
STKE Extract API — v2.0

Changes from v1:
  - Fetches current user's full_name/username from DB to pass into
    extraction service for ownership resolution
  - detect_context_from_text() called HERE once — not duplicated in service
  - /health endpoint fixed: checks DB + spaCy, removes dead Ollama check
  - Input validation enforced via ExtractionRequest schema
  - Specific exception handling instead of bare except
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.models import User
from app.models.schemas import ExtractionRequest, ExtractionResponse
from app.services.extraction_service import extraction_service
from app.nlp.rule_engine import detect_context_from_text, nlp

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/", response_model=ExtractionResponse)
async def extract_tasks(
    payload: ExtractionRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Extract tasks, decisions, and dependencies from text.

    Ownership resolution requires the current user's name so that
    pronouns (I/we/my) and chain inference work correctly.
    We fetch it once here — single source of truth for the pipeline.
    """
    # ── Resolve current user's display name ──────────────────────────────
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prefer full_name for NER matching (e.g. "Ayush Munot"),
    # fall back to username if full_name not set.
    current_user_name = user.full_name or user.username

    # ── Detect context ONCE here ──────────────────────────────────────────
    context = payload.source_context
    if not context or context in ("webpage", "auto"):
        context = detect_context_from_text(payload.text)

    # ── Run extraction pipeline ───────────────────────────────────────────
    try:
        return await extraction_service.extract_and_save(
            text=payload.text,
            user_id=user_id,
            current_user_name=current_user_name,
            source_url=payload.source_url,
            source_context=context,
            auto_create=payload.auto_create_tasks,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        logger.error("NLP pipeline error for user %d: %s", user_id, e)
        raise HTTPException(status_code=503, detail="NLP service unavailable")
    except Exception as e:
        logger.exception("Unexpected extraction error for user %d: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Extraction failed. Please try again.")


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """
    Real health check — verifies DB connection and spaCy model load.
    (Previous version called ollama_service which is not installed.)
    """
    status = {"status": "ok", "spacy_model": None, "database": None}

    if nlp is not None:
        status["spacy_model"] = "loaded"
    else:
        status["spacy_model"] = "not_loaded"
        status["status"] = "degraded"

    try:
        await db.execute(select(1))
        status["database"] = "connected"
    except Exception as e:
        logger.error("Health check DB error: %s", e)
        status["database"] = "error"
        status["status"] = "degraded"

    if status["status"] != "ok":
        raise HTTPException(status_code=503, detail=status)

    return status