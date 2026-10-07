# Demo script — AI Software Evolution Platform

Use this for a viva / walkthrough. Prefer a **small public** GitHub repo so analysis and indexing finish during the demo.

## Recommended demo repository

- Primary: `https://github.com/axios/axios` (or another small/medium public repo)
- Avoid: `facebook/react` / `react/react` (~1 GB on GitHub) — too large for local clone/analysis on a demo machine

## Prerequisites (before the audience)

1. MongoDB running locally
2. Git installed and on `PATH` (analysis and indexing run `git clone`)
3. Backend: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
4. Frontend: `npm run dev` in `frontend/`
5. `GEMINI_API_KEY` set in `backend/.env` (architecture generation and AI Copilot answers)
6. Google OAuth client configured (sign-in)

Quick health check: open [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health) — expect MongoDB / OAuth / Gemini configuration flags.

## Demo flow (~8–12 minutes)

### 1. Landing + sign-in (~1 min)

- Open [http://127.0.0.1:5173](http://127.0.0.1:5173)
- Sign in with Google
- Point out: server-side Mongo sessions + HttpOnly cookie (no JWT)

### 2. Connect a repository (~1 min)

- Dashboard → **Analyze a Repository**
- Paste the public GitHub URL
- Project name auto-derives from `owner/repo`
- Submit → workspace opens and analysis starts

### 3. Health report (~2 min)

- Wait for analysis to finish (clone + structural analysis + health)
- Open **Health**
- Show overall score, category breakdown, and that metrics come from real analysis (not fabricated labels)

### 4. Architecture diagram (~2–3 min)

- Open **Architecture** → **Generate**
- Narrate stages: Preparing → Analyzing (if needed) → Generating → Ready
- Interact with the React Flow canvas (pan/zoom)
- Mention: Gemini produces JSON; backend validates against repository evidence; fallback exists if Gemini is unavailable

### 5. AI Copilot (RAG) (~3–4 min)

- The **AI Copilot** panel opens with the workspace; reopen it from the floating button if minimized
- If the code index is still building, wait for auto-index (or use **Refresh Repository**)
- Ask one suggested question, e.g. “Where is authentication implemented?”
- While waiting, explain: embeddings are local; Gemini writes the answer, grounded with **cited source files**
- Expand **Sources** and show file paths / excerpts

### 6. Failure handling (optional, 30–60s)

- Stop the backend briefly and refresh dashboard → show clear “Cannot reach the API” banner + Retry
- Or ask a question before indexing is ready → show “not ready” guidance

## Talking points

| Topic | What to say |
|-------|-------------|
| Data flow | GitHub → shallow clone → analysis → health / architecture / RAG index |
| Storage | MongoDB = app data; ChromaDB = embeddings with `project_id` filter |
| AI split | Gemini = architecture + AI Copilot answers; sentence-transformers = embeddings |
| Safety | Ownership checks on every project route; no fabricated metrics/evidence |

## If something is slow

| Step | Typical wait | What to say |
|------|--------------|-------------|
| Analyze | tens of seconds | Shallow clone + AST / filesystem pass |
| Architecture | tens of seconds | Gemini + validation |
| RAG index | ~35–45s (medium repo) | Local embedding batch |
| AI Copilot answer | depends on network / Gemini latency | Gemini generation over retrieved context |

Do **not** switch models mid-demo unless you already benchmarked a faster one.

## After demo cleanup

- Delete the demo project from the dashboard if desired
- Leave services running only if you still need them
