# """
# STKE Extraction Service — v2.0

# Changes from v1:
#   - current_user name passed into rule_extract() for ownership resolution
#   - Ownership-aware task routing: my tasks / delegated / shared / role-based
#   - Calendar sync: ONLY tasks where owner == current_user are synced
#   - Gmail notification: drafted for tasks assigned to other named people
#   - Dedup thresholds now read from settings (not hardcoded)
#   - was_truncated flag added to ExtractionHistory
#   - detect_context_from_text() duplicate call removed (called once in extract.py)
#   - _create_reminders() made async-safe
#   - confidence_score now comes from rule_engine (real score, not hardcoded 0.85)
# """

# import logging
# import time
# from datetime import datetime, timezone, timedelta
# from typing import List, Optional

# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select

# from app.core.config import settings
# from app.models.models import Task, Reminder, ExtractionHistory, TaskPriority, TaskOwnerType
# from app.models.schemas import ExtractedTaskPreview, ExtractionResponse, DecisionItem, DependencyItem
# from app.nlp.rule_engine import rule_extract, detect_context_from_text, normalize_task_title

# logger = logging.getLogger(__name__)

# # Priority string → enum map
# PRIORITY_MAP = {
#     "low":      TaskPriority.LOW,
#     "medium":   TaskPriority.MEDIUM,
#     "high":     TaskPriority.HIGH,
#     "critical": TaskPriority.CRITICAL,
# }

# # Owner type string → enum map
# OWNER_TYPE_MAP = {
#     "explicit": TaskOwnerType.EXPLICIT,
#     "self":     TaskOwnerType.SELF,
#     "role":     TaskOwnerType.ROLE,
#     "shared":   TaskOwnerType.SHARED,
#     "inferred": TaskOwnerType.INFERRED,
#     "fallback": TaskOwnerType.FALLBACK,
# }

# # These owner_types go to the current user's calendar
# CALENDAR_SYNC_TYPES = {"explicit", "self", "inferred", "fallback"}

# # These owner_types trigger a Gmail notification to the assignee
# NOTIFY_TYPES = {"explicit"}


# class ExtractionService:

#     # ── Helpers ───────────────────────────────────────────────

#     def _token_overlap(self, a: str, b: str) -> float:
#         """Jaccard similarity between two normalised title strings."""
#         ta = set(a.lower().split())
#         tb = set(b.lower().split())
#         if not ta or not tb:
#             return 0.0
#         return len(ta & tb) / len(ta | tb)

#     def _create_reminders(self, db: AsyncSession, task: Task) -> None:
#         """Add email + popup reminders for a task with a deadline."""
#         if not task.deadline:
#             return
#         now = datetime.now(timezone.utc)
#         one_day = task.deadline - timedelta(days=1)
#         if one_day > now:
#             db.add(Reminder(task_id=task.id, remind_at=one_day, method="email"))
#         one_hour = task.deadline - timedelta(hours=1)
#         if one_hour > now:
#             db.add(Reminder(task_id=task.id, remind_at=one_hour, method="popup"))

#     def _should_sync_to_calendar(
#         self,
#         owner: Optional[str],
#         owner_type: Optional[str],
#         current_user_name: str,
#     ) -> bool:
#         """
#         Decide if a task should be synced to the current user's Google Calendar.

#         Rules:
#           - owner_type must be in CALENDAR_SYNC_TYPES (explicit/self/inferred/fallback)
#           - owner must match current_user_name (case-insensitive)
#           - shared and role tasks NEVER go to calendar — they have no clear individual owner

#         Returns True only when BOTH conditions are met.
#         """
#         if owner_type not in CALENDAR_SYNC_TYPES:
#             return False
#         if not owner:
#             return False
#         return owner.lower() == current_user_name.lower()

#     def _should_notify_assignee(
#         self,
#         owner: Optional[str],
#         owner_type: Optional[str],
#         current_user_name: str,
#     ) -> bool:
#         """
#         Decide if a Gmail notification should be sent to the task's assignee.

