"""FastAPI application for Gabrr Budget transaction parsing."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.logging_config import configure_logging

configure_logging()

app = FastAPI(
    title="Gabrr Budget API",
    description="Parse financial documents (CSV/PDF) into normalized transactions",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
