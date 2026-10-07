# Architecture

## Overview

Single FastAPI backend and a React (Vite + TypeScript) frontend. The frontend talks only to FastAPI over REST. MongoDB stores application data; ChromaDB stores repository embeddings. Gemini generates architecture JSON and writes AI Copilot answers from retrieved repository context.

## High-level flow

```text
GitHub Repository
  → Ingestion / shallow clone
  → Structural analysis (canonical RepositoryAnalysis)
      → Health metrics → MongoDB
      → Architecture prep → Gemini → validated ArchitectureGraph → React Flow
      → Chunking → embeddings → ChromaDB → project-filtered retrieval → Gemini (AI Copilot)
```

## Responsibility split

| Concern | System |
|---------|--------|
| Users, sessions, projects, analysis, health, architecture JSON | MongoDB |
| Repository chunk embeddings + metadata | ChromaDB |
| Architecture interpretation | Gemini API |
| AI Copilot answer generation | Gemini API |
| Embeddings | sentence-transformers (local) |

## MongoDB collections (app data)

| Collection | Role |
|------------|------|
| `users`, `sessions`, `oauth_states` | Auth |
| `projects` | Connected repositories |
| `repository_analyses` | Structural analysis + health_report |
| `architectures` | Validated ArchitectureGraph (unique per `project_id`) |
| `rag_index_status` | RAG indexing status / chunk counts (vectors live in Chroma) |

## Authentication (Phase 1)

- Google OAuth 2.0
- Server-side sessions stored in MongoDB (`sessions` collection)
- Session id delivered as HttpOnly cookie (`SameSite=Lax`; `Secure` when configured)
- Identity keyed by Google `sub`
- Project routes require authenticated owner checks

## Backend modules (planned)

- `api/` — HTTP routes and auth dependencies
- `schemas/` — request/response models
- `models/` — Mongo document helpers
- `db/` — MongoDB and Chroma clients
- `services/` — business orchestration
- `analyzers/` — deterministic repository analysis
- `architecture/` — Gemini client, prompts, validation
- `rag/` — chunking, embed, retrieve, Gemini chat client
- `utils/` — shared helpers

## Principles

- No microservices, Redis, Celery, or Kafka unless a real need appears
- No fabricated metrics or architecture
- Ownership checks on every project-scoped operation (Phase 1+)
