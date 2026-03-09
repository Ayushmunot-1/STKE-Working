from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.models import Task, TaskStatus, TaskPriority
from app.models.schemas import TaskCreate, TaskUpdate, TaskResponse, TaskListResponse

router = APIRouter()


async def get_task_or_404(task_id: int, user_id: int, db: AsyncSession) -> Task:
    result = await db.execute(
        select(Task)
        .options(selectinload(Task.reminders))
        .where(Task.id == task_id, Task.owner_id == user_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    status: Optional[TaskStatus] = None,
    priority: Optional[TaskPriority] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Task)
        .options(selectinload(Task.reminders))
        .where(Task.owner_id == user_id)
    )
    if status:
        query = query.where(Task.status == status)
    if priority:
        query = query.where(Task.priority == priority)

    count_result = await db.execute(
        select(func.count()).select_from(Task).where(Task.owner_id == user_id)
    )
    total = count_result.scalar_one()

    query = query.order_by(Task.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tasks = result.scalars().all()

    return TaskListResponse(total=total, tasks=list(tasks))


@router.post("/", response_model=TaskResponse, status_code=201)
async def create_task(
    payload: TaskCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = Task(
        title=payload.title,
        description=payload.description,
        assigned_to=payload.assigned_to,
        deadline=payload.deadline,
        deadline_raw=payload.deadline_raw,
        priority=payload.priority,
        owner_id=user_id,
        confidence_score=1.0,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await get_task_or_404(task_id, user_id, db)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await get_task_or_404(task_id, user_id, db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task, key, value)
    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await get_task_or_404(task_id, user_id, db)
    await db.delete(task)
    await db.commit()


@router.post("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await get_task_or_404(task_id, user_id, db)
    task.status = TaskStatus.COMPLETED
    await db.commit()
    await db.refresh(task)
    return task
