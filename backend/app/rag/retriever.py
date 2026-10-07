"""Retrieve project-filtered chunks for chat with intent-aware ranking."""

from __future__ import annotations

import re
from typing import Any, Literal

from app.config import Settings
from app.rag.chroma_store import get_project_chunks_for_files, query_project_chunks
from app.rag.embedder import embed_texts

QuestionIntent = Literal["overview", "usage", "stack", "implementation"]

# Path fragments that usually hurt implementation Q&A when over-retrieved.
_WEAK_PATH_MARKERS = (
    "/.github/",
    "/workflows/",
    "/workflow/",
    "/docs/",
    "/documentation/",
    "/changelog",
    "/contributing",
    "/license",
    "readme",
    ".md",
    ".rst",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock",
    "poetry.lock",
    "generated",
    "/ci/",
    "/.circleci/",
    "/.gitlab-ci",
)

# Prefer application / API / client / config / dependency evidence.
_STRONG_PATH_MARKERS = (
    "/src/",
    "/lib/",
    "/app/",
    "/api/",
    "/backend/",
    "/frontend/",
    "/services/",
    "/service/",
    "/client/",
    "/clients/",
    "/adapters/",
    "/adapter/",
    "/routes/",
    "/routers/",
    "/auth",
    "/security",
    "/db/",
    "/database/",
    "/models/",
    "/crud/",
    "/repos/",
    "/repository/",
    "/deps/",
    "/core/",
    "/config/",
    "/configs/",
    "/schemas/",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "dockerfile",
    "docker-compose",
    "tsconfig",
    "vite.config",
    "settings.py",
    "main.py",
    "main.ts",
    "main.tsx",
)

_OVERVIEW_PATH_MARKERS = (
    "readme",
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "composer.json",
    "cargo.toml",
    "go.mod",
    "/index.js",
    "/index.ts",
    "/index.mjs",
    "/main.py",
    "/main.ts",
    "/main.js",
    "/app.py",
    "/app.ts",
    "/lib/axios.js",
    "/lib/axios.ts",
)

_STACK_PATH_MARKERS = (
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock",
    "pyproject.toml",
    "requirements.txt",
    "pipfile",
    "poetry.lock",
    "go.mod",
    "cargo.toml",
    "pom.xml",
    "build.gradle",
    "gemfile",
    "composer.json",
    "tsconfig",
    "jsconfig",
    "webpack",
    "rollup",
    "vite.config",
    "babel.config",
    "dockerfile",
    "docker-compose",
    ".nvmrc",
    "runtime.txt",
)

_SOURCE_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".rb", ".php", ".cs")
_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "and",
    "or",
    "this",
    "that",
    "it",
    "as",
    "by",
    "from",
    "at",
    "how",
    "what",
    "where",
    "which",
    "who",
    "when",
    "why",
    "does",
    "do",
    "did",
    "can",
    "could",
    "should",
    "would",
    "any",
    "there",
    "project",
    "repository",
    "codebase",
    "code",
    "file",
    "files",
    "used",
    "use",
    "using",
    "include",
    "includes",
    "have",
    "has",
    "please",
    "explain",
    "tell",
    "me",
    "about",
    "they",
    "them",
    "their",
    "purpose",
    "overview",
    "architecture",
    "backend",
    "frontend",
    "implemented",
    "implement",
    "implementation",
    "module",
    "modules",
    "class",
    "classes",
    "function",
    "functions",
}

_OVERVIEW_RE = re.compile(
    r"(?:"
    r"\bpurpose\b|"
    r"\boverview\b|"
    r"\bhigh[- ]level\b|"
    r"\bwhat\s+is\s+(?:the\s+)?purpose\b|"
    r"\bwhat\s+is\s+this\s+(?:project|repo|repository|app|library|package)\b|"
    r"\bwhat\s+does\s+this\s+(?:project|repo|repository|app|library|package)\s+do\b|"
    r"\bdescribe\s+(?:this\s+)?(?:project|repo|repository)\b|"
    r"\bproject\s+description\b|"
    r"\babout\s+this\s+(?:project|repo|repository)\b"
    r")",
    re.IGNORECASE,
)

