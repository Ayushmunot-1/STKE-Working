from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.database import engine, Base
from app.api import auth, tasks, extract, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all database tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="STKE - Semantic Task & Knowledge Extractor",
    description="Extract tasks from natural language using local AI",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow browser extension to talk to this server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routes
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(extract.router, prefix="/api/v1/extract", tags=["Extract"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"])


@app.get("/")
async def root():
    return {"service": "STKE API", "version": "1.0.0", "status": "running"}

# Add these lines to your existing main.py
# Place them AFTER your existing router includes

# ── Serve Dashboard ────────────────────────────────────────────
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os

# Serve dashboard.html at /dashboard
@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "..", "dashboard.html")
    return FileResponse(dashboard_path)

# Add these 2 lines to your existing app/main.py
# Place them after your existing router includes (after tasks, auth, extract, users)

from app.api import gmail
app.include_router(gmail.router, prefix="/api/v1/gmail", tags=["gmail"])
from app.api import calendar
app.include_router(calendar.router, prefix="/api/v1/calendar", tags=["calendar"])