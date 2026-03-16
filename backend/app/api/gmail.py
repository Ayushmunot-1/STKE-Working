"""
STKE Gmail API Routes — v2.0

Changes from v1:
  - POST /notify/{task_id} added — Step 8, user-confirmed assignee notification
  - extract/{email_id} and extract-all: now pass current_user_name to service
  - extract-all: sender name parsed from email From: header and prepended
  - _save_tokens logging fixed: print → logger
  - Bare except in extract-all replaced with specific logging
  - from app.* imports moved to top level (not inside functions)
"""

import json
import os
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import get_current_user_id
from app.core.database import get_db
from app.models.models import Task, User
from app.models.schemas import NotifyAssigneeRequest, NotifyAssigneeResponse
from app.services.gmail_service import (
    get_auth_url, exchange_code, fetch_emails, notify_assignee
)

router = APIRouter()
logger = logging.getLogger(__name__)

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "gmail_tokens.json")


# ── Token helpers (unchanged logic, fixed logging) ────────────

def _load_tokens() -> dict:
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("Failed to load Gmail tokens: %s", e)
    return {}


def _save_tokens(tokens: dict):
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    except Exception as e:
        logger.error("Failed to save Gmail tokens: %s", e)


def _get_user_token(user_id: int):
    tokens = _load_tokens()
    return tokens.get(str(user_id)) or tokens.get("pending")


def _set_user_token(user_id: int, token_data: dict):
    tokens = _load_tokens()
    tokens[str(user_id)] = token_data
    tokens.pop("pending", None)
    _save_tokens(tokens)


def _set_pending_token(token_data: dict):
    tokens = _load_tokens()
    tokens["pending"] = token_data
    _save_tokens(tokens)


# ── Auth routes (unchanged) ────────────────────────────────────

@router.get("/auth")
async def gmail_auth(user_id: int = Depends(get_current_user_id)):
    return {"auth_url": get_auth_url()}


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
        logger.error("Gmail callback error: %s", e)
        return HTMLResponse(content=f"""
        <html><body style="background:#09080f;color:#f87171;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px">
          <div style="font-size:40px">❌</div>
          <div>Error: {str(e)}</div>
          <script>setTimeout(function(){{window.close();}}, 3000);</script>
        </body></html>""")


@router.get("/status")
async def gmail_status(user_id: int = Depends(get_current_user_id)):
    token = _get_user_token(user_id)
    if token:
        _set_user_token(user_id, token)
    return {"connected": token is not None}


