"""
STKE Data Models — v2.0

Changes from v1:
  - Duplicate imports cleaned up (Column/String/etc were imported twice)
  - calendar_event_id fixed to use modern Mapped[] style (was legacy Column())
  - Task model: 6 new ownership fields added
      owner_type, owner_inferred, artifact_id,
      intervention_by, notified_assignee, notification_sent_at
  - DB indexes added: (owner_id, status), (owner_id, created_at),
      owner_type, owner_inferred, notified_assignee
  - ExtractionHistory: was_truncated field added
  - TaskOwnerType enum added for owner_type values
"""

from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    String, Integer, Text, DateTime, ForeignKey,
    Boolean, Float, Index,
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


# ══════════════════════════════════════════════════════════════
#  Enums
# ══════════════════════════════════════════════════════════════

class TaskStatus(str, enum.Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"


class TaskPriority(str, enum.Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class TaskOwnerType(str, enum.Enum):
    """
    How the task owner was determined.

    explicit   — spaCy found a PERSON entity or clear name in text
    self       — pronoun (I/we/my/our) mapped to the logged-in user
    role       — role word found (manager, CTO, team lead, etc.)
    shared     — group word found (team, everyone, all, etc.)
    inferred   — chain inference from last known artifact owner
    fallback   — no signal at all; defaulted to current user
    """
    EXPLICIT = "explicit"
    SELF     = "self"
    ROLE     = "role"
    SHARED   = "shared"
    INFERRED = "inferred"
    FALLBACK = "fallback"


# ══════════════════════════════════════════════════════════════
#  User
# ══════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id            : Mapped[int]           = mapped_column(Integer, primary_key=True, index=True)
    email         : Mapped[str]           = mapped_column(String(255), unique=True, index=True, nullable=False)
    username      : Mapped[str]           = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str]          = mapped_column(String(255), nullable=False)
    full_name     : Mapped[Optional[str]] = mapped_column(String(255))
    is_active     : Mapped[bool]          = mapped_column(Boolean, default=True)
    created_at    : Mapped[datetime]      = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    tasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="owner", cascade="all, delete-orphan"
    )


# ══════════════════════════════════════════════════════════════
#  Task
# ══════════════════════════════════════════════════════════════

