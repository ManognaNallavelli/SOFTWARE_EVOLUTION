# AI Software Evolution Platform

End-to-end web platform for connecting a public GitHub repository and obtaining:

1. Repository health / statistical analysis
2. AI-assisted architecture generation and interactive visualization
3. AI Copilot — a repository-aware assistant using RAG

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | React, Vite, TypeScript, React Router |
| Backend | Python, FastAPI, Pydantic |
| Data | MongoDB, ChromaDB |
| AI | Gemini (architecture + AI Copilot answers), sentence-transformers (local embeddings) |
| Auth | Google OAuth + MongoDB server-side sessions (HttpOnly cookie) |

## Project layout

```text
PROJECT/
├── frontend/     # React + Vite + TypeScript
├── backend/      # FastAPI application
├── docs/         # Architecture and phase docs
├── .gitignore
└── README.md
```

## Prerequisites

- Node.js 20+
- Python 3.11+
- MongoDB running locally
- Git on `PATH` (repository analysis and indexing use `git clone`)
- Google OAuth client ID/secret for sign-in
- Gemini API key ([Google AI Studio](https://aistudio.google.com/apikey)) for architecture generation and the AI Copilot

## Quick start

### Backend

```bash
cd backend
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Edit `backend/.env` (copied from `backend/.env.example`) before starting:

| Variable | Purpose |
|----------|---------|
| `SESSION_SECRET` | Long random string |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google sign-in |
| `GEMINI_API_KEY` | Required for the AI Copilot; without it architecture uses the deterministic fallback |
| `GEMINI_MODEL`, `GEMINI_ARCHITECTURE_FALLBACK_MODEL` | Architecture models (defaults in `.env.example`) |
| `GEMINI_CHAT_MODEL`, `GEMINI_CHAT_FALLBACK_MODEL` | AI Copilot models (defaults in `.env.example`) |
| `MONGODB_URI`, `MONGODB_DB` | MongoDB connection |
| `CHROMA_PERSIST_DIR`, `REPO_CLONE_DIR` | Leave empty to use the OS temp folder (recommended on OneDrive) |

Never commit or share the real `.env` files.

Health check: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

### Frontend

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

`VITE_API_BASE_URL` in `frontend/.env` must point at the backend (default `http://127.0.0.1:8000`).

App: [http://127.0.0.1:5173](http://127.0.0.1:5173)

### Google OAuth setup

1. Create an OAuth client in Google Cloud Console (Web application).
2. Authorized redirect URI: `http://127.0.0.1:8000/api/auth/google/callback`
3. Authorized JavaScript origins: `http://127.0.0.1:5173` and `http://127.0.0.1:8000`
4. Put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `backend/.env`.

## Documentation

- [Architecture](docs/architecture.md)
- [Analysis model](docs/analysis-model.md)
- [API plan](docs/api.md)
- [Development phases](docs/phases.md)
- [Demo script](docs/demo.md)
- [Test cases](docs/test-cases.md)

## Current status

**Phase 5 — polish / demo readiness** is complete.

Available now: Google OAuth, projects, clone/analysis, health report, architecture diagrams, Chroma indexing, the Gemini-based AI Copilot with cited source evidence, clearer error/loading UX, and a demo script.
