# """
# STKE Google Calendar API Routes — v2.0

# Changes from v1:
#   - sync_all_tasks: NOW filters by owner_type — only syncs tasks that belong
#     to the current user (explicit/self/inferred/fallback owner_type).
#     Shared and role-based tasks are excluded from calendar sync.
#   - sync_task (single): added owner_type check — warns if task isn't owned
#     by current user but still allows manual override.
#   - calendar_synced flag now properly set to True after successful sync.
#   - Bare except replaced with specific exception logging.
#   - task.calendar_synced set correctly on unsync.
# """

# import json
# import os
# import logging
# from fastapi import APIRouter, Depends, HTTPException
# from fastapi.responses import HTMLResponse
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select, and_

# from app.core.security import get_current_user_id
# from app.core.database import get_db
# from app.models.models import Task, TaskOwnerType
# from app.services.calendar_service import (
#     get_auth_url, exchange_code, get_upcoming_events, create_event, delete_event
# )

# router = APIRouter()
# logger = logging.getLogger(__name__)

# TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "calendar_tokens.json")

# # Owner types that are eligible for calendar sync
# # shared → no individual owner, skip
# # role   → needs manual assignment first, skip
# CALENDAR_ELIGIBLE_TYPES = {
#     TaskOwnerType.EXPLICIT.value,
#     TaskOwnerType.SELF.value,
#     TaskOwnerType.INFERRED.value,
#     TaskOwnerType.FALLBACK.value,
#     None,  # tasks extracted before v2.0 have no owner_type — include them
# }


# # ── Token helpers (unchanged) ──────────────────────────────────

# def _load_tokens() -> dict:
#     try:
#         if os.path.exists(TOKEN_FILE):
#             with open(TOKEN_FILE) as f:
#                 return json.load(f)
#     except Exception as e:
#         logger.warning("Failed to load calendar tokens: %s", e)
#     return {}


# def _save_tokens(tokens: dict):
#     try:
#         with open(TOKEN_FILE, "w") as f:
#             json.dump(tokens, f, indent=2)
#     except Exception as e:
#         logger.error("Calendar token save failed: %s", e)


# def _get_token(user_id: int):
#     tokens = _load_tokens()
#     return tokens.get(str(user_id)) or tokens.get("pending")


# def _set_token(user_id: int, data: dict):
#     tokens = _load_tokens()
#     tokens[str(user_id)] = data
#     tokens.pop("pending", None)
#     _save_tokens(tokens)


# # ── Auth routes (unchanged) ────────────────────────────────────

# @router.get("/auth")
# async def calendar_auth(user_id: int = Depends(get_current_user_id)):
#     return {"auth_url": get_auth_url()}


# @router.get("/callback")
# async def calendar_callback(code: str):
#     try:
#         creds = exchange_code(code)
#         tokens = _load_tokens()
#         tokens["pending"] = creds
#         _save_tokens(tokens)
#         return HTMLResponse(content="""
#         <html><body style="background:#09080f;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px">
#           <div style="font-size:40px">📅</div>
#           <div style="font-weight:700;font-size:18px">Calendar Connected!</div>
#           <div style="font-size:13px;color:#94a3b8">This window will close automatically...</div>
#           <script>setTimeout(function(){ window.close(); }, 1500);</script>
#         </body></html>""")
#     except Exception as e:
#         logger.error("Calendar callback error: %s", e)
#         return HTMLResponse(content=f"""
#         <html><body style="background:#09080f;color:#f87171;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
#           <div>Error: {str(e)}</div>
#           <script>setTimeout(function(){{window.close();}}, 3000);</script>
#         </body></html>""")


# @router.get("/status")
# async def calendar_status(user_id: int = Depends(get_current_user_id)):
#     token = _get_token(user_id)
#     if token:
#         _set_token(user_id, token)
#     return {"connected": token is not None}


# @router.get("/events")
# async def get_events(user_id: int = Depends(get_current_user_id)):
#     creds = _get_token(user_id)
#     if not creds:
#         raise HTTPException(status_code=401, detail="Calendar not connected")
#     try:
#         events = get_upcoming_events(creds, max_results=5)
#         return {"events": events, "count": len(events)}
#     except Exception as e:
#         logger.error("Failed to fetch calendar events for user %d: %s", user_id, e)
#         raise HTTPException(status_code=500, detail=str(e))


