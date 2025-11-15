"""Main FastAPI application"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import router as intake_router
from app.session_store import session_store

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def cleanup_expired_sessions():
    """Background task to clean up expired sessions"""
    while True:
        await asyncio.sleep(settings.session_cleanup_interval_minutes * 60)
        count = await session_store.cleanup_expired_sessions()
        logger.info(f"Cleanup task completed, removed {count} expired sessions")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app lifecycle (startup/shutdown)"""
    # Startup
    logger.info("Starting realtime triage backend...")
    cleanup_task = asyncio.create_task(cleanup_expired_sessions())

    yield

    # Shutdown
    logger.info("Shutting down...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Realtime Virtual Triage Backend",
    description="Backend for intake and clinical guidance agents",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict to frontend domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(intake_router)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    active_sessions = await session_store.get_active_session_count()
    return {
        "status": "healthy",
        "active_sessions": active_sessions,
        "gpt4o_configured": True,  # TODO: Check actual config
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Realtime Virtual Triage Backend",
        "version": "0.1.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
