# Frontend - Realtime Virtual Triage

TypeScript + React frontend for the intake agent UI.

## Directory Structure

```bash
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── .eslintrc.cjs
├── vite.svg
└── src/
    ├── main.tsx           # App entry point
    ├── App.tsx            # Main app component
    ├── App.css            # App styles
    ├── index.css          # Global styles
    ├── store.ts           # Zustand state management
    ├── api.ts             # API client for backend communication
    ├── webrtc.ts          # WebRTC connection management
    └── components/
        ├── IntakeForm.tsx       # Language selection and start form
        ├── IntakeForm.css
        ├── TranscriptDisplay.tsx # Live transcript display
        └── TranscriptDisplay.css
```

## Setup

### Prerequisites

- Node.js 16+
- npm or yarn

### Installation

```bash
# Install dependencies
npm install

# Or with yarn
yarn install
```

### Environment Configuration

Create a `.env` file in the `frontend/` directory:

```bash
# Backend API endpoint
VITE_BACKEND_URL=http://localhost:8000
```

## Running

```bash
# Development server (with hot reload)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Run linting
npm run lint

# Type check
npm run type-check
```

The app will be available at `http://localhost:5173`

## Features

### 1. Language Selection
- Users can select their preferred language before starting the intake session
- Supports: English, Spanish, French, Chinese, Arabic, Hindi

### 2. Microphone Capture
- Request microphone permission from browser
- Capture audio with echo cancellation, noise suppression, and auto-gain control
- Encode audio and stream to backend over WebRTC

### 3. Real-Time Transcript Display
- Shows live transcript updates as the user speaks
- Auto-scrolls to latest content
- Status indicator (idle, active, completed, error)
- Live pulse animation when conversation is active

### 4. Session Management
- Create session with backend
- Establish WebRTC connection
- Stream conversation to GPT-4o Realtime
- Display extracted symptoms when ready
- End session and reset to start a new one

## Architecture

### State Management
Uses **Zustand** for lightweight, reactive state:
- Session details (ID, language, status)
- Transcript content
- Extracted symptoms
- Error messages

### WebRTC Connection
**WebRTCManager** handles:
- Peer connection setup with STUN/TURN servers
- Microphone capture and stream management
- Data channel for real-time transcript/events
- Connection lifecycle (connect, disconnect)

### API Integration
**IntakeAPIClient** provides:
- Session creation and management
- WebRTC signaling (SDP offer/answer, ICE candidates)
- WebSocket connection for event streaming

## Key Dependencies

- **React 18**: UI framework
- **Zustand**: State management
- **Vite**: Build tool and dev server
- **TypeScript**: Static typing
- **Axios**: HTTP client

## Project Status

### Implemented
- [x] Vite + React + TypeScript scaffolding
- [x] State management (Zustand store)
- [x] API client with axios
- [x] WebRTC connection manager
- [x] Intake form component
- [x] Transcript display component
- [x] Main app layout and flow

### TODO
- [ ] Connect API calls to real backend (create session, signaling)
- [ ] WebRTC data channel implementation
- [ ] Real-time transcript streaming from WebSocket
- [ ] Microphone permission and capture
- [ ] Error handling and recovery
- [ ] Audio encoding/streaming to backend
- [ ] Mobile responsive improvements
- [ ] Accessibility (a11y) improvements
- [ ] Unit and integration tests

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14.1+

Note: WebRTC requires HTTPS in production (HTTP OK for localhost development).

## Notes

- Vite proxy forwards `/api` and `/ws` requests to `http://localhost:8000` in development
- Update `VITE_BACKEND_URL` for production deployments
- WebRTC requires microphone permission from the browser
- Data channel is used for low-latency real-time transcript delivery