#         Only notify when:
#           - owner_type is 'explicit' (clear person name found in text)
#           - owner is NOT the current user (no point notifying yourself)
#           - owner is not None
#         """
#         if owner_type not in NOTIFY_TYPES:
#             return False
#         if not owner:
#             return False
#         return owner.lower() != current_user_name.lower()

#     # ── Main extraction pipeline ──────────────────────────────

#     async def extract_and_save(
#         self,
#         text: str,
#         user_id: int,
#         current_user_name: str,       # NEW: needed for ownership resolution
#         source_url: Optional[str],
#         source_context: Optional[str],
#         auto_create: bool,
#         db: AsyncSession,
#     ) -> ExtractionResponse:
#         """
#         Full extraction pipeline:
#           1. Run rule engine with ownership resolution
#           2. Deduplicate against existing DB tasks
#           3. Route tasks by owner type
#           4. Save owned tasks to DB
#           5. Log extraction history
#           6. Return structured response with routing metadata
#         """
#         start_ms = int(time.time() * 1000)

#         # NOTE: detect_context_from_text() is called ONCE in extract.py
#         # and passed in as source_context. No duplicate call here.
#         # If somehow it's still "auto" here, detect it as a safety net.
#         if not source_context or source_context in ("webpage", "auto"):
#             source_context = detect_context_from_text(text)

#         # ── Step 1: Run rule engine ───────────────────────────
#         # Pass current_user_name so infer_task_ownership() can resolve
#         # pronouns (I/we/my → current user) and chain inference correctly.
#         rule_results = rule_extract(text, current_user=current_user_name)
#         raw_tasks    = rule_results["tasks"]
#         raw_decisions    = rule_results.get("decisions", [])
#         raw_dependencies = rule_results.get("dependencies", [])

#         logger.info(
#             "Rule engine extracted: %d tasks, %d decisions, %d dependencies",
#             len(raw_tasks), len(raw_decisions), len(raw_dependencies)
#         )

#         # ── Early exit: no tasks found ────────────────────────
#         if not raw_tasks:
#             elapsed = int(time.time() * 1000) - start_ms
#             was_truncated = len(text) > 5000
#             db.add(ExtractionHistory(
#                 user_id=user_id,
#                 source_url=source_url,
#                 source_context=source_context,
#                 raw_input=text[:5000],
#                 was_truncated=was_truncated,
#                 tasks_extracted=0,
#                 processing_time_ms=elapsed,
#             ))
#             await db.commit()
#             return ExtractionResponse(
#                 tasks_found=0,
#                 duplicates_filtered=0,
#                 processing_time_ms=elapsed,
#                 tasks=[],
#                 saved_task_ids=[],
#                 decisions=[DecisionItem(decision_text=d["decision_text"]) for d in raw_decisions],
#                 dependencies=[DependencyItem(**d) for d in raw_dependencies],
#             )

#         # ── Step 2: Load existing tasks for deduplication ─────
#         existing_result = await db.execute(
#             select(Task.id, Task.title).where(Task.owner_id == user_id)
#         )
#         existing_tasks = [
#             {"id": r.id, "title": r.title}
#             for r in existing_result.fetchall()
#         ]

#         # ── Step 3: Dedup + build previews ────────────────────
#         seen_this_batch: List[str] = []
#         previews: List[ExtractedTaskPreview] = []
#         duplicates_filtered = 0

#         for task in raw_tasks:
#             title        = task.get("title", "Untitled task")
#             priority_str = task.get("priority", "medium").lower()
#             normalized   = normalize_task_title(title)
#             owner        = task.get("owner")
#             owner_type   = task.get("owner_type")      # set by infer_task_ownership()
#             owner_inferred = task.get("owner_inferred", False)
#             intervention_by = task.get("intervention_by")

#             if not normalized or len(normalized) < 2:
#                 continue

#             is_dup = False
#             dup_id = None

#             # Check against saved DB tasks
#             # Threshold from settings — not hardcoded
#             for ex in existing_tasks:
#                 ex_norm = normalize_task_title(ex["title"])
#                 if self._token_overlap(normalized, ex_norm) > settings.SIMILARITY_THRESHOLD:
#                     is_dup = True
#                     dup_id = ex["id"]
#                     duplicates_filtered += 1
#                     break

