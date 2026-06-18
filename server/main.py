
from fastapi import FastAPI

from app.api.router import api_router

app = FastAPI(
    title="Autonomous Clinical Discharge & Care-Plan Orchestrator",
    description="Conversational drug-safety agent with multi-tier security.",
    version="0.1.0",
)
app.include_router(api_router)
