"""Architecture generation helpers (Phase 3).

Modules:
- prompt_builder: compact brief from RepositoryAnalysis + Gemini prompt
- gemini_client: REST call to Gemini
- validator: drop unsupported invented edges/nodes
- deterministic: evidence-only fallback without Gemini
"""