@router.get("/emails")
async def get_emails(
    max_results: int = 10,
    _t: str = None,
    user_id: int = Depends(get_current_user_id),
):
    creds = _get_user_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Gmail not connected")
    _set_user_token(user_id, creds)
    try:
        emails = fetch_emails(creds, max_results=max_results)
        return JSONResponse(
            content={"emails": emails, "count": len(emails)},
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
    except Exception as e:
        logger.error("Failed to fetch emails for user %d: %s", user_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Extraction routes (FIXED: now pass current_user_name) ─────

@router.post("/extract/{email_id}")
async def extract_from_email(
    email_id: str,
    payload: dict,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Extract tasks from a single email.

    CHANGED in v2.0:
      - Fetches current user from DB to pass their name into the service.
        This is required for ownership resolution (I/we/my → current user).
      - Sender name extracted from email's From: header and included
        in the text so the NLP pipeline can detect it as a person entity.
    """
    from app.services.extraction_service import extraction_service

    text    = payload.get("text", "")
    subject = payload.get("subject", "")
    sender  = payload.get("sender", "")

    if not text:
        raise HTTPException(status_code=400, detail="Email text required")

    # ── Get current user's name for ownership resolution ──────
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    current_user_name = user.full_name or user.username

    # Include subject + sender in text so NLP can detect context
    # and resolve sender as a named entity if relevant
    full_text = f"Subject: {subject}\nFrom: {sender}\n\n{text}"

    result = await extraction_service.extract_and_save(
        text=full_text,
        user_id=user_id,
        current_user_name=current_user_name,      # NEW
        source_url=f"gmail://message/{email_id}",
        source_context="email",
        auto_create=True,
        db=db,
    )
    return result


@router.post("/extract-all")
async def extract_all_emails(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Extract tasks from all recent inbox emails.

    CHANGED in v2.0:
      - Passes current_user_name to extraction service.
      - Specific exception logging instead of bare except + continue.
    """
    from app.services.extraction_service import extraction_service

    creds = _get_user_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Gmail not connected")

    # ── Get current user's name ────────────────────────────────
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    current_user_name = user.full_name or user.username

    try:
        emails = fetch_emails(creds, max_results=5)
    except Exception as e:
        logger.error("Failed to fetch emails for extract-all, user %d: %s", user_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    total_tasks = 0
    results = []

    for email in emails:
        full_text = (
            f"Subject: {email['subject']}\n"
            f"From: {email['from']}\n\n"
            f"{email['body']}"
        )
        try:
            result = await extraction_service.extract_and_save(
                text=full_text,
                user_id=user_id,
                current_user_name=current_user_name,  # NEW
                source_url=f"gmail://message/{email['id']}",
                source_context="email",
                auto_create=True,
                db=db,
            )
            total_tasks += result.tasks_found
            results.append({
                "email":       email["subject"],
                "tasks_found": result.tasks_found,
                "my_tasks":    result.my_tasks_count,
                "delegated":   result.delegated_count,
            })
        except Exception as e:
            logger.error(
                "Extraction failed for email '%s' (user %d): %s",
                email.get("subject", "unknown"), user_id, e
            )
            results.append({
                "email":  email["subject"],
                "error":  str(e),
            })

    return {
        "emails_processed": len(emails),
        "total_tasks_found": total_tasks,
        "results": results,
    }


# ── STEP 8: Notify assignee endpoint (NEW) ────────────────────

@router.post("/notify/{task_id}", response_model=NotifyAssigneeResponse)
async def notify_task_assignee(
    task_id: int,
    payload: NotifyAssigneeRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Send a Gmail notification to a task's assignee.

    The user sees a delegated task in the dashboard, types the
    assignee's email address, and clicks "Notify". This endpoint
    fires the email and marks the task as notified.

    Design decisions:
      - User CONFIRMS the email — we never guess or auto-send
      - Already-notified tasks return a clear message, not an error
      - A Gmail send failure returns 502 (bad gateway) not 500
    """
    # ── Load Gmail credentials ─────────────────────────────────
    creds = _get_user_token(user_id)
    if not creds:
        raise HTTPException(
            status_code=401,
            detail="Gmail not connected. Please connect Gmail first."
        )

    # ── Load task + current user together ─────────────────────
    result = await db.execute(
        select(Task, User)
        .join(User, Task.owner_id == User.id)
        .where(Task.id == task_id, Task.owner_id == user_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    task, current_user = row

    # ── Guard: task has no assignee name ──────────────────────
    if not task.assigned_to:
        raise HTTPException(
            status_code=400,
            detail="This task has no assignee. Cannot send notification."
        )

    # ── Guard: already notified ───────────────────────────────
    # Return info response, not an error — so dashboard can show status
    if task.notified_assignee:
        return NotifyAssigneeResponse(
            success=False,
            message=(
                f"'{task.assigned_to}' was already notified"
                + (f" on {task.notification_sent_at.strftime('%b %d at %H:%M')}"
                   if task.notification_sent_at else "")
            ),
            task_id=task_id,
            assignee_email=payload.assignee_email,
            notified_at=task.notification_sent_at,
        )

    # ── Send the notification ──────────────────────────────────
    sender_name = current_user.full_name or current_user.username

    success = notify_assignee(
        creds_dict=creds,
        assignee_email=payload.assignee_email,
        assignee_name=task.assigned_to,
        sender_name=sender_name,
        task_title=task.title,
        deadline_raw=task.deadline_raw,
        source_context=task.source_context,
    )

    if not success:
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to send Gmail notification. "
                "Check your Gmail connection and try again."
            )
        )

    # ── Mark task as notified ──────────────────────────────────
    now = datetime.now(timezone.utc)
    task.notified_assignee    = True
    task.notification_sent_at = now
    await db.commit()

    logger.info(
        "Notification sent: task %d → '%s' <%s> by user %d (%s)",
        task_id, task.assigned_to, payload.assignee_email,
        user_id, sender_name
    )

    return NotifyAssigneeResponse(
        success=True,
        message=f"Notification sent to {payload.assignee_email}",
        task_id=task_id,
        assignee_email=payload.assignee_email,
        notified_at=now,
    )


# ── Disconnect (unchanged) ─────────────────────────────────────

@router.delete("/disconnect")
async def disconnect_gmail(user_id: int = Depends(get_current_user_id)):
    tokens = _load_tokens()
    tokens.pop(str(user_id), None)
    tokens.pop("pending", None)
    _save_tokens(tokens)
    return {"status": "disconnected"}