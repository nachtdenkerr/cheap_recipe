"""Auth endpoints: signup, login, session."""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