#             # Check within this extraction batch
#             if not is_dup:
#                 for seen in seen_this_batch:
#                     if self._token_overlap(normalized, seen) > settings.BATCH_SIMILARITY_THRESHOLD:
#                         is_dup = True
#                         duplicates_filtered += 1
#                         break

#             if not is_dup:
#                 seen_this_batch.append(normalized)

#             # Resolve deadline + timezone
#             deadline: Optional[datetime] = None
#             raw_dl = task.get("deadline")
#             if isinstance(raw_dl, datetime):
#                 deadline = raw_dl
#                 if deadline.tzinfo is None:
#                     deadline = deadline.replace(tzinfo=timezone.utc)

#             # ── Routing decision for this task ────────────────
#             sync_to_calendar  = self._should_sync_to_calendar(owner, owner_type, current_user_name)
#             notify_assignee   = self._should_notify_assignee(owner, owner_type, current_user_name)

#             previews.append(ExtractedTaskPreview(
#                 title=title,
#                 description=task.get("description"),
#                 raw_text=task.get("description", ""),
#                 assigned_to=owner,
#                 deadline=deadline,
#                 deadline_raw=task.get("deadline_raw"),
#                 priority=PRIORITY_MAP.get(priority_str, TaskPriority.MEDIUM),
#                 confidence_score=float(task.get("confidence", 0.55)),
#                 is_duplicate=is_dup,
#                 duplicate_of_id=dup_id,
#                 # New ownership fields — passed through to response
#                 owner_type=owner_type,
#                 owner_inferred=owner_inferred,
#                 intervention_by=intervention_by,
#                 sync_to_calendar=sync_to_calendar,
#                 notify_assignee=notify_assignee,
#             ))

#         # ── Step 4: Save to DB ────────────────────────────────
#         saved_ids: List[int] = []
#         tasks_to_notify: List[Task] = []   # collect for Gmail notifications

#         if auto_create:
#             for preview in previews:
#                 if preview.is_duplicate:
#                     continue

#                 # Only save tasks that belong to this user OR have no clear owner
#                 # Shared/role tasks are saved too — for dashboard visibility —
#                 # but they will NOT be synced to calendar.
#                 db_task = Task(
#                     title=preview.title,
#                     description=preview.description,
#                     raw_text=preview.raw_text,
#                     source_url=source_url,
#                     source_context=source_context,
#                     assigned_to=preview.assigned_to,
#                     deadline=preview.deadline,
#                     deadline_raw=preview.deadline_raw,
#                     priority=preview.priority,
#                     confidence_score=preview.confidence_score,
#                     owner_id=user_id,
#                     # New ownership fields
#                     owner_type=OWNER_TYPE_MAP.get(preview.owner_type) if preview.owner_type else None,
#                     owner_inferred=preview.owner_inferred or False,
#                     intervention_by=preview.intervention_by,
#                     # Calendar sync: ONLY if this task belongs to current user
#                     calendar_synced=False,  # sync happens separately via /calendar/sync
#                     # Notification: will be sent after save
#                     notified_assignee=False,
#                 )
#                 db.add(db_task)
#                 await db.flush()   # get the db_task.id
#                 saved_ids.append(db_task.id)

#                 # Add reminders for tasks with deadlines
#                 if preview.deadline:
#                     self._create_reminders(db, db_task)

#                 # Track which tasks need Gmail notifications
#                 if preview.notify_assignee:
#                     tasks_to_notify.append(db_task)

#         # ── Step 5: Log extraction history ────────────────────
#         elapsed = int(time.time() * 1000) - start_ms
#         was_truncated = len(text) > 5000
#         db.add(ExtractionHistory(
#             user_id=user_id,
#             source_url=source_url,
#             source_context=source_context,
#             raw_input=text[:5000],
#             was_truncated=was_truncated,
#             tasks_extracted=len(saved_ids),
#             processing_time_ms=elapsed,
#         ))
#         await db.commit()

