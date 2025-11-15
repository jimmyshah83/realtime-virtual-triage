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
    """Create a Realtime API session with Azure OpenAI."""
    try:
        # Get the SDP payload from the request body
        sdp_payload = await request.body()
        print(f"Received SDP payload, length: {len(sdp_payload)}")
        
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
        
        print(f"URL from env: {url}")
        print(f"API key present: {bool(api_key)}")
        
        if not url or not api_key:
            return Response(
                content=json.dumps({"error": "Azure OpenAI credentials not configured"}),
                status_code=500,
                media_type="application/json"
            )
        
        # Prepare multipart form data
        files = {
            "sdp": ("sdp.txt", sdp_payload),
            "session": ("session.json", json.dumps(session_config).encode())
        }
        
        headers = {
            "api-key": api_key,
        }
        
        print(f"Sending request to: {url}")
        print(f"Headers: {headers}")
        
        # Make request to Azure OpenAI
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                files=files,
                headers=headers
            )
            
            print(f"Response status: {response.status_code}")
            print(f"Response body: {response.text}")
            
            if response.status_code != 200:
                return Response(
                    content=json.dumps({
                        "error": "Failed to create realtime session",
                        "details": response.text,
                        "status_code": response.status_code
                    }),
                    status_code=response.status_code,
                    media_type="application/json"
                )
            
            # Return the SDP response from Azure OpenAI
            return PlainTextResponse(content=response.text)
            
    except (httpx.RequestError, httpx.HTTPStatusError) as error:
        print(f"Exception occurred: {type(error).__name__}: {str(error)}")
        return Response(
            content=json.dumps({"error": f"Failed to create session: {str(error)}"}),
            status_code=500,
            media_type="application/json"
        )
    except Exception as error:
        print(f"Unexpected exception: {type(error).__name__}: {str(error)}")
        import traceback
        traceback.print_exc()
        return Response(
            content=json.dumps({"error": f"Unexpected error: {str(error)}"}),
            status_code=500,
            media_type="application/json"
        )
