# Backend - Realtime Virtual Triage

Python/FastAPI backend service for the intake agent.

## Directory Structure

```bash
backend/
├── pyproject.toml          # Project dependencies and metadata
├── .env                    # Environment variables (create locally)
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI app entry point
│   ├── config.py           # Configuration management
│   ├── models.py           # Pydantic models (requests/responses)
│   ├── session_store.py    # In-memory session management
│   ├── gpt4o_client.py     # GPT-4o Realtime API wrapper
│   ├── intake_graph.py     # LangGraph intake agent orchestration
│   └── routes.py           # WebRTC signaling and WebSocket endpoints
└── tests/
    ├── __init__.py
    ├── test_session_store.py
    ├── test_routes.py
    └── test_intake_graph.py
```

## Setup

### Prerequisites

- Python 3.11+
- `uv` package manager

### Installation

```bash
# Install dependencies
uv pip install -e ".[dev]"

# Or using uv directly
uv sync
```

### Environment Configuration

Create a `.env` file in the `backend/` directory:

```bash
# Azure AI Foundry
AZURE_FOUNDRY_ENDPOINT=https://your-foundry-endpoint.openai.azure.com/
AZURE_FOUNDRY_API_KEY=your-api-key-here
AZURE_DEPLOYMENT_NAME_REALTIME=gpt-4o-realtime
AZURE_API_VERSION=2024-10-01-preview

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=True

# Logging
LOG_LEVEL=INFO
```

## Running

```bash
# Development with auto-reload
uv run python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

The API will be available at `http://localhost:8000`

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## API Endpoints

### Create Session

**POST** `/api/intake/sessions`

```json
{
  "user_language": "en",
  "user_id": "optional-user-id"
}
```

Response:

```json
{
  "session_id": "uuid",
  "ice_servers": [{"urls": ["stun:stun.l.google.com:19302"]}]
}
```

### WebRTC Offer/Answer

**POST** `/api/intake/sessions/{session_id}/offer`

**POST** `/api/intake/sessions/{session_id}/candidates`

### WebSocket Events

**WebSocket** `/ws/{session_id}/events`

Emits real-time events:

- `transcript_chunk`: Transcript updates from GPT-4o Realtime
- `status_update`: Session status changes
- `symptom_complete`: Symptoms extracted
- `error`: Error events

## Testing

```bash
# Run all tests
uv run pytest

# With coverage
uv run pytest --cov=app tests/

# Watch mode
uv run pytest-watch
```

## Project Status

### Implemented

- [x] FastAPI app scaffold
- [x] Session store (in-memory)
- [x] Models and data contracts
- [x] Configuration management
- [x] Route stubs (not yet connected to GPT-4o Realtime)

### TODO

- [ ] GPT-4o Realtime client implementation (audio streaming, transcription)
- [ ] WebRTC signaling with aiortc
- [ ] LangGraph intake agent integration
- [ ] Symptom extraction logic
- [ ] Error handling and resilience
- [ ] Observability (logging, metrics, tracing)
- [ ] Unit and integration tests
- [ ] Docker containerization
- [ ] Deployment configuration

## Key Dependencies

- **FastAPI**: Web framework
- **LangGraph**: Agent orchestration
- **langchain**: LLM integrations
- **aiortc**: WebRTC peer connection
- **openai**: Azure OpenAI SDK (for GPT-4o)
- **pydantic**: Data validation

## Notes

- Sessions are stored in-memory and not persisted; suitable for single-instance MVP
- Migrate to a database for multi-pod deployments
- STUN servers configured for public ICE discovery; TURN may be needed for restrictive NATs
