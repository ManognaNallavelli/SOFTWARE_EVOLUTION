# Development Phases

Vertical slices: backend → API → frontend → verify → next feature.

| Phase | Focus | Status |
|-------|--------|--------|
| **0** | Skeleton: frontend/backend/docs, config, `GET /api/health` | Complete |
| **1** | Google OAuth, users, project create/list shell | Complete |
| **2** | Clone, structural analysis, health metrics + UI | Complete |
| **3** | Gemini architecture generation + React Flow | Complete |
| **4** | RAG indexing + Gemini AI Copilot | Complete |
| **5** | Polish, errors, demo readiness | Complete |

## Phase 0 exit criteria

- Both apps start locally
- `GET /api/health` returns a structured OK response
- Frontend loads without TypeScript/build errors
- Env example documents future services without real secrets

## Phase 3 exit criteria

- Compact architecture brief built from stored `RepositoryAnalysis`
- Gemini (or evidence-only deterministic fallback) produces `ArchitectureGraph`
- Backend validates nodes/edges against analysis evidence
- Graph stored in MongoDB `architectures` (independent of React Flow)
- `POST /api/projects/{id}/architecture/generate` and `GET .../architecture`
- Frontend interactive diagram via React Flow adapter

## Phase 5 exit criteria

- Network / API failures map to actionable UI messages with dismiss + retry where useful
- Long chat waits show elapsed feedback so demos do not look “stuck”
- Demo script documents prerequisites, walkthrough, and failure talking points
- No rebuild of Phases 0–4; existing auth / analysis / architecture / RAG preserved
