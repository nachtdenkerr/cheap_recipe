"""Recipe generation endpoints — drives the planner/critic agent loop."""

from fastapi import APIRouter

router = APIRouter(prefix="/generate", tags=["generate"])