_USAGE_RE = re.compile(
    r"(?:"
    r"\bwhere\s+(?:is|are|do|does)\b.+\b(?:used|imported|referenced|called|invoked)\b|"
    r"\bwhere\s+(?:is|are)\b.+\b(?:used|imported|referenced)\b|"
    r"\b(?:used|imported|referenced)\s+by\b|"
    r"\bwho\s+(?:uses|calls|imports)\b|"
    r"\band\s+where\s+(?:is|are)\s+(?:it|they|this|these)\s+used\b|"
    r"\bwhere\s+(?:is|are)\s+they\s+used\b|"
    r"\busages?\s+of\b|"
    r"\bimport(?:ed|s)?\s+(?:from|of)\b"
    r")",
    re.IGNORECASE,
)

_STACK_RE = re.compile(
    r"(?:"
    r"\btech(?:nology|nologies)?\s+stack\b|"
    r"\bstack\s+(?:does|is|used)\b|"
    r"\bwhat\s+technologies\b|"
    r"\bwhich\s+technologies\b|"
    r"\btechnologies\s+(?:are|were)\s+used\b|"
    r"\bwhat\s+tech\b|"
    r"\bwhich\s+frameworks?\b|"
    r"\bwhat\s+frameworks?\b|"
    r"\bframeworks?\s+and\s+libraries\b|"
    r"\blibraries?\s+(?:are|were)\s+used\b|"
    r"\bwhat\s+libraries\b|"
    r"\bwhich\s+libraries\b|"
    r"\bwhat\s+languages?\b|"
    r"\bwhich\s+languages?\b|"
    r"\blanguages?\s+(?:are|were)\s+used\b|"
    r"\bdependencies\s+(?:are|were)\s+used\b|"
    r"\bwhat\s+dependencies\b|"
    r"\bdetected\s+stack\b"
    r")",
    re.IGNORECASE,
)


def _normalize_path(path: str) -> str:
    return "/" + path.replace("\\", "/").lower().lstrip("/")


def classify_question(question: str) -> QuestionIntent:
    q = question.strip()
    if _USAGE_RE.search(q):
        return "usage"
    if _STACK_RE.search(q):
        return "stack"
    if _OVERVIEW_RE.search(q):
        return "overview"
    return "implementation"


def extract_focus_symbols(question: str) -> list[str]:
    """Extract likely symbol/module names for definition + usage retrieval."""
    found: list[str] = []
    for match in re.finditer(r"`([^`]+)`", question):
        token = match.group(1).strip()
        if token:
            found.append(token.split(".")[-1])
    # PascalCase / CamelCase identifiers (AxiosHeaders, InterceptorManager, ...)
    for match in re.finditer(r"\b([A-Z][a-zA-Z0-9]{2,})\b", question):
        found.append(match.group(1))
    # snake_case / dotted module-ish tokens
    for match in re.finditer(r"\b([a-z][a-z0-9_]{2,}(?:/[a-z0-9_]+)?)\b", question):
        token = match.group(1)
        if token not in _STOPWORDS:
            found.append(token)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in found:
        key = item.lower()
        if key in seen or key in _STOPWORDS or len(item) < 2:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:8]


def path_relevance_bonus(file_path: str, *, intent: QuestionIntent = "implementation") -> float:
    """Heuristic prior conditioned on question intent."""
    path = _normalize_path(file_path)
    bonus = 0.0

    if intent == "overview":
        depth = path.strip("/").count("/")
        for marker in _OVERVIEW_PATH_MARKERS:
            if marker in path:
                bonus += 0.22
        # Prefer repository-root README / package metadata over nested docs copies.
        if path.endswith("readme.md") or path.rstrip("/").endswith("/readme"):
            bonus += 0.36 if depth == 0 else 0.10
        if path.endswith("package.json") or path.endswith("pyproject.toml"):
            if "/docs/" in path or "/documentation/" in path:
                bonus -= 0.08  # nested docs metadata is secondary
            else:
                bonus += 0.30 if depth <= 1 else 0.10
        if ("/docs/" in path or "/documentation/" in path) and path.endswith((".md", ".rst")):
            bonus += 0.12
        elif path.endswith((".md", ".rst")):
            bonus += 0.08 if depth <= 1 else 0.02
        if "/.github/" in path or "/workflows/" in path or "/test" in path or "/__tests__/" in path:
            bonus -= 0.30
        if path.endswith(_SOURCE_EXTS) and bonus < 0.2:
            # Keep a little source evidence, but do not let random impl dominate.
            bonus += 0.04
        return bonus

    if intent == "usage":
        for marker in _STRONG_PATH_MARKERS:
            if marker in path:
                bonus += 0.14
        if path.endswith(_SOURCE_EXTS):
            bonus += 0.16
        if path.endswith((".md", ".rst")) or "readme" in path:
            bonus -= 0.12
        if "/.github/" in path or "/workflows/" in path:
            bonus -= 0.30
        return bonus

    if intent == "stack":
        depth = path.strip("/").count("/")
        for marker in _STACK_PATH_MARKERS:
            if marker in path:
                bonus += 0.32
        if path.endswith("package.json") or path.endswith("pyproject.toml"):
            bonus += 0.28 if depth <= 1 else 0.08
            if "/docs/" in path:
                bonus -= 0.12
        if path.endswith(("requirements.txt", "go.mod", "cargo.toml", "pom.xml")):
            bonus += 0.22
        if any(name in path for name in ("webpack", "rollup", "vite.config", "tsconfig")):
            bonus += 0.18
        if path.endswith((".md", ".rst")) and "readme" not in path:
            bonus -= 0.15
        if "/.github/" in path or "/workflows/" in path:
            bonus -= 0.25
        if path.endswith(_SOURCE_EXTS):
            bonus += 0.06
        return bonus

    # implementation (default)
    for marker in _WEAK_PATH_MARKERS:
        if marker in path:
            bonus -= 0.28
    for marker in _STRONG_PATH_MARKERS:
        if marker in path:
            bonus += 0.16
    if path.endswith(_SOURCE_EXTS):
        bonus += 0.14
    if path.endswith((".yml", ".yaml")) and ("/.github/" in path or "/workflows/" in path):
        bonus -= 0.35
    if path.endswith(".md") or path.endswith(".rst"):
        bonus -= 0.22
    return bonus