#         # ── Step 6: Queue Gmail notifications ─────────────────
#         # We log which tasks need notifications here.
#         # Actual sending is done by gmail_service (Step 8).
#         # Kept separate so a Gmail API failure doesn't break extraction.
#         if tasks_to_notify:
#             logger.info(
#                 "%d task(s) flagged for Gmail notification to assignees: %s",
#                 len(tasks_to_notify),
#                 [t.assigned_to for t in tasks_to_notify]
#             )
#             # TODO Step 8: call gmail_service.notify_assignee(task, sender=current_user_name)

#         # ── Step 7: Build routing summary for response ────────
#         # Categorise previews by owner_type for the dashboard
#         my_tasks_count     = sum(1 for p in previews if not p.is_duplicate and p.sync_to_calendar)
#         delegated_count    = sum(1 for p in previews if not p.is_duplicate and p.notify_assignee)
#         shared_count       = sum(1 for p in previews if not p.is_duplicate and p.owner_type == "shared")
#         needs_assign_count = sum(1 for p in previews if not p.is_duplicate and p.owner_type == "role")

#         logger.info(
#             "Routing summary — mine: %d | delegated: %d | shared: %d | needs assignment: %d",
#             my_tasks_count, delegated_count, shared_count, needs_assign_count
#         )

#         return ExtractionResponse(
#             tasks_found=len(previews),
#             duplicates_filtered=duplicates_filtered,
#             processing_time_ms=elapsed,
#             tasks=previews,
#             saved_task_ids=saved_ids,
#             decisions=[DecisionItem(decision_text=d["decision_text"]) for d in raw_decisions],
#             dependencies=[DependencyItem(**d) for d in raw_dependencies],
#         )


# extraction_service = ExtractionService()

