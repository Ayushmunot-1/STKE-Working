"""
STKE Gmail API Routes - with persistent token storage
"""

import json
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.core.security import get_current_user_id
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.gmail_service import get_auth_url, exchange_code, fetch_emails

router = APIRouter()

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "gmail_tokens.json")


def _load_tokens() -> dict:
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_tokens(tokens: dict):
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    except Exception as e:
        print(f"[STKE] Failed to save tokens: {e}")


def _get_user_token(user_id: int):
    tokens = _load_tokens()
    return tokens.get(str(user_id)) or tokens.get("pending")


def _set_user_token(user_id: int, token_data: dict):
    tokens = _load_tokens()
    tokens[str(user_id)] = token_data
    # Clear pending once assigned to a user
    tokens.pop("pending", None)
    _save_tokens(tokens)


def _set_pending_token(token_data: dict):
    tokens = _load_tokens()
    tokens["pending"] = token_data
    _save_tokens(tokens)


@router.get("/auth")
async def gmail_auth(user_id: int = Depends(get_current_user_id)):
    url = get_auth_url()
    return {"auth_url": url}


@router.get("/callback")
async def gmail_callback(code: str, state: str = None):
    try:
        creds = exchange_code(code)
        _set_pending_token(creds)
        return HTMLResponse(content="""
        <html><body style="background:#09080f;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px">
          <div style="font-size:40px">✅</div>
          <div style="font-weight:700;font-size:18px">Gmail Connected!</div>
          <div style="font-size:13px;color:#94a3b8">This window will close automatically...</div>
          <script>setTimeout(function(){ window.close(); }, 1500);</script>
        </body></html>""")
    except Exception as e:
        return HTMLResponse(content=f"""
        <html><body style="background:#09080f;color:#f87171;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px">
          <div style="font-size:40px">❌</div>
          <div>Error: {str(e)}</div>
          <script>setTimeout(function(){{window.close();}}, 3000);</script>
        </body></html>""")


@router.get("/status")
async def gmail_status(user_id: int = Depends(get_current_user_id)):
    token = _get_user_token(user_id)
    # Assign pending token to this user if exists
    if token:
        _set_user_token(user_id, token)
    return {"connected": token is not None}


@router.get("/emails")
async def get_emails(max_results: int = 10, _t: str = None, user_id: int = Depends(get_current_user_id)):
    creds = _get_user_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Gmail not connected")
    _set_user_token(user_id, creds)
    try:
        emails = fetch_emails(creds, max_results=max_results)
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content={"emails": emails, "count": len(emails)},
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract/{email_id}")
async def extract_from_email(
    email_id: str,
    payload: dict,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    from app.services.extraction_service import extraction_service
    text = payload.get("text", "")
    subject = payload.get("subject", "")
    sender = payload.get("sender", "")
    if not text:
        raise HTTPException(status_code=400, detail="Email text required")
    full_text = f"Subject: {subject}\nFrom: {sender}\n\n{text}"
    result = await extraction_service.extract_and_save(
        text=full_text, user_id=user_id,
        source_url=f"gmail://message/{email_id}",
        source_context="email", auto_create=True, db=db,
    )
    return result


@router.post("/extract-all")
async def extract_all_emails(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    from app.services.extraction_service import extraction_service
    creds = _get_user_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Gmail not connected")
    try:
        emails = fetch_emails(creds, max_results=5)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    total_tasks = 0
    results = []
    for email in emails:
        text = f"Subject: {email['subject']}\nFrom: {email['from']}\n\n{email['body']}"
        try:
            result = await extraction_service.extract_and_save(
                text=text, user_id=user_id,
                source_url=f"gmail://message/{email['id']}",
                source_context="email", auto_create=True, db=db,
            )
            total_tasks += result.tasks_found
            results.append({"email": email["subject"], "tasks_found": result.tasks_found})
        except Exception:
            continue

    return {"emails_processed": len(emails), "total_tasks_found": total_tasks, "results": results}


@router.delete("/disconnect")
async def disconnect_gmail(user_id: int = Depends(get_current_user_id)):
    tokens = _load_tokens()
    tokens.pop(str(user_id), None)
    tokens.pop("pending", None)
    _save_tokens(tokens)
    return {"status": "disconnected"}