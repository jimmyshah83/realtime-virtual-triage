"""Main FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(
    title="Real-time Virtual Triage",
    description="Real-time virtual triage backend API",
    version="0.1.0",
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Real-time Virtual Triage API"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
