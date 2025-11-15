# Realtime Virtual Triage

A multi-agent orchestration platform helping patients get triaged virtually using LangGraph, GPT-4o Realtime, and GPT-5.

## Overview

This project implements a virtual triage intake system where patients can have real-time conversations with an AI intake agent, get their symptoms structured and classified, and be routed to clinical guidance agents for assessment.

## Tech Stack

- **Backend**: Python/FastAPI with LangGraph for agent orchestration
- **Frontend**: TypeScript/React with Vite
- **AI Models**: 
  - GPT-4o Realtime (via Azure AI Foundry) for intake conversations
  - GPT-5 (via Azure AI Foundry) for clinical guidance
- **Transport**: WebRTC for low-latency audio streaming
- **State**: In-memory session store (scalable to persistence)

## Project Structure

```
realtime-virtual-triage/
├── docs/
│   └── intake-agent.md        # Intake agent architecture & design
├── backend/                    # Python/FastAPI backend
│   ├── pyproject.toml         # Python dependencies (uv)
│   ├── app/
│   │   ├── main.py            # FastAPI app
│   │   ├── config.py          # Configuration
│   │   ├── models.py          # Data models
│   │   ├── session_store.py   # In-memory session store
│   │   ├── gpt4o_client.py    # GPT-4o Realtime wrapper
│   │   ├── intake_graph.py    # LangGraph orchestration
│   │   └── routes.py          # API routes
│   └── README.md              # Backend setup & API docs
└── frontend/                   # TypeScript/React frontend
    ├── package.json           # Node dependencies
    ├── src/
    │   ├── App.tsx            # Main app
    │   ├── store.ts           # Zustand state
    │   ├── api.ts             # Backend API client
    │   ├── webrtc.ts          # WebRTC manager
    │   └── components/
    │       ├── IntakeForm.tsx
    │       └── TranscriptDisplay.tsx
    └── README.md              # Frontend setup & features
```

## Quick Start

### Backend Setup

```bash
cd backend
cp .env.example .env  # Update with Azure AI Foundry credentials
uv sync
uv run python -m uvicorn app.main:app --reload --port 8000
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev  # Runs on http://localhost:5173
```

## Architecture

### Intake Agent Flow

1. **Frontend**: User selects language and starts microphone capture
2. **WebRTC**: Audio streams from browser to backend over peer connection
3. **Backend**: Receives audio stream and forwards to GPT-4o Realtime
4. **GPT-4o Realtime**: Transcribes and understands user speech in their language
5. **Symptom Extraction**: LangGraph node extracts structured symptom data
6. **Session Store**: Symptoms stored in-memory, ready for clinical guidance agent
7. **Frontend**: Displays extracted symptoms and next steps

### Data Contracts

See `docs/intake-agent.md` for detailed API specifications and data schemas.

## Configuration

### Backend Environment Variables

```bash
AZURE_FOUNDRY_ENDPOINT=https://your-foundry.openai.azure.com/
AZURE_FOUNDRY_API_KEY=your-api-key
AZURE_DEPLOYMENT_NAME_REALTIME=gpt-4o-realtime
SESSION_TTL_HOURS=24
STUN_SERVERS=stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302
```

### Frontend Environment Variables

```bash
VITE_BACKEND_URL=http://localhost:8000
```

## Features

- ✅ Multilingual intake (English, Spanish, French, Chinese, Arabic, Hindi)
- ✅ Real-time microphone capture with WebRTC
- ✅ Live transcript display
- ✅ Structured symptom extraction via GPT-4o
- ✅ In-memory session management
- ⏳ GPT-4o Realtime integration (WIP)
- ⏳ WebRTC signaling (WIP)
- ⏳ Clinical guidance agent (WIP)

## API Documentation

See:
- Backend API: `http://localhost:8000/docs` (Swagger UI)
- Intake agent design: `docs/intake-agent.md`

## Testing

### Backend

```bash
cd backend
uv run pytest
```

### Frontend

```bash
cd frontend
npm test
```

## Deployment

### Docker (Future)

```bash
docker build -t virtual-triage-backend backend/
docker run -p 8000:8000 -e AZURE_FOUNDRY_API_KEY=... virtual-triage-backend
```

### Cloud Deployment (Future)

- Backend: Azure App Service / Container Apps
- Frontend: Azure Static Web Apps / Blob Storage + CDN
- Monitoring: Application Insights, Azure Monitor

## Next Steps

1. **Implement GPT-4o Realtime client**: Connect to Azure OpenAI and stream audio
2. **WebRTC signaling**: Use aiortc for peer connection management
3. **Symptom extraction**: Build LangGraph node for structured output
4. **Clinical guidance agent**: Implement GPT-5 assessment workflow
5. **Testing & observability**: Add unit tests, integration tests, and tracing
6. **Persistence**: Migrate in-memory store to database
7. **HIPAA compliance**: Add encryption, audit logs, and PII redaction

## Contributing

1. Review `docs/intake-agent.md` for architecture
2. Follow the project structure and coding conventions
3. Write tests for new features
4. Submit PRs with clear descriptions

## License

See LICENSE file
