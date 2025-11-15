"""Main FastAPI application entry point."""

import json
import os

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

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


@app.post("/session")
async def create_session(request: Request) -> Response:
    """Create a Realtime API session with Azure OpenAI."""
    # Get the SDP payload from the request body
    sdp_payload = await request.body()
    
    # Configuration for the realtime session
    session_config = {
        "type": "realtime",
        "model": "gpt-realtime",
        "audio": {
            "output": {
                "voice": "alloy"
            }
        }
    }
    
    # Get Azure OpenAI credentials from environment
    url = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    
    if not url or not api_key:
        return Response(
            content=json.dumps({"error": "Azure OpenAI credentials not configured"}),
            status_code=500,
            media_type="application/json"
        )
    
    try:
        # Prepare multipart form data
        files = {
            "sdp": ("sdp.txt", sdp_payload),
            "session": ("session.json", json.dumps(session_config).encode())
        }
        
        headers = {
            "api-key": api_key,
        }
        
        # Make request to Azure OpenAI
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                files=files,
                headers=headers
            )
            
            if response.status_code != 200:
                return Response(
                    content=json.dumps({
                        "error": "Failed to create realtime session",
                        "details": response.text
                    }),
                    status_code=response.status_code,
                    media_type="application/json"
                )
            
            # Return the SDP response from Azure OpenAI
            return PlainTextResponse(content=response.text)
            
    except (httpx.RequestError, httpx.HTTPStatusError) as error:
        return Response(
            content=json.dumps({"error": f"Failed to create session: {str(error)}"}),
            status_code=500,
            media_type="application/json"
        )