def _question_tokens(question: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_+.-]{1,}", question.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


def overview_content_bonus(*, file_path: str, document: str, start_line: Any = None) -> float:
    """Prefer early README/package description snippets for overview questions."""
    path = _normalize_path(file_path)
    doc = (document or "").lower()
    bonus = 0.0
    try:
        if start_line is not None and int(start_line) <= 60:
            bonus += 0.12
    except (TypeError, ValueError):
        pass
    if any(
        cue in doc
        for cue in (
            "description",
            "promise based",
            "http client",
            "what is",
            "overview",
            "purpose",
            '"name"',
        )
    ):
        bonus += 0.14
    if path.endswith("readme.md") and "contributing" in doc and "http client" not in doc:
        bonus -= 0.10
    return bonus


def keyword_overlap_bonus(question: str, *, file_path: str, document: str) -> float:
    tokens = _question_tokens(question)
    if not tokens:
        return 0.0
    haystack = f"{file_path}\n{document}".lower()
    hits = sum(1 for token in tokens if token in haystack)
    if hits == 0:
        return -0.05
    return min(0.35, 0.08 * hits)


def usage_evidence_bonus(symbols: list[str], *, file_path: str, document: str) -> float:
    if not symbols:
        return 0.0
    path = file_path.lower()
    text = document
    text_l = text.lower()
    bonus = 0.0
    for symbol in symbols:
        sym = symbol.strip()
        if len(sym) < 2:
            continue
        sym_l = sym.lower()
        if sym_l in path:
            bonus += 0.14
        # Import / require / export style references
        if re.search(
            rf"(?i)\b(?:import|from|require|export|using)\b[^\n]{{0,80}}\b{re.escape(sym)}\b",
            text,
        ):
            bonus += 0.22
        elif re.search(rf"(?i)\b{re.escape(sym)}\b", text):
            bonus += 0.10
        # Definition-ish cues in the same chunk
        if re.search(
            rf"(?i)\b(?:class|function|const|let|var|type|interface|def|export\s+(?:default\s+)?(?:class|function|const))\s+{re.escape(sym)}\b",
            text,
        ):
            bonus += 0.18
        if sym_l in text_l and ("extends" in text_l or "prototype" in text_l):
            bonus += 0.04
    return min(0.65, bonus)


