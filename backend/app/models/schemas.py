from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from app.models.models import TaskStatus, TaskPriority


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


class ExtractionRequest(BaseModel):
    text: str = Field(min_length=10)
    source_url: Optional[str] = None
    source_context: Optional[str] = None
    auto_create_tasks: bool = True


class ExtractedTaskPreview(BaseModel):
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


class DecisionItem(BaseModel):
    decision_text: str


class DependencyItem(BaseModel):
    prerequisite: str
    dependent: str
    raw_text: Optional[str] = None


class ExtractionResponse(BaseModel):
    tasks_found: int
    duplicates_filtered: int
    processing_time_ms: int
    tasks: List[ExtractedTaskPreview]
    saved_task_ids: List[int] = []
    decisions: List[DecisionItem] = []
    dependencies: List[DependencyItem] = []


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
    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    total: int
    tasks: List[TaskResponse]