# # ── Sync routes (UPGRADED) ─────────────────────────────────────

# @router.post("/sync/{task_id}")
# async def sync_task(
#     task_id: int,
#     user_id: int = Depends(get_current_user_id),
#     db: AsyncSession = Depends(get_db),
# ):
#     """
#     Sync a single task to Google Calendar.

#     CHANGED in v2.0:
#       - Warns (but doesn't block) if task owner_type is shared/role.
#         User can still manually sync any task — but they're informed.
#       - Sets calendar_synced = True after successful sync.
#     """
#     creds = _get_token(user_id)
#     if not creds:
#         raise HTTPException(status_code=401, detail="Calendar not connected")

#     result = await db.execute(
#         select(Task).where(Task.id == task_id, Task.owner_id == user_id)
#     )
#     task = result.scalar_one_or_none()
#     if not task:
#         raise HTTPException(status_code=404, detail="Task not found")

#     # Warn if syncing a task not owned by this user
#     # (still allowed — manual sync is always permitted)
#     ownership_warning = None
#     if task.owner_type in (TaskOwnerType.SHARED.value, TaskOwnerType.ROLE.value):
#         ownership_warning = (
#             f"This task has owner_type='{task.owner_type}' — "
#             "it may not belong to you personally. Syncing anyway."
#         )
#         logger.warning(
#             "User %d manually syncing task %d with owner_type=%s",
#             user_id, task_id, task.owner_type
#         )

#     try:
#         event = create_event(creds, {
#             "title": task.title,
#             "deadline": task.deadline.isoformat() if task.deadline else None,
#             "priority": task.priority.value if task.priority else "medium",
#             "status": task.status.value if task.status else "pending",
#         })
#         task.calendar_event_id = event.get("id")
#         task.calendar_synced = True      # FIXED: was never set in v1
#         await db.commit()

#         return {
#             "event_id": event.get("id"),
#             "event_link": event.get("htmlLink"),
#             "status": "synced",
#             "warning": ownership_warning,
#         }
#     except Exception as e:
#         logger.error("Calendar sync failed for task %d: %s", task_id, e)
#         raise HTTPException(status_code=500, detail=f"Calendar sync failed: {str(e)}")


# @router.post("/sync-all")
# async def sync_all_tasks(
#     user_id: int = Depends(get_current_user_id),
#     db: AsyncSession = Depends(get_db),
# ):
#     """
#     Sync all eligible tasks to Google Calendar.

#     CHANGED in v2.0 — KEY CHANGE:
#       Previously synced ALL tasks for this user indiscriminately.
#       Now filters to only sync tasks the current user actually owns:
#         ✅ owner_type = explicit (and owner = current user)
#         ✅ owner_type = self
#         ✅ owner_type = inferred
#         ✅ owner_type = fallback
#         ✅ owner_type = None (legacy tasks from before v2.0)
#         ❌ owner_type = shared  → skip, no individual owner
#         ❌ owner_type = role    → skip, needs manual assignment first

#       Also skips tasks already synced (calendar_synced = True).
#     """
#     creds = _get_token(user_id)
#     if not creds:
#         raise HTTPException(status_code=401, detail="Calendar not connected")

#     # Fetch only eligible, not-yet-synced, non-completed tasks
#     result = await db.execute(
#         select(Task).where(
#             and_(
#                 Task.owner_id == user_id,
#                 Task.status != "completed",
#                 Task.calendar_synced == False,          # skip already synced
#                 Task.owner_type.notin_([               # skip shared and role tasks
#                     TaskOwnerType.SHARED.value,
#                     TaskOwnerType.ROLE.value,
#                 ]),
#             )
#         )
#     )
#     tasks = result.scalars().all()

#     synced  = 0
#     failed  = 0
#     skipped = 0

#     for task in tasks:
#         try:
#             event = create_event(creds, {
#                 "title": task.title,
#                 "deadline": task.deadline.isoformat() if task.deadline else None,
#                 "priority": task.priority.value if task.priority else "medium",
#                 "status": task.status.value if task.status else "pending",
#             })
#             task.calendar_event_id = event.get("id")
#             task.calendar_synced = True
#             synced += 1
#         except Exception as e:
#             logger.error("Failed to sync task %d to calendar: %s", task.id, e)
#             failed += 1

#     await db.commit()

