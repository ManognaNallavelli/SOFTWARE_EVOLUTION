# API Plan

Base URL (local): `http://127.0.0.1:8000`

## Implemented

### Phase 0

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | API + MongoDB + OAuth + Gemini config status |

### Phase 1

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/auth/google/login` | No | Start Google OAuth |
| GET | `/api/auth/google/callback` | No | OAuth callback; sets session cookie |
| GET | `/api/auth/me` | Cookie optional | Current session user |
| POST | `/api/auth/logout` | Cookie optional | Destroy session + clear cookie |
| GET | `/api/projects` | Required | List current user's projects |
| POST | `/api/projects` | Required | Validate GitHub repo + create project |
| GET | `/api/projects/{id}` | Required + owner | Get project |
| DELETE | `/api/projects/{id}` | Required + owner | Delete project |

### Phase 2

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/projects/{id}/analyze` | Required + owner | Clone + structural analysis + health report |
| GET | `/api/projects/{id}/analysis` | Required + owner | Fetch stored analysis + health report |
| GET | `/api/projects/{id}/health` | Required + owner | Same document (health-focused access) |

### Phase 3

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/projects/{id}/architecture/generate` | Required + owner | Build architecture from stored analysis (Gemini if configured; `?deterministic=true` forces evidence-only) |
| GET | `/api/projects/{id}/architecture` | Required + owner | Fetch stored architecture graph |

### Phase 4

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/projects/{id}/rag/index` | Required + owner | Clone + chunk + embed into Chroma (project_id metadata); replaces prior chunks |
| GET | `/api/projects/{id}/rag/status` | Required + owner | Index status / chunk counts from MongoDB |
| POST | `/api/projects/{id}/chat` | Required + owner | AI Copilot answer via Gemini, grounded in stored analysis and project-filtered retrieval (requires `GEMINI_API_KEY`) |

Sessions use an HttpOnly cookie (`ase_session` by default). No JWT.
