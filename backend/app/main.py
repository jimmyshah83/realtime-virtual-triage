"""Main FastAPI application entry point."""

import json
import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

# Load environment variables from .env file
load_dotenv()

app = FastAPI(
    title="Real-time Virtual Triage",
    description="Real-time virtual triage backend API",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Real-time Virtual Triage API"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/session")
async def create_session(request: Request) -> Response:
    """Generate an ephemeral key for Azure OpenAI Realtime session."""
    try:
        api_key = os.environ["AZURE_OPENAI_API_KEY"]
        resource_name = os.environ["AZURE_OPENAI_RESOURCE_NAME"]
        api_version = os.environ["AZURE_OPENAI_API_VERSION"]
        deployment = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

        session_url = f"https://{resource_name}.openai.azure.com/openai/realtimeapi/sessions?api-version={api_version}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                session_url,
                json={
                    "model": deployment,
                    "voice": "alloy"
                },
                headers={
                    "api-key": api_key,
                    "Content-Type": "application/json"
                }
            )

            if response.status_code != 200:
                return Response(
                    content=json.dumps(
                        {
                            "error": "Failed to create session",
                            "details": response.text
                        }
                    )
                )