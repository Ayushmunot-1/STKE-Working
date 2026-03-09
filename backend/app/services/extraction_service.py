"""
STKE Extraction Service — Fast Rule-Based Pipeline
No Ollama for extraction — instant results
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import Task, Reminder, ExtractionHistory, TaskPriority
from app.models.schemas import ExtractedTaskPreview, ExtractionResponse, DecisionItem, DependencyItem
from app.nlp.rule_engine import rule_extract, detect_context_from_text, normalize_task_title

logger = logging.getLogger(__name__)

PRIORITY_MAP = {
    "low": TaskPriority.LOW,
    "medium": TaskPriority.MEDIUM,
    "high": TaskPriority.HIGH,
    "critical": TaskPriority.CRITICAL,
}


class ExtractionService:

    def _token_overlap(self, a: str, b: str) -> float:
        ta = set(a.lower().split())
        tb = set(b.lower().split())
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

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

    async def extract_and_save(
        self,
        text: str,
        user_id: int,
        source_url: Optional[str],
        source_context: Optional[str],
        auto_create: bool,
        db: AsyncSession,
    ) -> ExtractionResponse:

        start_ms = int(time.time() * 1000)

        # Auto-detect context
        if not source_context or source_context in ("webpage", "auto"):
            source_context = detect_context_from_text(text)

        # Rule engine — fast, no Ollama
        rule_results = rule_extract(text)
        raw_tasks = rule_results["tasks"]
        raw_decisions = rule_results.get("decisions", [])
        raw_dependencies = rule_results.get("dependencies", [])
        logger.info("Rule engine: %d tasks, %d decisions, %d dependencies",
                    len(raw_tasks), len(raw_decisions), len(raw_dependencies))

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

        # Load existing tasks for dedup
        existing_result = await db.execute(
            select(Task.id, Task.title).where(Task.owner_id == user_id)
        )
        existing_tasks = [
            {"id": r.id, "title": r.title}
            for r in existing_result.fetchall()
        ]

        # Dedup + build previews
        seen_this_batch: List[str] = []
        previews: List[ExtractedTaskPreview] = []
        duplicates_filtered = 0

        for task in raw_tasks:
            title = task.get("title", "Untitled task")
            priority_str = task.get("priority", "medium").lower()
            normalized = normalize_task_title(title)

            if not normalized or len(normalized) < 2:
                continue

            is_dup = False
            dup_id = None

            # Check against saved DB tasks
            for ex in existing_tasks:
                ex_norm = normalize_task_title(ex["title"])
                if self._token_overlap(normalized, ex_norm) > 0.85:
                    is_dup = True
                    dup_id = ex["id"]
                    duplicates_filtered += 1
                    break

            # Check within this extraction batch
            if not is_dup:
                for seen in seen_this_batch:
                    if self._token_overlap(normalized, seen) > 0.90:
                        is_dup = True
                        duplicates_filtered += 1
                        break

            if not is_dup:
                seen_this_batch.append(normalized)

            # Resolve deadline
            deadline: Optional[datetime] = None
            raw_dl = task.get("deadline")
            if isinstance(raw_dl, datetime):
                deadline = raw_dl
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)

            previews.append(ExtractedTaskPreview(
                title=title,
                description=task.get("description"),
                raw_text=task.get("description", ""),
                assigned_to=task.get("owner"),
                deadline=deadline,
                deadline_raw=task.get("deadline_raw"),
                priority=PRIORITY_MAP.get(priority_str, TaskPriority.MEDIUM),
                confidence_score=float(task.get("confidence", 0.85)),
                is_duplicate=is_dup,
                duplicate_of_id=dup_id,
            ))

        # Save to DB
        saved_ids: List[int] = []
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
                )
                db.add(db_task)
                await db.flush()
                saved_ids.append(db_task.id)
                if preview.deadline:
                    self._create_reminders(db, db_task)

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