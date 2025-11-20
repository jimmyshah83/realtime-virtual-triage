# Real-time Virtual Triage Backend

FastAPI-based backend for real-time virtual triage system.

## Setup

1. Copy the sample environment file and add your Azure OpenAI details:

	```bash
	cp .env.example .env
	```

2. Install dependencies:

	```bash
	pip install -e .
	```

3. For development dependencies:

	```bash
	pip install -e ".[dev]"
	```

## Run

```bash
uvicorn app.main:app --reload
```

## Debugging in VS Code

1. Ensure `.env` contains your Azure OpenAI settings as described above.
2. Open the workspace in VS Code and select the "Backend: FastAPI (uvicorn)" configuration from the Run and Debug panel.
3. Press F5 (or click the green run button) to start a debuggable Uvicorn session with auto-reload, using `backend/.env` automatically.
