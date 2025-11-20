# Realtime Virtual Triage

A multi-agent orchestration platform helping patients get triaged virtually using LangGraph, GPT Realtime, and GPT-5.

## Architecture Overview

- **Browser client (`frontend/src/App.tsx`)** captures microphone audio, maintains a chat transcript UI, and manages a `RTCPeerConnection` plus data channel to Azure Realtime. It also calls FastAPI REST endpoints to keep LangGraph state authoritative.
- **Azure Realtime API (WebRTC + Whisper + TTS)** receives the browser audio stream, performs built-in transcription, emits transcript events over the data channel, and plays synthesized speech when the frontend sends assistant text back.
- **FastAPI backend (`backend/app/main.py`)** exposes `/session` to mint Azure ephemeral keys and `/chat/{session_id}` to run the LangGraph workflow. It stores a `TriageAgentState` per session in memory for the proof of concept.
- **LangGraph agents (`backend/app/agents.py`)** host the triage nurse agent and referral builder agent, using `AzureChatOpenAI` structured outputs to keep assessments, red flags, medical codes, and referral packages consistent.
- **Session store** is currently an in-memory dictionary for rapid iteration; swap with Redis or Postgres when you need durability or horizontal scale.

```text
Mic → Browser WebRTC → Azure Realtime (Whisper STT)
                               ↓ transcripts via data channel
                      FastAPI `/chat/{session}` → LangGraph triage/referral
                               ↓ response text
Browser data channel → Azure Realtime TTS → Speakers
```

## Detailed Flow

1. **Session bootstrap** – The frontend requests `POST /session`. FastAPI proxies to Azure using `AZURE_OPENAI_*` credentials and returns the ephemeral key and session id that the browser will use for the SDP exchange.
2. **WebRTC connection** – `startRealtimeSession` in `frontend/src/App.tsx` creates a peer connection, adds the mic track, opens the `realtime-channel` data channel, and exchanges SDP with `https://{region}.realtimeapi-preview.ai.azure.com/v1/realtimertc`.
3. **Turn detection + transcription** – Azure Whisper performs speech-to-text and pushes `conversation.item.input_audio_transcription.completed` events on the data channel. The frontend appends each transcript to the chat history for transparency.
4. **Backend orchestration call** – For every finalized transcript, `processWithAgents` POSTs `/chat/{session_id}`. FastAPI records the utterance as a `HumanMessage`, retrieves the session state, and invokes `triage_graph`.
5. **Agent reasoning** – Inside `triage_graph`, the triage agent updates symptoms, urgency, and red flags. When `handoff_ready` becomes true, the referral builder agent compiles the referral package, all using `AzureChatOpenAI` structured outputs defined in `backend/app/agents.py`.
6. **Response payload** – `/chat/{session_id}` returns `ChatResponse` containing the assistant narrative, current agent label, urgency score, and referral completion flag. The frontend renders the message and updates the status indicator.
7. **Speech synthesis loop** – The frontend pushes the same response text back to Azure Realtime via the data channel (`conversation.item.create` followed by `response.create`). Azure converts it to speech on the existing audio track, so the user hears the answer immediately.
8. **Session lifecycle** – Optional `GET /chat/{session_id}` exposes current state for debugging, while `DELETE /chat/{session_id}` clears memory. Reconnect logic can request a new `/session` token if the peer connection drops.

## Running 

1. Backend `uvicorn app.main:app --reload`
2. Frontend `npm run dev`