#     logger.info(
#         "Calendar sync-all for user %d: synced=%d, failed=%d, skipped=%d",
#         user_id, synced, failed, skipped
#     )
#     return {
#         "synced": synced,
#         "failed": failed,
#         "skipped": skipped,
#         "total_eligible": len(tasks),
#     }


# @router.delete("/unsync/{task_id}")
# async def unsync_task(
#     task_id: int,
#     user_id: int = Depends(get_current_user_id),
#     db: AsyncSession = Depends(get_db),
# ):
#     """Remove a task's calendar event and clear the sync flag."""
#     creds = _get_token(user_id)
#     if not creds:
#         raise HTTPException(status_code=401, detail="Calendar not connected")

#     result = await db.execute(
#         select(Task).where(Task.id == task_id, Task.owner_id == user_id)
#     )
#     task = result.scalar_one_or_none()
#     if not task or not task.calendar_event_id:
#         raise HTTPException(status_code=404, detail="Task or calendar event not found")

#     try:
#         delete_event(creds, task.calendar_event_id)
#     except Exception as e:
#         logger.error("Failed to delete calendar event for task %d: %s", task_id, e)
#         raise HTTPException(status_code=500, detail=f"Failed to delete calendar event: {str(e)}")

#     task.calendar_event_id = None
#     task.calendar_synced = False     # FIXED: properly reset the flag
#     await db.commit()
#     return {"status": "unsynced"}


# @router.delete("/disconnect")
# async def disconnect_calendar(user_id: int = Depends(get_current_user_id)):
#     tokens = _load_tokens()
#     tokens.pop(str(user_id), None)
#     tokens.pop("pending", None)
#     _save_tokens(tokens)
#     return {"status": "disconnected"}
"""
STKE Google Calendar API Routes — v2.0

Changes from v1:
  - sync_all_tasks: NOW filters by owner_type — only syncs tasks that belong
    to the current user (explicit/self/inferred/fallback owner_type).
    Shared and role-based tasks are excluded from calendar sync.
  - sync_task (single): added owner_type check — warns if task isn't owned
    by current user but still allows manual override.
  - calendar_synced flag now properly set to True after successful sync.
  - Bare except replaced with specific exception logging.
  - task.calendar_synced set correctly on unsync.
"""

import json
import os
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.core.security import get_current_user_id
from app.core.database import get_db
from app.models.models import Task, TaskOwnerType
from app.services.calendar_service import (
    get_auth_url, exchange_code, get_upcoming_events, create_event, delete_event
)

router = APIRouter()
logger = logging.getLogger(__name__)

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "calendar_tokens.json")

# Owner types that are eligible for calendar sync
# shared → no individual owner, skip
# role   → needs manual assignment first, skip
CALENDAR_ELIGIBLE_TYPES = {
    TaskOwnerType.EXPLICIT.value,
    TaskOwnerType.SELF.value,
    TaskOwnerType.INFERRED.value,
    TaskOwnerType.FALLBACK.value,
    None,  # tasks extracted before v2.0 have no owner_type — include them
}


# ── Token helpers (unchanged) ──────────────────────────────────

def _load_tokens() -> dict:
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.warning("Failed to load calendar tokens: %s", e)
    return {}


def _save_tokens(tokens: dict):
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    except Exception as e:
        logger.error("Calendar token save failed: %s", e)


def _get_token(user_id: int):
    tokens = _load_tokens()
    return tokens.get(str(user_id)) or tokens.get("pending")


def _set_token(user_id: int, data: dict):
    tokens = _load_tokens()
    tokens[str(user_id)] = data
    tokens.pop("pending", None)
    _save_tokens(tokens)


