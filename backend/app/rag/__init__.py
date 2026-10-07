"""RAG indexing and retrieval helpers (Phase 4).

Modules:
- file_filter: which files to index
- chunker: code-aware chunks with metadata
- embedder: sentence-transformers embeddings
- chroma_store: persistent Chroma vectors (project_id filtered)
- retriever: project-scoped similarity search
- gemini_chat_client: Gemini answer generation (primary + fallback)
- prompts: grounded chat prompts
"""
