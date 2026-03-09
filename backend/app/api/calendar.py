"""
STKE Google Calendar API Routes
"""

import json
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import get_current_user_id
from app.core.database import get_db
from app.models.models import Task
from app.services.calendar_service import (
    get_auth_url, exchange_code, get_upcoming_events, create_event, delete_event
)

router = APIRouter()

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "calendar_tokens.json")


def _load_tokens() -> dict:
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_tokens(tokens: dict):
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    except Exception as e:
        print(f"[STKE] Calendar token save failed: {e}")


def _get_token(user_id: int):
    tokens = _load_tokens()
    return tokens.get(str(user_id)) or tokens.get("pending")


def _set_token(user_id: int, data: dict):
    tokens = _load_tokens()
    tokens[str(user_id)] = data
    tokens.pop("pending", None)
    _save_tokens(tokens)


@router.get("/auth")
async def calendar_auth(user_id: int = Depends(get_current_user_id)):
    return {"auth_url": get_auth_url()}


@router.get("/callback")
async def calendar_callback(code: str):
    try:
        creds = exchange_code(code)
        tokens = _load_tokens()
        tokens["pending"] = creds
        _save_tokens(tokens)
        return HTMLResponse(content="""
        <html><body style="background:#09080f;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px">
          <div style="font-size:40px">📅</div>
          <div style="font-weight:700;font-size:18px">Calendar Connected!</div>
          <div style="font-size:13px;color:#94a3b8">This window will close automatically...</div>
          <script>setTimeout(function(){ window.close(); }, 1500);</script>
        </body></html>""")
    except Exception as e:
        return HTMLResponse(content=f"""
        <html><body style="background:#09080f;color:#f87171;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
          <div>Error: {str(e)}</div>
          <script>setTimeout(function(){{window.close();}}, 3000);</script>
        </body></html>""")


@router.get("/status")
async def calendar_status(user_id: int = Depends(get_current_user_id)):
    token = _get_token(user_id)
    if token:
        _set_token(user_id, token)
    return {"connected": token is not None}


@router.get("/events")
async def get_events(user_id: int = Depends(get_current_user_id)):
    creds = _get_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Calendar not connected")
    try:
        events = get_upcoming_events(creds, max_results=5)
        return {"events": events, "count": len(events)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/{task_id}")
async def sync_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Sync a single task to Google Calendar."""
    creds = _get_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Calendar not connected")

    result = await db.execute(select(Task).where(Task.id == task_id, Task.owner_id == user_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        event = create_event(creds, {
            "title": task.title,
            "deadline": task.deadline.isoformat() if task.deadline else None,
            "priority": task.priority,
            "status": task.status,
        })
        # Store event_id on task
        task.calendar_event_id = event.get("id")
        await db.commit()
        return {"event_id": event.get("id"), "event_link": event.get("htmlLink"), "status": "synced"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-all")
async def sync_all_tasks(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Sync all pending tasks with deadlines to Calendar."""
    creds = _get_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Calendar not connected")

    result = await db.execute(
        select(Task).where(
            Task.owner_id == user_id,
            Task.status != "completed",
        )
    )
    tasks = result.scalars().all()

    synced = 0
    failed = 0
    for task in tasks:
        try:
            event = create_event(creds, {
                "title": task.title,
                "deadline": task.deadline.isoformat() if task.deadline else None,
                "priority": task.priority,
                "status": task.status,
            })
            task.calendar_event_id = event.get("id")
            synced += 1
        except Exception:
            failed += 1

    await db.commit()
    return {"synced": synced, "failed": failed, "total": len(tasks)}


@router.delete("/unsync/{task_id}")
async def unsync_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    creds = _get_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Calendar not connected")

    result = await db.execute(select(Task).where(Task.id == task_id, Task.owner_id == user_id))
    task = result.scalar_one_or_none()
    if not task or not task.calendar_event_id:
        raise HTTPException(status_code=404, detail="Task or event not found")

    delete_event(creds, task.calendar_event_id)
    task.calendar_event_id = None
    await db.commit()
    return {"status": "unsynced"}


@router.delete("/disconnect")
async def disconnect_calendar(user_id: int = Depends(get_current_user_id)):
    tokens = _load_tokens()
    tokens.pop(str(user_id), None)
    tokens.pop("pending", None)
    _save_tokens(tokens)
    return {"status": "disconnected"}