def _merge_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the best-scoring row per chunk id / path+lines fingerprint."""
    best: dict[str, dict[str, Any]] = {}
    for group in groups:
        for row in group:
            meta = row.get("metadata") or {}
            key = str(
                row.get("id")
                or f"{meta.get('file_path')}:{meta.get('start_line')}-{meta.get('end_line')}:{hash(row.get('document') or '')}"
            )
            prev = best.get(key)
            if prev is None or float(row.get("score") or 0.0) > float(prev.get("score") or 0.0):
                best[key] = row
    return list(best.values())


def rerank_contexts(
    question: str,
    rows: list[dict[str, Any]],
    *,
    top_k: int,
    intent: QuestionIntent | None = None,
) -> list[dict[str, Any]]:
    intent = intent or classify_question(question)
    symbols = extract_focus_symbols(question) if intent == "usage" else []
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        meta = row.get("metadata") or {}
        file_path = str(meta.get("file_path") or "")
        document = str(row.get("document") or "")
        base = float(row.get("score") or 0.0)
        adjusted = (
            base
            + path_relevance_bonus(file_path, intent=intent)
            + keyword_overlap_bonus(question, file_path=file_path, document=document)
        )
        if intent == "usage":
            adjusted += usage_evidence_bonus(symbols, file_path=file_path, document=document)
        if intent == "overview":
            adjusted += overview_content_bonus(
                file_path=file_path,
                document=document,
                start_line=meta.get("start_line"),
            )
        enriched = dict(row)
        enriched["score"] = max(0.0, min(1.0, adjusted))
        enriched["rank_score"] = adjusted
        scored.append((adjusted, enriched))
    scored.sort(key=lambda item: item[0], reverse=True)

    # Prefer diverse files so one noisy file cannot dominate the context window.
    selected: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    max_per_file = 2 if intent in {"usage", "implementation"} else 2
    for _, row in scored:
        meta = row.get("metadata") or {}
        file_path = str(meta.get("file_path") or "")
        key = file_path.lower()
        if key in seen_files and len(selected) < top_k:
            same = sum(
                1
                for item in selected
                if str((item.get("metadata") or {}).get("file_path") or "").lower() == key
            )
            if same >= max_per_file:
                continue
            # For overview, allow a second README/package chunk; otherwise require some prior.
            if intent != "overview" and path_relevance_bonus(file_path, intent=intent) < 0.05:
                continue
        selected.append(row)
        seen_files.add(key)
        if len(selected) >= top_k:
            break
    return selected


def detect_presence_technology(question: str) -> str | None:
    """Extract a technology name from 'is X used / does this use X' style questions."""
    q = question.strip()
    patterns = (
        r"\bis\s+([A-Za-z][\w.+-]{1,40})\s+(?:used|present|included|configured)\b",
        r"\bdoes\s+(?:this|the)\s+(?:project|repo|repository|codebase)?\s*use\s+([A-Za-z][\w.+-]{1,40})\b",
        r"\bdo\s+(?:we|you|they)\s+use\s+([A-Za-z][\w.+-]{1,40})\b",
        r"\bany\s+(?:evidence|sign|mention)\s+of\s+([A-Za-z][\w.+-]{1,40})\b",
        r"\b(?:uses?|using)\s+([A-Za-z][\w.+-]{1,40})\??\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, q, flags=re.IGNORECASE)
        if match:
            tech = match.group(1).strip("?.!")
            if tech.lower() not in _STOPWORDS and len(tech) >= 2:
                return tech
    return None


def contexts_mention_technology(contexts: list[dict[str, Any]], technology: str) -> bool:
    needle = technology.lower()
    aliases = {needle}
    if needle == "postgres":
        aliases.update({"postgresql", "psycopg"})
    if needle == "postgresql":
        aliases.update({"postgres", "psycopg"})
    if needle == "js":
        aliases.add("javascript")
    for row in contexts:
        meta = row.get("metadata") or {}
        haystack = f"{meta.get('file_path') or ''}\n{row.get('document') or ''}".lower()
        if any(alias in haystack for alias in aliases):
            return True
    return False


def _embed_query(settings: Settings, text: str) -> list[float] | None:
    vectors = embed_texts([text], model_name=settings.embedding_model_name)
    if not vectors:
        return None
    return vectors[0]


def retrieve_context(
    settings: Settings,
    *,
    project_id: str,
    question: str,
    top_k: int = 6,
) -> list[dict[str, Any]]:
    intent = classify_question(question)
    primary = _embed_query(settings, question)
    if primary is None:
        return []

    # Over-fetch, then re-rank toward intent-appropriate evidence.
    candidate_k = max(top_k * 5, 20)
    raw = query_project_chunks(
        settings,
        project_id=project_id,
        query_embedding=primary,
        top_k=candidate_k,
    )

    if intent == "overview":
        expanded = _embed_query(
            settings,
            f"{question} README.md package.json pyproject.toml project description purpose overview",
        )
        if expanded is not None:
            raw = _merge_rows(
                raw,
                query_project_chunks(
                    settings,
                    project_id=project_id,
                    query_embedding=expanded,
                    top_k=candidate_k,
                ),
            )
    elif intent == "stack":
        for aux in (
            f"{question} package.json dependencies devDependencies engines",
            "pyproject.toml requirements.txt go.mod cargo.toml tsconfig.json webpack rollup vite",
            "framework library runtime language build tooling configuration",
        ):
            vec = _embed_query(settings, aux)
            if vec is None:
                continue
            raw = _merge_rows(
                raw,
                query_project_chunks(
                    settings,
                    project_id=project_id,
                    query_embedding=vec,
                    top_k=candidate_k,
                ),
            )
    elif intent == "usage":
        symbols = extract_focus_symbols(question)
        if symbols:
            joined = " ".join(symbols)
            aux_queries = [
                f"{joined} class function type interface export definition declaration",
                f"{joined} import from require used by reference usage call",
            ]
            for sym in symbols[:4]:
                aux_queries.append(f"{sym} class export function type definition")
                aux_queries.append(f"import {sym} from require {sym}")
            for aux in aux_queries:
                vec = _embed_query(settings, aux)
                if vec is None:
                    continue
                raw = _merge_rows(
                    raw,
                    query_project_chunks(
                        settings,
                        project_id=project_id,
                        query_embedding=vec,
                        top_k=candidate_k,
                    ),
                )
    elif re.search(r"\barchitecture\b|\badapters?\b|\bbackend\b", question, flags=re.IGNORECASE):
        expanded = _embed_query(
            settings,
            f"{question} architecture structure core modules adapters api request http client services",
        )
        if expanded is not None:
            raw = _merge_rows(
                raw,
                query_project_chunks(
                    settings,
                    project_id=project_id,
                    query_embedding=expanded,
                    top_k=candidate_k,
                ),
            )

    return_k = top_k + 1 if intent in {"usage", "stack"} else top_k
    return rerank_contexts(question, raw, top_k=return_k, intent=intent)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def select_supporting_chunks(
    rows: list[dict[str, Any]],
    refs: list[dict[str, Any]],
    *,
    question: str,
    max_chunks: int = 3,
) -> list[dict[str, Any]]:
    """Pick indexed chunks that back analysis findings.

    A ref with a stored line selects the smallest chunk whose metadata range covers
    that line; a ref without a line selects the file chunk with the best keyword
    overlap. Selected rows carry ``supports`` (finding ids); their line metadata is
    the chunk's own stored range.
    """
    by_file: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        path = str((row.get("metadata") or {}).get("file_path") or "")
        by_file.setdefault(path, []).append(row)

    chosen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for ref in refs:
        candidates = by_file.get(str(ref.get("file_path") or ""), [])
        if not candidates:
            continue
        line = _as_int(ref.get("line"))
        pick: dict[str, Any] | None = None
        if line is not None:
            covering = []
            for row in candidates:
                meta = row.get("metadata") or {}
                start, end = _as_int(meta.get("start_line")), _as_int(meta.get("end_line"))
                if start is not None and end is not None and start <= line <= end:
                    covering.append((end - start, start, row))
            if covering:
                covering.sort(key=lambda item: (item[0], item[1]))
                pick = covering[0][2]
        if pick is None:
            pick = max(
                candidates,
                key=lambda row: (
                    keyword_overlap_bonus(
                        question,
                        file_path=str((row.get("metadata") or {}).get("file_path") or ""),
                        document=str(row.get("document") or ""),
                    ),
                    -(_as_int((row.get("metadata") or {}).get("start_line")) or 0),
                ),
            )
        key = str(pick.get("id") or id(pick))
        finding_id = ref.get("finding_id")
        if key not in chosen:
            if len(order) >= max_chunks:
                continue
            enriched = dict(pick)
            enriched["supports"] = []
            chosen[key] = enriched
            order.append(key)
        if finding_id and finding_id not in chosen[key]["supports"]:
            chosen[key]["supports"].append(finding_id)
    return [chosen[key] for key in order]


def retrieve_supporting_chunks(
    settings: Settings,
    *,
    project_id: str,
    refs: list[dict[str, Any]],
    question: str,
    max_chunks: int = 3,
) -> list[dict[str, Any]]:
    paths = [str(ref.get("file_path") or "") for ref in refs]
    rows = get_project_chunks_for_files(settings, project_id=project_id, file_paths=paths)
    return select_supporting_chunks(rows, refs, question=question, max_chunks=max_chunks)