class Task(Base):
    __tablename__ = "tasks"

    # ── Core identity ─────────────────────────────────────────
    id          : Mapped[int]           = mapped_column(Integer, primary_key=True, index=True)
    title       : Mapped[str]           = mapped_column(String(500), nullable=False)
    description : Mapped[Optional[str]] = mapped_column(Text)
    raw_text    : Mapped[Optional[str]] = mapped_column(Text)
    source_url  : Mapped[Optional[str]] = mapped_column(String(2000))
    source_context: Mapped[Optional[str]] = mapped_column(String(100))

    # ── Scheduling ────────────────────────────────────────────
    assigned_to  : Mapped[Optional[str]]      = mapped_column(String(255))
    deadline     : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deadline_raw : Mapped[Optional[str]]      = mapped_column(String(100))
    priority     : Mapped[TaskPriority]       = mapped_column(
        SAEnum(TaskPriority), default=TaskPriority.MEDIUM
    )
    status       : Mapped[TaskStatus]         = mapped_column(
        SAEnum(TaskStatus), default=TaskStatus.PENDING
    )

    # ── NLP metadata ──────────────────────────────────────────
    confidence_score : Mapped[float]          = mapped_column(Float, default=0.0)
    embedding_json   : Mapped[Optional[str]]  = mapped_column(Text)

    # ── Calendar sync ─────────────────────────────────────────
    # FIXED: was legacy Column(String(255)) — now uses modern Mapped[] style
    calendar_event_id : Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    calendar_synced   : Mapped[bool]          = mapped_column(Boolean, default=False)

    # ── Ownership fields (NEW in v2.0) ────────────────────────
    #
    # owner_type: How was the owner determined?
    #   - 'explicit' → clear name found in text by spaCy NER
    #   - 'self'     → pronoun (I/we/my) → logged-in user
    #   - 'role'     → role word (manager/CTO) — needs manual assignment
    #   - 'shared'   → group word (team/everyone) — no individual owner
    #   - 'inferred' → chain inference from previous artifact owner
    #   - 'fallback' → no signal at all, defaulted to current user
    #
    owner_type : Mapped[Optional[str]] = mapped_column(
        SAEnum(TaskOwnerType, values_callable=lambda x: [e.value for e in x]),
        nullable=True,
        default=None,
    )

    # owner_inferred: True = ownership was guessed, not stated explicitly.
    # Dashboard shows these with a warning badge so user can verify.
    owner_inferred : Mapped[bool] = mapped_column(Boolean, default=False)

    # artifact_id: If this task is part of a chain, this points to the
    # first/root task in the chain (the original ownership task).
    # Used for chain visualization in the dashboard.
    artifact_id : Mapped[Optional[int]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    # intervention_by: If this task is an intervention (review/approve/check),
    # this stores the person DOING the intervention (e.g. "Sarah").
    # The task owner (artifact owner) is still stored in assigned_to.
    intervention_by : Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)

    # notified_assignee: True = a Gmail notification was sent to the assignee.
    # Prevents duplicate notifications on re-extraction.
    notified_assignee : Mapped[bool] = mapped_column(Boolean, default=False)

    # notification_sent_at: When the Gmail notification was sent.
    # Useful for audit trail and dashboard display.
    notification_sent_at : Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # ── Relationships ─────────────────────────────────────────
    owner_id : Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owner    : Mapped["User"] = relationship("User", back_populates="tasks")

    reminders: Mapped[List["Reminder"]] = relationship(
        "Reminder", back_populates="task", cascade="all, delete-orphan"
    )

    # Self-referential relationship for artifact chain tracking
    artifact_parent: Mapped[Optional["Task"]] = relationship(
        "Task", remote_side="Task.id", foreign_keys=[artifact_id]
    )

    # ── Timestamps ────────────────────────────────────────────
    created_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── DB Indexes (NEW in v2.0) ──────────────────────────────
    # These make dashboard queries dramatically faster as data grows.
    #
    # Why these specific indexes?
    #   - Dashboard "My Tasks" tab: filters by owner_id + status constantly
    #   - Dashboard "Delegated" tab: filters by owner_id + owner_type
    #   - "Needs Assignment" tab: filters by owner_type + owner_inferred
    #   - Notification worker: scans notified_assignee=False periodically
    #
    __table_args__ = (
        Index("ix_task_owner_status",    "owner_id",    "status"),
        Index("ix_task_owner_created",   "owner_id",    "created_at"),
        Index("ix_task_owner_type",      "owner_type"),
        Index("ix_task_owner_inferred",  "owner_inferred"),
        Index("ix_task_notified",        "notified_assignee"),
    )


# ══════════════════════════════════════════════════════════════
#  Reminder (unchanged)
# ══════════════════════════════════════════════════════════════

class Reminder(Base):
    __tablename__ = "reminders"

    id        : Mapped[int]      = mapped_column(Integer, primary_key=True)
    task_id   : Mapped[int]      = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    remind_at : Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method    : Mapped[str]      = mapped_column(String(50), default="email")
    sent      : Mapped[bool]     = mapped_column(Boolean, default=False)

    task: Mapped["Task"] = relationship("Task", back_populates="reminders")


# ══════════════════════════════════════════════════════════════
#  ExtractionHistory (was_truncated field added)
# ══════════════════════════════════════════════════════════════

class ExtractionHistory(Base):
    __tablename__ = "extraction_history"

    id              : Mapped[int]           = mapped_column(Integer, primary_key=True)
    user_id         : Mapped[int]           = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_url      : Mapped[Optional[str]] = mapped_column(String(2000))
    source_context  : Mapped[Optional[str]] = mapped_column(String(100))
    raw_input       : Mapped[str]           = mapped_column(Text, nullable=False)
    tasks_extracted : Mapped[int]           = mapped_column(Integer, default=0)
    processing_time_ms: Mapped[int]         = mapped_column(Integer, default=0)

    # was_truncated: True if raw_input was cut off at 5000 chars.
    # Previously this happened silently with no flag. Now it's tracked.
    was_truncated   : Mapped[bool]          = mapped_column(Boolean, default=False)

    created_at      : Mapped[datetime]      = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Index for analytics queries: "show history for last 30 days"
    __table_args__ = (
        Index("ix_history_user_created", "user_id", "created_at"),
    )