# ── Auth routes (unchanged) ────────────────────────────────────

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
        logger.error("Calendar callback error: %s", e)
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
        logger.error("Failed to fetch calendar events for user %d: %s", user_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Sync routes (UPGRADED) ─────────────────────────────────────

@router.post("/sync/{task_id}")
async def sync_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync a single task to Google Calendar.

    CHANGED in v2.0:
      - Warns (but doesn't block) if task owner_type is shared/role.
        User can still manually sync any task — but they're informed.
      - Sets calendar_synced = True after successful sync.
    """
    creds = _get_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Calendar not connected")

    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.owner_id == user_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Warn if syncing a task not owned by this user
    # (still allowed — manual sync is always permitted)
    ownership_warning = None
    if task.owner_type in (TaskOwnerType.SHARED.value, TaskOwnerType.ROLE.value):
        ownership_warning = (
            f"This task has owner_type='{task.owner_type}' — "
            "it may not belong to you personally. Syncing anyway."
        )
        logger.warning(
            "User %d manually syncing task %d with owner_type=%s",
            user_id, task_id, task.owner_type
        )

    try:
        event = create_event(creds, {
            "title": task.title,
            "deadline": task.deadline.isoformat() if task.deadline else None,
            "priority": task.priority.value if task.priority else "medium",
            "status": task.status.value if task.status else "pending",
        })
        task.calendar_event_id = event.get("id")
        task.calendar_synced = True      # FIXED: was never set in v1
        await db.commit()

        return {
            "event_id": event.get("id"),
            "event_link": event.get("htmlLink"),
            "status": "synced",
            "warning": ownership_warning,
        }
    except Exception as e:
        logger.error("Calendar sync failed for task %d: %s", task_id, e)
        raise HTTPException(status_code=500, detail=f"Calendar sync failed: {str(e)}")


@router.post("/sync-all")
async def sync_all_tasks(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync all eligible tasks to Google Calendar.

    CHANGED in v2.0 — KEY CHANGE:
      Previously synced ALL tasks for this user indiscriminately.
      Now filters to only sync tasks the current user actually owns:
        ✅ owner_type = explicit (and owner = current user)
        ✅ owner_type = self
        ✅ owner_type = inferred
        ✅ owner_type = fallback
        ✅ owner_type = None (legacy tasks from before v2.0)
        ❌ owner_type = shared  → skip, no individual owner
        ❌ owner_type = role    → skip, needs manual assignment first

      Also skips tasks already synced (calendar_synced = True).
    """
    creds = _get_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Calendar not connected")

    # Fetch only eligible, not-yet-synced, non-completed tasks
    # NOTE: notin_() in SQLAlchemy/SQL silently excludes NULL values.
    # Tasks extracted before the ownership model (owner_type IS NULL) would be
    # invisible to sync. We must explicitly include NULLs with OR IS NULL.
    result = await db.execute(
        select(Task).where(
            and_(
                Task.owner_id == user_id,
                Task.status != "completed",
                Task.calendar_synced == False,
                or_(
                    Task.owner_type == None,            # legacy tasks (pre-ownership model)
                    Task.owner_type.notin_([            # skip shared and role tasks
                        TaskOwnerType.SHARED.value,
                        TaskOwnerType.ROLE.value,
                    ]),
                ),
            )
        )
    )
    tasks = result.scalars().all()

    synced  = 0
    failed  = 0
    skipped = 0

    for task in tasks:
        try:
            event = create_event(creds, {
                "title": task.title,
                "deadline": task.deadline.isoformat() if task.deadline else None,
                "priority": task.priority.value if task.priority else "medium",
                "status": task.status.value if task.status else "pending",
            })
            task.calendar_event_id = event.get("id")
            task.calendar_synced = True
            synced += 1
        except Exception as e:
            logger.error("Failed to sync task %d to calendar: %s", task.id, e)
            failed += 1

    await db.commit()

    logger.info(
        "Calendar sync-all for user %d: synced=%d, failed=%d, skipped=%d",
        user_id, synced, failed, skipped
    )
    return {
        "synced": synced,
        "failed": failed,
        "skipped": skipped,
        "total_eligible": len(tasks),
    }


@router.delete("/unsync/{task_id}")
async def unsync_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Remove a task's calendar event and clear the sync flag."""
    creds = _get_token(user_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Calendar not connected")

    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.owner_id == user_id)
    )
    task = result.scalar_one_or_none()
    if not task or not task.calendar_event_id:
        raise HTTPException(status_code=404, detail="Task or calendar event not found")

    try:
        delete_event(creds, task.calendar_event_id)
    except Exception as e:
        logger.error("Failed to delete calendar event for task %d: %s", task_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to delete calendar event: {str(e)}")

    task.calendar_event_id = None
    task.calendar_synced = False     # FIXED: properly reset the flag
    await db.commit()
    return {"status": "unsynced"}


@router.delete("/disconnect")
async def disconnect_calendar(user_id: int = Depends(get_current_user_id)):
    tokens = _load_tokens()
    tokens.pop(str(user_id), None)
    tokens.pop("pending", None)
    _save_tokens(tokens)
    return {"status": "disconnected"}