"""
STKE Extraction Service — v3.0

Changes from v2.1:
  - current_user_name now passed into rule_extract() for ownership resolution.
    (v2.1 had the param but called rule_extract(text) without it — root cause
    of all tasks landing in My Tasks regardless of who they were assigned to.)
  - Full ownership routing: TaskOwnerType enum, OWNER_TYPE_MAP,
    _should_sync_to_calendar(), _should_notify_assignee().
  - owner_type, owner_inferred, intervention_by saved to Task model.
  - Calendar sync: only tasks owned by current user are synced.
  - Gmail notify: tasks with explicit assignee != current user are flagged.
  - Routing summary logged on every extraction.
  - 3-signal duplicate check from v2.1 retained.
  - existing_tasks pre-normalised at load time (not per-comparison).
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.models import Task, Reminder, ExtractionHistory, TaskPriority, TaskOwnerType
from app.models.schemas import ExtractedTaskPreview, ExtractionResponse, DecisionItem, DependencyItem
from app.nlp.rule_engine import rule_extract, detect_context_from_text, normalize_task_title
from app.models.models import User
from app.api import gmail as gmail_router
import app.services.gmail_service as gmail_service

logger = logging.getLogger(__name__)

# ── Priority string → enum ────────────────────────────────────────────────────
PRIORITY_MAP = {
    "low":      TaskPriority.LOW,
    "medium":   TaskPriority.MEDIUM,
    "high":     TaskPriority.HIGH,
    "critical": TaskPriority.CRITICAL,
}

# ── Owner type string → enum ──────────────────────────────────────────────────
OWNER_TYPE_MAP = {
    "explicit": TaskOwnerType.EXPLICIT,
    "self":     TaskOwnerType.SELF,
    "role":     TaskOwnerType.ROLE,
    "shared":   TaskOwnerType.SHARED,
    "inferred": TaskOwnerType.INFERRED,
    "fallback": TaskOwnerType.FALLBACK,
}

# owner_types that belong on the current user's Google Calendar
CALENDAR_SYNC_TYPES = {"explicit", "self", "inferred", "fallback"}

# owner_types that trigger a Gmail notification to the assignee
NOTIFY_TYPES = {"explicit"}


class ExtractionService:

    # ── Similarity helpers ────────────────────────────────────────────────────

    def _token_overlap(self, a: str, b: str) -> float:
        """Jaccard similarity on word token sets."""
        ta = set(a.lower().split())
        tb = set(b.lower().split())
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    def _prefix_match(self, a: str, b: str, min_len: int = 5) -> bool:
        """True if either string starts with the other."""
        a, b = a.lower().strip(), b.lower().strip()
        if len(a) < min_len or len(b) < min_len:
            return False
        return a.startswith(b) or b.startswith(a)

    def _substring_containment(self, a: str, b: str) -> float:
        """Fraction of the shorter string's tokens present in the longer."""
        ta = set(a.lower().split())
        tb = set(b.lower().split())
        if not ta or not tb:
            return 0.0
        shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        return len(shorter & longer) / len(shorter)

    def _is_duplicate(self, normalized: str, other: str, db_check: bool = True) -> bool:
        """
        3-signal duplicate check.

        DB check (lenient)  — Jaccard > 0.75 OR containment > 0.90 OR prefix
        Batch check (strict) — Jaccard > 0.85 OR containment > 0.95
        """
        jaccard     = self._token_overlap(normalized, other)
        containment = self._substring_containment(normalized, other)
        prefix      = self._prefix_match(normalized, other)
        if db_check:
            return jaccard > 0.75 or containment > 0.90 or prefix
        else:
            return jaccard > 0.85 or containment > 0.95

    # ── Routing helpers ───────────────────────────────────────────────────────

    def _should_sync_to_calendar(
        self,
        owner: Optional[str],
        owner_type: Optional[str],
        current_user_name: str,
    ) -> bool:
        """
        True only when:
          - owner_type is in CALENDAR_SYNC_TYPES (explicit/self/inferred/fallback)
          - owner matches current_user_name (case-insensitive)
        shared and role tasks never go to calendar — no clear individual owner.
        """
        if owner_type not in CALENDAR_SYNC_TYPES:
            return False
        if not owner:
            return False
        return owner.lower() == current_user_name.lower()

    def _should_notify_assignee(
        self,
        owner: Optional[str],
        owner_type: Optional[str],
        current_user_name: str,
    ) -> bool:
        """
        True only when:
          - owner_type is 'explicit' (a real person's name was found in text)
          - owner is NOT the current user (no point notifying yourself)
        """
        if owner_type not in NOTIFY_TYPES:
            return False
        if not owner:
            return False
        return owner.lower() != current_user_name.lower()

    # ── Reminders ─────────────────────────────────────────────────────────────

    def _create_reminders(self, db: AsyncSession, task: Task) -> None:
        if not task.deadline:
            return
        now = datetime.now(timezone.utc)
        one_day = task.deadline - timedelta(days=1)
        if one_day > now:
            db.add(Reminder(task_id=task.id, remind_at=one_day, method="email"))
        one_hour = task.deadline - timedelta(hours=1)
        if one_hour > now:
            db.add(Reminder(task_id=task.id, remind_at=one_hour, method="popup"))

    # ── Main pipeline ─────────────────────────────────────────────────────────

    async def extract_and_save(
        self,
        text: str,
        user_id: int,
        current_user_name: str,
        source_url: Optional[str],
        source_context: Optional[str],
        auto_create: bool,
        db: AsyncSession,
    ) -> ExtractionResponse:
        """
        Full extraction pipeline:
          1. Run rule engine with ownership resolution
          2. Deduplicate against existing DB tasks
          3. Route tasks by owner_type
          4. Save to DB with ownership fields
          5. Log extraction history
          6. Return structured response
        """
        start_ms = int(time.time() * 1000)

        if not source_context or source_context in ("webpage", "auto"):
            source_context = detect_context_from_text(text)

        # ── Step 1: Rule engine ───────────────────────────────────────────────
        # current_user_name is passed so infer_task_ownership() can resolve
        # pronouns (I/we/my → current user) and chain inference correctly.
        rule_results     = rule_extract(text, current_user=current_user_name)
        raw_tasks        = rule_results["tasks"]
        raw_decisions    = rule_results.get("decisions", [])
        raw_dependencies = rule_results.get("dependencies", [])

        logger.info(
            "Rule engine: %d tasks, %d decisions, %d dependencies (user=%s)",
            len(raw_tasks), len(raw_decisions), len(raw_dependencies), current_user_name,
        )

        # ── Early exit: no tasks ──────────────────────────────────────────────
        if not raw_tasks:
            elapsed = int(time.time() * 1000) - start_ms
            db.add(ExtractionHistory(
                user_id=user_id,
                source_url=source_url,
                source_context=source_context,
                raw_input=text[:5000],
                tasks_extracted=0,
                processing_time_ms=elapsed,
            ))
            await db.commit()
            return ExtractionResponse(
                tasks_found=0,
                duplicates_filtered=0,
                processing_time_ms=elapsed,
                tasks=[],
                saved_task_ids=[],
                decisions=[DecisionItem(decision_text=d["decision_text"]) for d in raw_decisions],
                dependencies=[DependencyItem(**d) for d in raw_dependencies],
            )

        # ── Step 2: Load + pre-normalise existing tasks ───────────────────────
        existing_result = await db.execute(
            select(Task.id, Task.title).where(Task.owner_id == user_id)
        )
        existing_tasks = [
            {"id": r.id, "title": r.title, "norm": normalize_task_title(r.title)}
            for r in existing_result.fetchall()
        ]

        # ── Step 3: Dedup + build previews ────────────────────────────────────
        seen_this_batch: List[str] = []
        previews: List[ExtractedTaskPreview] = []
        duplicates_filtered = 0

        for task in raw_tasks:
            title           = task.get("title", "Untitled task")
            priority_str    = task.get("priority", "medium").lower()
            normalized      = normalize_task_title(title)
            owner           = task.get("owner")
            owner_type      = task.get("owner_type")
            owner_inferred  = task.get("owner_inferred", False)
            intervention_by = task.get("intervention_by")

            if not normalized or len(normalized) < 2:
                continue

            is_dup = False
            dup_id = None

            for ex in existing_tasks:
                if self._is_duplicate(normalized, ex["norm"], db_check=True):
                    is_dup = True
                    dup_id = ex["id"]
                    duplicates_filtered += 1
                    logger.debug("Dup (DB): '%s' ~ '%s'", title, ex["title"])
                    break

            if not is_dup:
                for seen in seen_this_batch:
                    if self._is_duplicate(normalized, seen, db_check=False):
                        is_dup = True
                        duplicates_filtered += 1
                        logger.debug("Dup (batch): '%s'", title)
                        break

            if not is_dup:
                seen_this_batch.append(normalized)

            # Deadline timezone safety
            deadline: Optional[datetime] = None
            raw_dl = task.get("deadline")
            if isinstance(raw_dl, datetime):
                deadline = raw_dl
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)

            # Routing decision for this task
            sync_to_calendar = self._should_sync_to_calendar(owner, owner_type, current_user_name)
            notify_assignee  = self._should_notify_assignee(owner, owner_type, current_user_name)

            previews.append(ExtractedTaskPreview(
                title=title,
                description=task.get("description"),
                raw_text=task.get("description", ""),
                assigned_to=owner,
                deadline=deadline,
                deadline_raw=task.get("deadline_raw"),
                priority=PRIORITY_MAP.get(priority_str, TaskPriority.MEDIUM),
                confidence_score=float(task.get("confidence", 0.55)),
                is_duplicate=is_dup,
                duplicate_of_id=dup_id,
                owner_type=owner_type,
                owner_inferred=owner_inferred,
                intervention_by=intervention_by,
                sync_to_calendar=sync_to_calendar,
                notify_assignee=notify_assignee,
            ))

        # ── Step 4: Save to DB ────────────────────────────────────────────────
        saved_ids: List[int] = []
        tasks_to_notify: List[Task] = []

        if auto_create:
            for preview in previews:
                if preview.is_duplicate:
                    continue

                db_task = Task(
                    title=preview.title,
                    description=preview.description,
                    raw_text=preview.raw_text,
                    source_url=source_url,
                    source_context=source_context,
                    assigned_to=preview.assigned_to,
                    deadline=preview.deadline,
                    deadline_raw=preview.deadline_raw,
                    priority=preview.priority,
                    confidence_score=preview.confidence_score,
                    owner_id=user_id,
                    # Ownership fields
                    owner_type=OWNER_TYPE_MAP.get(preview.owner_type) if preview.owner_type else None,
                    owner_inferred=preview.owner_inferred or False,
                    intervention_by=preview.intervention_by,
                    calendar_synced=False,
                    notified_assignee=False,
                )
                db.add(db_task)
                await db.flush()
                saved_ids.append(db_task.id)

                if preview.deadline:
                    self._create_reminders(db, db_task)

                if preview.notify_assignee:
                    tasks_to_notify.append(db_task)

        # ── Step 5: Log extraction history ────────────────────────────────────
        elapsed = int(time.time() * 1000) - start_ms
        db.add(ExtractionHistory(
            user_id=user_id,
            source_url=source_url,
            source_context=source_context,
            raw_input=text[:5000],
            tasks_extracted=len(saved_ids),
            processing_time_ms=elapsed,
        ))
        await db.commit()

        # ── Step 6: Routing summary ───────────────────────────────────────────
        my_count      = sum(1 for p in previews if not p.is_duplicate and p.sync_to_calendar)
        deleg_count   = sum(1 for p in previews if not p.is_duplicate and p.notify_assignee)
        shared_count  = sum(1 for p in previews if not p.is_duplicate and p.owner_type == "shared")
        role_count    = sum(1 for p in previews if not p.is_duplicate and p.owner_type == "role")

        logger.info(
            "Routing — mine: %d | delegated: %d | shared: %d | needs assignment: %d",
            my_count, deleg_count, shared_count, role_count,
        )

        if tasks_to_notify:
            logger.info(
                "%d task(s) flagged for Gmail notification: %s",
                len(tasks_to_notify), [t.assigned_to for t in tasks_to_notify],
            )
            # ── Step 8: Gmail notify delegated tasks ─────────────────────────
            creds = gmail_router._get_user_token(user_id)
            if not creds:
                logger.warning("Step 8: no Gmail credentials for user %d — skipping notifications", user_id)
            else:
                # Load all STKE users once for name→email lookup
                result      = await db.execute(select(User))
                all_users   = result.scalars().all()
                name_to_email = {}
                for u in all_users:
                    if u.full_name:
                        name_to_email[u.full_name.strip().lower()] = u.email
                    name_to_email[u.username.strip().lower()] = u.email

                for task in tasks_to_notify:
                    assignee_name  = (task.assigned_to or "").strip()
                    assignee_email = name_to_email.get(assignee_name.lower())

                    if not assignee_email:
                        logger.info(
                            "Step 8: no STKE account found for assignee '%s' — skipping",
                            assignee_name,
                        )
                        continue

                    sent = gmail_service.notify_assignee(
                        creds_dict     = creds,
                        assignee_email = assignee_email,
                        assignee_name  = assignee_name,
                        sender_name    = current_user_name or "Your teammate",
                        task_title     = task.title,
                        deadline_raw   = task.deadline.strftime("%A, %B %-d") if task.deadline else None,
                        source_context = source_context,
                    )

                    if sent:
                        task.notified_assignee    = True
                        task.notification_sent_at = datetime.now(timezone.utc)
                        logger.info("Step 8: notification sent to %s for task '%s'", assignee_email, task.title)
                    else:
                        logger.warning("Step 8: notification FAILED for %s — task '%s'", assignee_email, task.title)

                await db.commit()   # persist notified_assignee + notification_sent_at

        return ExtractionResponse(
            tasks_found=len(previews),
            duplicates_filtered=duplicates_filtered,
            processing_time_ms=elapsed,
            tasks=previews,
            saved_task_ids=saved_ids,
            decisions=[DecisionItem(decision_text=d["decision_text"]) for d in raw_decisions],
            dependencies=[DependencyItem(**d) for d in raw_dependencies],
        )


extraction_service = ExtractionService()