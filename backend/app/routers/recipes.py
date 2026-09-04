"""Recipe browse/detail endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/recipes", tags=["recipes"])
