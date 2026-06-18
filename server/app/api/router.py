"""Top-level router — aggregates every feature router for FastAPI to mount."""
from fastapi import APIRouter

from app.api.routes import admin, auth, chat, health, patients

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(admin.router)
api_router.include_router(patients.router)
