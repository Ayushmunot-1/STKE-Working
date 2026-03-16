"""
STKE Schemas — v2.0

Changes from v1:
  - ExtractedTaskPreview: 5 new ownership fields added
      owner_type, owner_inferred, intervention_by,
      sync_to_calendar, notify_assignee
  - ExtractionResponse: routing summary counts added
      my_tasks_count, delegated_count, shared_count, needs_assignment_count
  - TaskResponse: 4 new ownership fields added
      owner_type, owner_inferred, intervention_by,
      notified_assignee, notification_sent_at
  - ExtractionRequest: max_length validator added (security fix)
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from app.models.models import TaskStatus, TaskPriority, TaskOwnerType


# ══════════════════════════════════════════════════════════════
#  Auth
# ══════════════════════════════════════════════════════════════

class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8)
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    username: str


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: Optional[str]
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════
#  Extraction
# ══════════════════════════════════════════════════════════════

class ExtractionRequest(BaseModel):
    # FIXED: max_length added — prevents DoS via huge text payloads
    text: str = Field(min_length=10, max_length=50000)
    source_url: Optional[str] = None
    source_context: Optional[str] = None
    auto_create_tasks: bool = True


class ExtractedTaskPreview(BaseModel):
    # ── Core fields (unchanged) ───────────────────────────────
    title: str
    description: Optional[str] = None
    raw_text: str
    assigned_to: Optional[str] = None
    deadline: Optional[datetime] = None
    deadline_raw: Optional[str] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    confidence_score: float
    is_duplicate: bool = False
    duplicate_of_id: Optional[int] = None

    # ── Ownership fields (NEW in v2.0) ────────────────────────
    #
    # owner_type: How the owner was determined
    #   explicit / self / role / shared / inferred / fallback
    owner_type: Optional[str] = None

    # owner_inferred: True = ownership was guessed via chain inference
    # Dashboard shows these with a ⚠️ badge so user can verify
    owner_inferred: bool = False

    # intervention_by: Person doing review/approve on someone else's artifact
    # e.g. "Sarah reviews John's report" → assigned_to=John, intervention_by=Sarah
    intervention_by: Optional[str] = None

    # sync_to_calendar: True = this task will be synced to current user's calendar
    # Only True when owner matches current user
    sync_to_calendar: bool = False

    # notify_assignee: True = a Gmail notification should be sent to the assignee
    # Only True when owner is an explicit named person who is NOT the current user
    notify_assignee: bool = False


class DecisionItem(BaseModel):
    decision_text: str


class DependencyItem(BaseModel):
    prerequisite: str
    dependent: str
    raw_text: Optional[str] = None


class ExtractionResponse(BaseModel):
    # ── Core stats (unchanged) ────────────────────────────────
    tasks_found: int
    duplicates_filtered: int
    processing_time_ms: int
    tasks: List[ExtractedTaskPreview]
    saved_task_ids: List[int] = []
    decisions: List[DecisionItem] = []
    dependencies: List[DependencyItem] = []

    # ── Routing summary (NEW in v2.0) ─────────────────────────
    # Breakdown of where extracted tasks were routed.
    # Powers the 4-tab dashboard: My Tasks | Delegated | Team | Needs Assignment
    my_tasks_count: int = 0         # tasks synced to current user's calendar
    delegated_count: int = 0        # tasks where Gmail notification was sent
    shared_count: int = 0           # tasks with group owner (team/everyone)
    needs_assignment_count: int = 0 # tasks with role owner (manager/CTO)


# ══════════════════════════════════════════════════════════════
#  Tasks
# ══════════════════════════════════════════════════════════════

class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    description: Optional[str] = None
    assigned_to: Optional[str] = None
    deadline: Optional[datetime] = None
    deadline_raw: Optional[str] = None
    priority: TaskPriority = TaskPriority.MEDIUM


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[str] = None
    deadline: Optional[datetime] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None


class ReminderResponse(BaseModel):
    id: int
    remind_at: datetime
    method: str
    sent: bool
    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    # ── Core fields (unchanged) ───────────────────────────────
    id: int
    title: str
    description: Optional[str]
    raw_text: Optional[str]
    source_url: Optional[str]
    source_context: Optional[str]
    assigned_to: Optional[str]
    deadline: Optional[datetime]
    deadline_raw: Optional[str]
    priority: TaskPriority
    status: TaskStatus
    confidence_score: float
    calendar_synced: bool
    calendar_event_id: Optional[str] = None
    owner_id: int
    reminders: List[ReminderResponse] = []
    created_at: datetime
    updated_at: datetime

    # ── Ownership fields (NEW in v2.0) ────────────────────────
    owner_type: Optional[str] = None
    owner_inferred: bool = False
    intervention_by: Optional[str] = None
    notified_assignee: bool = False
    notification_sent_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    total: int
    tasks: List[TaskResponse]


# ══════════════════════════════════════════════════════════════
#  Gmail Notification (NEW in v2.0)
# ══════════════════════════════════════════════════════════════

class NotifyAssigneeRequest(BaseModel):
    """
    Payload for POST /api/v1/gmail/notify/{task_id}
    User confirms the assignee's email before we send anything.
    """
    assignee_email: EmailStr


class NotifyAssigneeResponse(BaseModel):
    success: bool
    message: str
    task_id: int
    assignee_email: str
    notified_at: Optional[datetime] = None