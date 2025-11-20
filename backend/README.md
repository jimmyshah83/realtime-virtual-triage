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
