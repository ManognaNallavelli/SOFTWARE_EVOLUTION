"""Prompts for repository-aware RAG chat."""

from __future__ import annotations

from typing import Any

MAX_CONTEXT_CHARS = 500
# Chunks fetched to back an analysis finding keep their full stored text so the
# referenced line stays visible.
MAX_SUPPORTING_CONTEXT_CHARS = 1600

NO_EVIDENCE_REPLY = "No evidence was found in the indexed repository."

ANALYSIS_RULES = """Rules for repository analysis findings:
- Health scores, categories, issues, recommendations, strengths, architecture components and relationships,
  routes, imports, statistics and detected technologies come ONLY from the findings below. Do not compute new
  scores, add findings, or claim an analysis was run when an availability note says it was not.
- Cite every finding you rely on by its id in square brackets, for example [A2]. Cite code snippets by file path.
- Only use line numbers that appear in a finding's "Files:" list or in a code context header. If a file is listed
  without a line number, cite the file without one.
- When asked why a finding exists, explain it with the finding's stated summary/evidence and any code context
  marked as supporting it. Say when a score is a structural heuristic (for example test-file ratios, not runtime
  coverage).
- If an availability note says results are missing, failed, in progress or outdated, say so plainly."""


def build_rag_prompt(
    *,
    question: str,
    contexts: list[dict[str, Any]],
    stack_metadata: str | None = None,
    analysis_block: str | None = None,
    workspace_context: str | None = None,
) -> str:
    has_stack_meta = bool(stack_metadata and stack_metadata.strip())
    has_analysis = bool(analysis_block and analysis_block.strip())
    if not contexts and not has_stack_meta and not has_analysis:
        return (
            "You are a repository assistant. There is NO retrieved context for this question.\n"
            f'Reply with exactly: {NO_EVIDENCE_REPLY}\n'
            f"Question: {question}\n"
        )

    blocks: list[str] = []
    for i, row in enumerate(contexts, start=1):
        meta = row.get("metadata") or {}
        file_path = meta.get("file_path") or "unknown"
        symbol = meta.get("symbol") or ""
        start = meta.get("start_line")
        end = meta.get("end_line")
        loc = f":{start}-{end}" if start is not None and end is not None else ""
        header = f"[{i}] {file_path}{loc}"
        if symbol:
            header += f" ({symbol})"
        supports = row.get("supports") or []
        if supports:
            header += " — supports " + ", ".join(supports)
        limit = MAX_SUPPORTING_CONTEXT_CHARS if supports else MAX_CONTEXT_CHARS
        body = (row.get("document") or "").strip()
        if len(body) > limit:
            body = body[:limit] + "\n..."
        blocks.append(f"{header}\n{body}")

    context_blob = "\n\n---\n\n".join(blocks) if blocks else "(No Chroma snippets retrieved.)"
    stack_section = ""
    if has_stack_meta:
        stack_section = f"""
Repository analysis / detected technology metadata (authoritative for stack questions; do not invent beyond this + file context):
{stack_metadata.strip()}
"""
    analysis_section = ""
    if has_analysis:
        analysis_section = f"""
{ANALYSIS_RULES}

Repository analysis findings (stored results of this project's analysis):
{analysis_block.strip()}
"""
    workspace_section = ""
    if workspace_context and workspace_context.strip():
        workspace_section = f"""
Workspace context:
{workspace_context.strip()}
"""

    return f"""Answer ONLY from the repository context and the repository analysis metadata below. Do not invent files, symbols, line numbers, or technologies.
Be concise. Cite file paths from the context when helpful.

Question-type guidance:
- Project purpose / overview: prefer root README and root package metadata over nested docs packages; cite those files.
  If README or package.json context is present, you MUST answer from it (for example description / tagline) and cite the file.
  Do not reply with no-evidence when those files are in context.
- Implementation / architecture: prefer source, config, service, adapter, and API files. If context shows module/adapter structure, summarize that structure even when the repo is a library rather than a traditional server backend. For Axios-like libraries, describe core request flow and adapters from the retrieved files.
- "Where is X used?" questions: cover both the definition of X and files that import/call/reference X when present in context.
- Technology stack / languages / frameworks / libraries questions:
  Prefer package/dependency manifests, lockfiles, tsconfig, build configs, and the detected technology metadata.
  Answer in clear groups when evidence supports them, for example:
    Languages: ...
    Runtime: ...
    Libraries/Frameworks: ...
    Build/Tooling: ...
  Only list technologies supported by metadata or retrieved files. Omit empty groups. Do not invent technologies.
  If metadata or manifests are present, you MUST provide a stack answer (not "{NO_EVIDENCE_REPLY}").

Technology / dependency presence questions:
- If the question asks whether a specific technology/library (for example Redis, Kafka, MongoDB) is used,
  and the context does not mention it, reply exactly:
  "No evidence of <technology> was found in the indexed repository."
- Do not say context is insufficient when the indexed snippets are present but simply lack that technology.

If neither retrieved context nor analysis metadata contains evidence that answers the question, reply exactly:
"{NO_EVIDENCE_REPLY}"
Do not say only that "context may be insufficient."
{stack_section}{workspace_section}{analysis_section}
Context:
{context_blob}

Question: {question}
Answer:"""
