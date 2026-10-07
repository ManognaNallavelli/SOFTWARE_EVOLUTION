"""Select stored repository-analysis findings that are relevant to a chat question.

Reads only what analysis / health / architecture generation already persisted
(``repository_analyses``, ``architectures``, ``projects``). Nothing here re-runs an
analysis. File and line references are copied from stored fields; a reference
without a stored line is emitted without one.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.schemas.analysis import AnalysisImport, RepositoryAnalysisPayload
from app.schemas.architecture import ArchitectureEdge, ArchitectureGraph, ArchitectureNode
from app.schemas.health_report import HealthReport
from app.services.analysis_service import INTEGRATION_HINTS
from app.services.health_engine import CATEGORY_WEIGHTS

logger = logging.getLogger(__name__)

IN_PROGRESS_STATUSES = {"validating", "cloning", "analyzing"}

MAX_FACTS = 32
MAX_DETAIL_CHARS = 700
MAX_ISSUES = 10
MAX_RECOMMENDATIONS = 8
MAX_NODES = 6
MAX_EDGES = 12
MAX_ROUTES = 15
MAX_IMPORT_REFS = 15
MAX_SYMBOL_FACTS = 6

# Topics that are inherently about code, so semantic code retrieval stays useful.
CODE_TOPICS = {"architecture", "dependencies", "stack", "symbols"}
# Fact kinds whose file references are worth fetching source code for.
SUPPORTABLE_KINDS = {
    "file",
    "health_issue",
    "architecture_node",
    "architecture_edge",
    "route",
    "import",
    "symbol",
    "integration",
}

_TOPIC_PATTERNS: dict[str, re.Pattern[str]] = {
    "health": re.compile(r"\bhealth(?:y|iness)?\b|\bscor(?:e|es|ed|ing)\b|\bgrade\b|\brating\b", re.I),
    "issues": re.compile(
        r"\bissues?\b|\bproblems?\b|\bfindings?\b|\bweakness(?:es)?\b|\brisks?\b|\bconcerns?\b"
        r"|\bsmells?\b|\bdebt\b|\bflagged\b|\bwhat(?:'s| is) wrong\b",
        re.I,
    ),
    "recommendations": re.compile(
        r"\brecommend\w*|\bsuggest\w*|\bnext steps?\b|\bpriorit\w*|\bwhat should (?:i|we)\b"
        r"|\bhow (?:can|could|should) (?:i|we) (?:fix|improve)\b|\bimprovements?\b",
        re.I,
    ),
    "strengths": re.compile(r"\bstrengths?\b|\bdoing well\b|\bwhat(?:'s| is) good\b|\bpositives?\b", re.I),
    "architecture": re.compile(
        r"\barchitect\w*|\bcomponents?\b|\blayers?\b|\bdiagram\b|\bgraph\b|\bnodes?\b|\bedges?\b",
        re.I,
    ),
    "dependencies": re.compile(
        r"\bdepend(?:s|ing)?\s+on\b|\bdepends\b|\bdependents\b|\bdependencies of\b"
        r"|\bimport(?:s|ed|ing)?\b|\bused by\b|\b(?:who|what|which \w+) (?:uses|calls)\b"
        r"|\brel(?:y|ies) on\b|\bcoupl\w*",
        re.I,
    ),
    "routes": re.compile(r"\broutes?\b|\brouting\b|\bendpoints?\b|\bapis?\b|\brest(?:ful)?\s+api", re.I),
    "stack": re.compile(
        r"\btechnolog(?:y|ies)\b|\btech\s+stack\b|\bstack\b|\bframeworks?\b|\blibrar(?:y|ies)\b"
        r"|\blanguages?\b|\bmanifests?\b|\bintegrations?\b|\bdependencies\b",
        re.I,
    ),
    "statistics": re.compile(
        r"\bhow many\b|\bnumber of\b|\bcount\b|\bstatistic\w*|\bstats\b|\bhow (?:big|large)\b"
        r"|\b(?:largest|biggest) files?\b|\bfile inventory\b|\bfile types?\b|\bsize of\b",
        re.I,
    ),
}

_WANTS_CODE_RE = re.compile(
    r"\bhow\b(?!\s+many)|\bimplement\w*|\bwhere\b|\bsource code\b|\bcode\b(?!\s+quality)"
    r"|\bdefined\b|\bdefinition\b|\bshow me\b|\bsnippet\b|\blook like\b",
    re.I,
)
_WANTS_WHY_RE = re.compile(r"\bwhy\b|\bexplain\w*|\breasons?\b|\bcaus\w*|\bjustif\w*|\bevidence\b", re.I)
_UNRESOLVED_REF_RE = re.compile(
    r"\bth(?:is|at)\s+(module|component|file|node|service|package|layer)\b", re.I
)
_INCOMING_RE = re.compile(
    r"\b(?:what|which|who)\b[^?]*\b(?:depends?\s+on|uses|imports|calls|relies\s+on|references)\b"
    r"|\bused\s+by\b|\bdependents\b|\bcallers\b",
    re.I,
)
_OUTGOING_RE = re.compile(
    r"\bwhat\s+(?:does|do)\b[^?]*\b(?:depend\s+on|import|use|call|rely\s+on)\b|\bdependencies\s+of\b",
    re.I,
)

_CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    "code_quality": re.compile(r"\bcode\s+quality\b|\bquality\b", re.I),
    "maintainability": re.compile(r"\bmaintainab\w*|\bmaintain\w*", re.I),
    "architecture": re.compile(r"\barchitecture\s+(?:score|health|category|rating)\b", re.I),
    "testing": re.compile(r"\btest\w*|\bcoverage\b", re.I),
    "security": re.compile(r"\bsecur\w*|\bsecrets?\b|\bcredentials?\b|\bvulnerab\w*", re.I),
    "documentation": re.compile(r"\bdocument\w*|\bdocs\b|\breadme\b", re.I),
    "dependency_health": re.compile(r"\bdependency\s+health\b|\bmanifests?\b|\bdependenc(?:y|ies)\b", re.I),
    "technical_debt": re.compile(r"\btechnical\s+debt\b|\bdebt\b", re.I),
}

_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "about", "what", "which", "where", "why",
    "how", "does", "did", "this", "that", "these", "those", "are", "was", "were", "has",
    "have", "can", "could", "should", "would", "will", "explain", "tell", "show", "describe",
    "repository", "repo", "project", "codebase", "please", "give", "list", "any", "all",
    "there", "its", "our", "their", "them", "they", "you", "your", "who", "use", "uses",
    "used", "using", "detected", "analysis", "found", "generated",
}
# Topic words that would otherwise match every node / route.
_GENERIC_TOKENS = {
    "architecture", "architectural", "component", "components", "node", "nodes", "edge",
    "edges", "layer", "layers", "module", "modules", "file", "files", "depend", "depends",
    "dependency", "dependencies", "import", "imports", "imported", "graph", "diagram",
    "route", "routes", "endpoint", "endpoints", "api", "apis", "work", "works", "connect",
    "connects", "relationship", "relationships", "part", "parts",
}

_CODE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")
_PATH_TOKEN_RE = re.compile(r"[\w@.-]*[\w-]/[\w./@-]+|[\w-]+\.(?:py|tsx?|jsx?|mjs|cjs|vue|svelte)\b")
_DOTTED_RE = re.compile(r"\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+\b")
_IDENT_RE = re.compile(r"\b(?:[a-z]+[A-Z]\w*|[A-Z][a-z0-9]+[A-Z]\w*|[A-Za-z]\w*_\w+)\b")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_EDGE_IMPORT_EVIDENCE_RE = re.compile(r"^(?P<file>\S+)\s+imports\s+(?P<module>\S+)$")
_TRAILING_PAREN_PATH_RE = re.compile(r"\(([^()]+)\)\s*$")


@dataclass(frozen=True)
class FileRef:
    file_path: str
    line: int | None = None
    end_line: int | None = None

    def render(self) -> str:
        if self.line is None:
            return self.file_path
        if self.end_line is not None and self.end_line != self.line:
            return f"{self.file_path}:{self.line}-{self.end_line}"
        return f"{self.file_path}:{self.line}"


@dataclass
class AnalysisFact:
    kind: str
    title: str
    detail: str
    file_refs: list[FileRef] = field(default_factory=list)
    id: str = ""


@dataclass
class AnalysisSnapshot:
    project_id: str
    analysis_doc: dict[str, Any] | None = None
    analysis_status: str = "missing"
    analysis: RepositoryAnalysisPayload | None = None
    analysis_error: str | None = None
    analysis_unreadable: bool = False
    analyzed_at: datetime | None = None
    health: HealthReport | None = None
    health_error: str | None = None
    architecture_status: str = "not_generated"
    architecture: ArchitectureGraph | None = None
    architecture_source: str | None = None
    architecture_error: str | None = None
    architecture_analyzed_at: datetime | None = None
    architecture_generated_at: datetime | None = None
    technologies: list[str] = field(default_factory=list)
    index_indexed_at: datetime | None = None


@dataclass
class AnalysisContext:
    topics: set[str] = field(default_factory=set)
    facts: list[AnalysisFact] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    wants_code: bool = False
    wants_explanation: bool = False

    @property
    def code_relevant(self) -> bool:
        return self.wants_code or bool(self.topics & CODE_TOPICS)

    def add_facts(self, facts: list[AnalysisFact]) -> None:
        for fact in facts:
            if len(self.facts) >= MAX_FACTS:
                break
            fact.id = f"A{len(self.facts) + 1}"
            self.facts.append(fact)

    def prepend_facts(self, facts: list[AnalysisFact]) -> None:
        """Put facts first (dropping later duplicates) and renumber every id."""
        seen: set[tuple[str, str]] = set()
        ordered: list[AnalysisFact] = []
        for fact in [*facts, *self.facts]:
            key = (fact.kind, fact.title)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(fact)
        self.facts = []
        self.add_facts(ordered)

    def supporting_refs(self, *, limit: int = 6, per_fact: int = 2) -> list[dict[str, Any]]:
        """File refs (stored lines first) from findings that code can substantiate."""
        refs: list[dict[str, Any]] = []
        seen: set[tuple[str, int | None]] = set()
        for fact in self.facts:
            if fact.kind not in SUPPORTABLE_KINDS:
                continue
            taken = 0
            for ref in sorted(fact.file_refs, key=lambda r: r.line is None):
                key = (ref.file_path, ref.line)
                if key in seen:
                    continue
                seen.add(key)
                refs.append({"file_path": ref.file_path, "line": ref.line, "finding_id": fact.id})
                taken += 1
                if len(refs) >= limit:
                    return refs
                if taken >= per_fact:
                    break
        return refs


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fmt_time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "unknown time"


def _owned_doc(
    doc: dict[str, Any] | None,
    *,
    project_id: str,
    owner_user_id: str | None,
    collection: str,
) -> dict[str, Any] | None:
    """Reject documents that do not belong to this project/owner (defense in depth)."""
    if doc is None:
        return None
    if str(doc.get("project_id") or "") != project_id:
        logger.warning("Ignoring %s document with mismatched project_id for %s", collection, project_id)
        return None
    doc_owner = doc.get("owner_user_id")
    if doc_owner is not None and owner_user_id is not None and str(doc_owner) != str(owner_user_id):
        logger.warning("Ignoring %s document owned by another user for project %s", collection, project_id)
        return None
    return doc


async def load_analysis_snapshot(
    db: AsyncIOMotorDatabase,
    project: dict[str, Any],
    *,
    rag_status_doc: dict[str, Any] | None = None,
) -> AnalysisSnapshot:
    project_id = str(project["id"])
    owner = project.get("owner_user_id")
    snapshot = AnalysisSnapshot(
        project_id=project_id,
        technologies=[str(t).strip() for t in (project.get("technologies") or []) if str(t).strip()],
    )
    if rag_status_doc is not None and _owned_doc(
        rag_status_doc, project_id=project_id, owner_user_id=owner, collection="rag_index_status"
    ):
        snapshot.index_indexed_at = _as_utc(rag_status_doc.get("indexed_at"))

    analysis_doc = _owned_doc(
        await db.repository_analyses.find_one({"project_id": project_id}),
        project_id=project_id,
        owner_user_id=owner,
        collection="repository_analyses",
    )
    if analysis_doc is not None:
        snapshot.analysis_doc = analysis_doc
        snapshot.analysis_status = str(analysis_doc.get("status") or "unknown")
        snapshot.analysis_error = analysis_doc.get("error")
        snapshot.analyzed_at = _as_utc(analysis_doc.get("analyzed_at"))
        snapshot.health_error = analysis_doc.get("health_error")
        if analysis_doc.get("analysis"):
            try:
                payload = RepositoryAnalysisPayload.model_validate(analysis_doc["analysis"])
                if payload.project_id == project_id:
                    snapshot.analysis = payload
                else:
                    logger.warning("Analysis payload project_id mismatch for %s", project_id)
                    snapshot.analysis_unreadable = True
            except Exception:  # noqa: BLE001
                logger.exception("Stored analysis failed validation for %s", project_id)
                snapshot.analysis_unreadable = True
        if analysis_doc.get("health_report") and snapshot.analysis is not None:
            try:
                snapshot.health = HealthReport.model_validate(analysis_doc["health_report"])
            except Exception:  # noqa: BLE001
                logger.exception("Stored health_report failed validation for %s", project_id)
                snapshot.health_error = snapshot.health_error or "Stored health report could not be read."

    arch_doc = _owned_doc(
        await db.architectures.find_one({"project_id": project_id}),
        project_id=project_id,
        owner_user_id=owner,
        collection="architectures",
    )
    if arch_doc is not None:
        snapshot.architecture_status = str(arch_doc.get("status") or "unknown")
        snapshot.architecture_source = arch_doc.get("source")
        snapshot.architecture_error = arch_doc.get("error")
        snapshot.architecture_analyzed_at = _as_utc(arch_doc.get("analyzed_at"))
        snapshot.architecture_generated_at = _as_utc(arch_doc.get("generated_at"))
        if arch_doc.get("graph"):
            try:
                snapshot.architecture = ArchitectureGraph.model_validate(arch_doc["graph"])
            except Exception:  # noqa: BLE001
                logger.exception("Stored architecture graph failed validation for %s", project_id)
    return snapshot


# ---------------------------------------------------------------------------
# Question understanding
# ---------------------------------------------------------------------------


def classify_analysis_topics(question: str) -> set[str]:
    return {topic for topic, pattern in _TOPIC_PATTERNS.items() if pattern.search(question)}


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for word in _WORD_RE.findall(text.lower()):
        for part in [word, *word.split("_")]:
            if len(part) < 3 or part in _STOPWORDS:
                continue
            out.add(part)
            if part.endswith("s") and len(part) > 4:
                out.add(part[:-1])
    return out


def _strip_ext(value: str) -> str:
    for ext in (".d.ts", *_CODE_EXTENSIONS):
        if value.endswith(ext):
            return value[: -len(ext)]
    return value


def normalize_module(value: str) -> str:
    """Normalize a file path or import specifier to a comparable slash path."""
    norm = value.strip().strip("`'\"").replace("\\", "/").lower()
    while norm.startswith("./") or norm.startswith("../"):
        norm = norm[2:] if norm.startswith("./") else norm[3:]
    norm = norm.lstrip("@/").lstrip("/")
    norm = _strip_ext(norm)
    if "/" not in norm:
        norm = norm.replace(".", "/")
    for suffix in ("/index", "/__init__"):
        if norm.endswith(suffix):
            norm = norm[: -len(suffix)]
    return norm


def module_matches(target: str, term: str) -> bool:
    t = normalize_module(target)
    q = normalize_module(term)
    if not t or not q:
        return False
    return t == q or t.endswith("/" + q) or ("/" in q and t.endswith(q))


def _symbol_names_in_question(question: str) -> list[str]:
    names: list[str] = []
    for match in _BACKTICK_RE.finditer(question):
        token = match.group(1).strip().rstrip("()")
        if token:
            names.append(token.split(".")[-1])
    names.extend(match.group(0) for match in _IDENT_RE.finditer(question))
    deduped: list[str] = []
    for name in names:
        if name not in deduped:
            deduped.append(name)
    return deduped


def _focus_terms(question: str, analysis: RepositoryAnalysisPayload | None) -> list[str]:
    """Module / file names the question names explicitly or that match a known file stem."""
    terms: list[str] = []
    for match in _BACKTICK_RE.finditer(question):
        terms.append(match.group(1).strip())
    terms.extend(m.group(0).rstrip(".") for m in _PATH_TOKEN_RE.finditer(question))
    terms.extend(m.group(0) for m in _DOTTED_RE.finditer(question))
    terms.extend(m.group(0) for m in _IDENT_RE.finditer(question))
    if analysis is not None:
        stems = {
            normalize_module(PurePosixPath(f.path).name)
            for f in analysis.files
            if f.path.endswith(_CODE_EXTENSIONS)
        }
        words = re.findall(r"[A-Za-z_][\w-]*", question)
        for word in words:
            w = word.lower()
            if len(w) >= 4 and w not in _STOPWORDS and w not in _GENERIC_TOKENS and w in stems:
                terms.append(word)
        # "rag service" → rag_service.py / ragService.ts
        for first, second in zip(words, words[1:]):
            a, b = first.lower(), second.lower()
            terms.extend(j for j in (f"{a}_{b}", f"{a}{b}", f"{a}-{b}") if j in stems)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = normalize_module(term)
        if len(key) < 3 or key in seen or key in _STOPWORDS:
            continue
        seen.add(key)
        deduped.append(term)
    return deduped[:6]


def _mentioned_categories(question: str) -> list[str]:
    return [key for key, pattern in _CATEGORY_PATTERNS.items() if pattern.search(question)]


# ---------------------------------------------------------------------------
# Availability notes
# ---------------------------------------------------------------------------

_HEALTH_TOPICS = {"health", "issues", "recommendations", "strengths"}
_ARCH_TOPICS = {"architecture", "dependencies"}


def availability_notes(snapshot: AnalysisSnapshot, topics: set[str]) -> list[str]:
    notes: list[str] = []
    status = snapshot.analysis_status
    when = _fmt_time(snapshot.analyzed_at)

    if snapshot.analysis is None:
        if status == "missing":
            notes.append("No repository analysis has been run for this project yet.")
        elif status in IN_PROGRESS_STATUSES:
            notes.append("Repository analysis is currently in progress; no results are available yet.")
        elif status == "failed":
            reason = f" ({snapshot.analysis_error})" if snapshot.analysis_error else ""
            notes.append(f"Repository analysis failed{reason}; no analysis results are available.")
        elif snapshot.analysis_unreadable:
            notes.append("The stored analysis results could not be read; re-run the analysis.")
        else:
            notes.append("The analysis record for this project contains no results.")
        return notes

    if status in IN_PROGRESS_STATUSES:
        notes.append(
            f"A new analysis is in progress; the results below are from the previous completed analysis ({when})."
        )
    elif status == "failed":
        reason = f" ({snapshot.analysis_error})" if snapshot.analysis_error else ""
        notes.append(
            f"The most recent analysis attempt failed{reason}; the results below are from the previous "
            f"completed analysis ({when})."
        )

    if topics & _HEALTH_TOPICS and snapshot.health is None:
        if snapshot.health_error:
            notes.append(f"No health report is available: {snapshot.health_error}")
        else:
            notes.append("No health report is stored for this analysis.")

    if topics & _ARCH_TOPICS:
        arch_status = snapshot.architecture_status
        if snapshot.architecture is None:
            if arch_status == "generating":
                notes.append("Architecture generation is in progress; no architecture graph is available yet.")
            elif arch_status == "failed":
                reason = f": {snapshot.architecture_error}" if snapshot.architecture_error else ""
                notes.append(f"Architecture generation failed{reason}.")
            else:
                notes.append("An architecture graph has not been generated for this project yet.")
        elif _is_outdated(snapshot.architecture_analyzed_at, snapshot.analyzed_at):
            notes.append(
                "The architecture graph was generated from an older analysis "
                f"({_fmt_time(snapshot.architecture_analyzed_at)}) than the current one ({when}); "
                "it may be outdated."
            )

    if snapshot.index_indexed_at and snapshot.analyzed_at and snapshot.index_indexed_at < snapshot.analyzed_at:
        notes.append(
            "The code index was built before the latest analysis, so source snippets may not match "
            "analysis line numbers exactly."
        )
    return notes


def _is_outdated(built_from: datetime | None, current: datetime | None) -> bool:
    if built_from is None or current is None:
        return False
    return abs((current - built_from).total_seconds()) > 1


# ---------------------------------------------------------------------------
# Fact builders
# ---------------------------------------------------------------------------


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_DETAIL_CHARS else text[: MAX_DETAIL_CHARS - 3] + "..."


def _inventory(analysis: RepositoryAnalysisPayload) -> set[str]:
    return {f.path for f in analysis.files}


def _paths_mentioned(text: str, inventory: set[str], limit: int = 5) -> list[FileRef]:
    refs: list[FileRef] = []
    for path in sorted(inventory, key=len, reverse=True):
        if len(path) >= 4 and path in text:
            refs.append(FileRef(path))
            if len(refs) >= limit:
                break
    return refs


def _category_label(key: str) -> str:
    return key.replace("_", " ")


def _health_overall_fact(snapshot: AnalysisSnapshot) -> AnalysisFact:
    health = snapshot.health
    assert health is not None
    score = f"{health.overall_score}/100" if health.overall_score is not None else "not scored"
    weights = ", ".join(f"{_category_label(k)} {int(w * 100)}%" for k, w in CATEGORY_WEIGHTS.items())
    return AnalysisFact(
        kind="health_overall",
        title="Overall health score",
        detail=_clip(
            f"Overall score {score} ({health.status}) from the analysis run at {_fmt_time(snapshot.analyzed_at)}. "
            f"It is a weighted average of scored categories ({weights}); categories with insufficient "
            "data are excluded."
        ),
    )


def _health_category_facts(snapshot: AnalysisSnapshot, question: str) -> list[AnalysisFact]:
    health = snapshot.health
    assert health is not None
    mentioned = _mentioned_categories(question)
    keys = [k for k in mentioned if k in health.categories] or list(health.categories.keys())

    def sort_key(key: str) -> tuple[int, int]:
        cat = health.categories[key]
        return (0 if cat.score is not None else 1, cat.score if cat.score is not None else 0)

    facts: list[AnalysisFact] = []
    for key in sorted(keys, key=sort_key):
        cat = health.categories[key]
        weight = int(CATEGORY_WEIGHTS.get(key, 0) * 100)
        score = f"{cat.score}/100" if cat.score is not None else "insufficient data"
        parts = [f"Score {score} (weight {weight}%). {cat.summary}"]
        if cat.issues:
            parts.append("Issues: " + "; ".join(i.rstrip(".") for i in cat.issues) + ".")
        if cat.strengths:
            parts.append("Strengths: " + "; ".join(s.rstrip(".") for s in cat.strengths[:4]) + ".")
        facts.append(
            AnalysisFact(
                kind="health_category",
                title=f"Health category: {_category_label(key)}",
                detail=_clip(" ".join(parts)),
            )
        )
    return facts


def _health_issue_facts(snapshot: AnalysisSnapshot, question: str) -> list[AnalysisFact]:
    health = snapshot.health
    assert health is not None and snapshot.analysis is not None
    inventory = _inventory(snapshot.analysis)
    mentioned = set(_mentioned_categories(question))
    issues = [i for i in health.issues if not mentioned or i.category in mentioned] or list(health.issues)
    if not issues:
        return [
            AnalysisFact(
                kind="health_issue",
                title="Detected issues",
                detail="The health report recorded no issues.",
            )
        ]
    facts: list[AnalysisFact] = []
    for issue in issues[:MAX_ISSUES]:
        refs = [FileRef(e) for e in issue.evidence if e in inventory]
        refs.extend(r for r in _paths_mentioned(issue.detail, inventory) if r not in refs)
        evidence = f" Evidence: {', '.join(issue.evidence[:5])}." if issue.evidence else ""
        facts.append(
            AnalysisFact(
                kind="health_issue",
                title=f"Issue ({issue.severity}, {_category_label(issue.category)})",
                detail=_clip(f"{issue.detail}{evidence}"),
                file_refs=refs,
            )
        )
    return facts


def _recommendation_facts(snapshot: AnalysisSnapshot, question: str) -> list[AnalysisFact]:
    health = snapshot.health
    assert health is not None
    mentioned = set(_mentioned_categories(question))
    recs = [r for r in health.recommendations if not mentioned or r.category in mentioned] or list(
        health.recommendations
    )
    if not recs:
        return [
            AnalysisFact(
                kind="recommendation",
                title="Recommendations",
                detail="The health report generated no recommendations (no category scored below 75).",
            )
        ]
    return [
        AnalysisFact(
            kind="recommendation",
            title=f"Recommendation ({rec.priority}, {_category_label(rec.category)}): {rec.title}",
            detail=_clip(f"Reason: {rec.reason} Expected impact: {rec.expected_impact}"),
        )
        for rec in recs[:MAX_RECOMMENDATIONS]
    ]


def _strength_fact(snapshot: AnalysisSnapshot) -> AnalysisFact:
    health = snapshot.health
    assert health is not None
    detail = "; ".join(health.strengths) if health.strengths else "The health report recorded no strengths."
    return AnalysisFact(kind="health_strengths", title="Recorded strengths", detail=_clip(detail))


def _scoring_notes_fact(snapshot: AnalysisSnapshot) -> AnalysisFact | None:
    health = snapshot.health
    if health is None or not health.scoring_notes:
        return None
    return AnalysisFact(
        kind="health_method",
        title="Health scoring method",
        detail=_clip(" ".join(health.scoring_notes)),
    )


def _import_line(analysis: RepositoryAnalysisPayload, source_file: str, module: str) -> int | None:
    for imp in analysis.imports:
        if imp.source_file == source_file and imp.imported_module == module:
            return imp.line
    return None


def _evidence_refs(
    evidence: list[str],
    analysis: RepositoryAnalysisPayload,
    inventory: set[str],
    candidate_files: list[str] | None = None,
) -> list[FileRef]:
    """Turn stored evidence strings into file refs, using stored lines only."""
    refs: list[FileRef] = []
    for item in evidence:
        text = str(item).strip()
        match = _EDGE_IMPORT_EVIDENCE_RE.match(text)
        if match and match.group("file") in inventory:
            refs.append(FileRef(match.group("file"), _import_line(analysis, match.group("file"), match.group("module"))))
            continue
        if text in inventory:
            refs.append(FileRef(text))
            continue
        paren = _TRAILING_PAREN_PATH_RE.search(text)
        if paren and paren.group(1) in inventory:
            route_line = None
            for route in analysis.detections.api_routes:
                if route.file_path == paren.group(1) and route.path and route.path in text:
                    route_line = route.line
                    break
            refs.append(FileRef(paren.group(1), route_line))
            continue
        if text.startswith("symbol:"):
            name = text.split(":", 1)[1].strip()
            for sym in analysis.symbols:
                if sym.name == name and (candidate_files is None or sym.file_path in candidate_files):
                    refs.append(FileRef(sym.file_path, sym.start_line, sym.end_line))
                    break
    deduped: list[FileRef] = []
    for ref in refs:
        if ref not in deduped:
            deduped.append(ref)
    return deduped


def _node_fact(node: ArchitectureNode, analysis: RepositoryAnalysisPayload, inventory: set[str]) -> AnalysisFact:
    refs = _evidence_refs(node.evidence, analysis, inventory, candidate_files=node.file_paths)
    for path in node.file_paths[:8]:
        if path in inventory and not any(r.file_path == path for r in refs):
            refs.append(FileRef(path))
    textual = [e for e in node.evidence if e not in node.file_paths][:5]
    parts = [node.description or ""]
    if textual:
        parts.append("Evidence: " + "; ".join(textual))
    if node.file_paths:
        parts.append(f"{len(node.file_paths)} associated file(s).")
    return AnalysisFact(
        kind="architecture_node",
        title=f"Architecture component: {node.label} ({node.kind}, id {node.id})",
        detail=_clip(" ".join(p for p in parts if p)),
        file_refs=refs[:8],
    )


def _edge_fact(
    edge: ArchitectureEdge,
    labels: dict[str, str],
    analysis: RepositoryAnalysisPayload,
    inventory: set[str],
) -> AnalysisFact:
    src = labels.get(edge.source, edge.source)
    tgt = labels.get(edge.target, edge.target)
    return AnalysisFact(
        kind="architecture_edge",
        title=f"Architecture relationship: {src} --{edge.type}--> {tgt}",
        detail=_clip("Evidence: " + "; ".join(edge.evidence[:5]) if edge.evidence else "No evidence recorded."),
        file_refs=_evidence_refs(edge.evidence, analysis, inventory)[:5],
    )


def _architecture_summary_fact(snapshot: AnalysisSnapshot) -> AnalysisFact:
    graph = snapshot.architecture
    assert graph is not None
    source = snapshot.architecture_source or "unknown"
    parts = [
        graph.summary or "",
        f"{len(graph.nodes)} components and {len(graph.edges)} relationships; source: {source}; "
        f"generated {_fmt_time(snapshot.architecture_generated_at)}.",
    ]
    if graph.warnings:
        parts.append("Validation notes: " + "; ".join(graph.warnings[:3]))
    return AnalysisFact(kind="architecture_summary", title="Architecture summary", detail=_clip(" ".join(parts)))


def _architecture_facts(
    snapshot: AnalysisSnapshot,
    question: str,
    focus: list[str],
    topics: set[str],
) -> tuple[list[AnalysisFact], bool]:
    """Return (facts, matched_specific_node)."""
    graph = snapshot.architecture
    analysis = snapshot.analysis
    assert graph is not None and analysis is not None
    inventory = _inventory(analysis)
    labels = {n.id: n.label for n in graph.nodes}
    q_tokens = _tokens(question) - _GENERIC_TOKENS

    scored: list[tuple[int, ArchitectureNode]] = []
    for node in graph.nodes:
        node_tokens = _tokens(f"{node.label} {node.id.replace('_', ' ')}") - _GENERIC_TOKENS
        score = 2 * len(q_tokens & node_tokens)
        for term in focus:
            if any(module_matches(p, term) for p in node.file_paths):
                score += 3
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [node for _, node in scored[:MAX_NODES]]

    facts: list[AnalysisFact] = [_architecture_summary_fact(snapshot)]
    if selected:
        selected_ids = {n.id for n in selected}
        facts.extend(_node_fact(node, analysis, inventory) for node in selected)
        incident = [e for e in graph.edges if e.source in selected_ids or e.target in selected_ids]
        facts.extend(_edge_fact(e, labels, analysis, inventory) for e in incident[:MAX_EDGES])
        return facts, True

    listing = "; ".join(f"{n.label} ({n.kind}, id {n.id})" for n in graph.nodes)
    facts.append(
        AnalysisFact(
            kind="architecture_components",
            title=f"Architecture components ({len(graph.nodes)})",
            detail=_clip(listing or "The architecture graph has no components."),
        )
    )
    edges = graph.edges
    if "dependencies" in topics and "architecture" not in topics:
        edges = [e for e in graph.edges if e.type in {"imports", "depends_on", "uses", "calls"}]
    facts.extend(_edge_fact(e, labels, analysis, inventory) for e in edges[:MAX_EDGES])
    return facts, False


def _imports_matching(imports: list[AnalysisImport], term: str, *, incoming: bool) -> list[AnalysisImport]:
    hits: list[AnalysisImport] = []
    for imp in imports:
        if incoming:
            if imp.imported_module in {".", ""}:
                continue
            if module_matches(imp.imported_module, term):
                hits.append(imp)
        elif module_matches(imp.source_file, term):
            hits.append(imp)
    return hits


def _dependency_facts(snapshot: AnalysisSnapshot, question: str, focus: list[str]) -> list[AnalysisFact]:
    analysis = snapshot.analysis
    assert analysis is not None
    outgoing_asked = bool(_OUTGOING_RE.search(question))
    incoming_asked = bool(_INCOMING_RE.search(question)) and not outgoing_asked
    directions = (
        [True] if incoming_asked else [False] if outgoing_asked else [True, False]
    )
    facts: list[AnalysisFact] = []
    for term in focus[:3]:
        for incoming in directions:
            hits = _imports_matching(analysis.imports, term, incoming=incoming)
            if not hits:
                if incoming:
                    facts.append(
                        AnalysisFact(
                            kind="import",
                            title=f"Files that import `{term}`",
                            detail=(
                                f"No recorded import of `{term}` was found. Imports are only extracted for "
                                "Python, JavaScript and TypeScript, and relative imports are matched by name."
                            ),
                        )
                    )
                continue
            lines = []
            refs: list[FileRef] = []
            for imp in hits[:MAX_IMPORT_REFS]:
                names = ", ".join(n for n in imp.names[:6] if n)
                loc = f"{imp.source_file}:{imp.line}" if imp.line else imp.source_file
                lines.append(f"{loc} imports '{imp.imported_module}'" + (f" ({names})" if names else ""))
                refs.append(FileRef(imp.source_file, imp.line))
            more = f" (+{len(hits) - MAX_IMPORT_REFS} more)" if len(hits) > MAX_IMPORT_REFS else ""
            title = f"Files that import `{term}`" if incoming else f"Imports declared in `{term}`"
            facts.append(
                AnalysisFact(
                    kind="import",
                    title=f"{title} ({len(hits)})",
                    detail=_clip("; ".join(lines) + more),
                    file_refs=refs,
                )
            )
    return facts


def _route_facts(snapshot: AnalysisSnapshot, question: str) -> list[AnalysisFact]:
    analysis = snapshot.analysis
    assert analysis is not None
    routes = analysis.detections.api_routes
    summary = analysis.summary
    q_tokens = _tokens(question) - _GENERIC_TOKENS
    wants_non_production = bool(re.search(r"\btests?\b|\bexamples?\b|\ball\b", question, re.I))

    matched = [
        r
        for r in routes
        if q_tokens
        & _tokens(f"{r.path or ''} {r.file_path} {r.function or ''}".replace("/", " ").replace("{", " "))
    ]
    pool = matched or routes
    production = [r for r in pool if r.code_role == "production"]
    others = [r for r in pool if r.code_role != "production"]
    chosen = production + (others if wants_non_production or not production else [])

    stored_note = f" Only the first {len(routes)} routes are stored." if summary.route_count > len(routes) else ""
    facts = [
        AnalysisFact(
            kind="route_summary",
            title="Detected API routes",
            detail=(
                f"{summary.production_route_count} production route(s) and "
                f"{summary.test_or_example_route_count} test/example route(s) detected "
                f"({summary.route_count} total).{stored_note} Detection covers Python decorators "
                "(FastAPI/Flask style) and JS router calls (app/router.get(...))."
            ),
        )
    ]
    for route in chosen[:MAX_ROUTES]:
        handler = f" handled by `{route.function}`" if route.function else ""
        facts.append(
            AnalysisFact(
                kind="route",
                title=f"Route {route.method} {route.path or '(path unknown)'} ({route.code_role})",
                detail=f"Defined in {route.file_path}{handler}; detected via {route.evidence}.",
                file_refs=[FileRef(route.file_path, route.line)],
            )
        )
    if len(chosen) > MAX_ROUTES:
        facts[0].detail += f" Showing {MAX_ROUTES} of {len(chosen)} matching routes."
    return facts


def _integration_refs(analysis: RepositoryAnalysisPayload, integration: str, limit: int = 3) -> list[FileRef]:
    hints = INTEGRATION_HINTS.get(integration, (integration,))
    refs: list[FileRef] = []
    for imp in analysis.imports:
        module = imp.imported_module.lower()
        if any(module == h or module.startswith(h + ".") or module.startswith(h + "/") for h in hints):
            refs.append(FileRef(imp.source_file, imp.line))
            if len(refs) >= limit:
                break
    return refs


def _stack_facts(snapshot: AnalysisSnapshot) -> list[AnalysisFact]:
    analysis = snapshot.analysis
    assert analysis is not None
    summary = analysis.summary
    facts: list[AnalysisFact] = []
    if snapshot.technologies:
        facts.append(
            AnalysisFact(
                kind="technology",
                title="Detected stack labels",
                detail="Derived from manifests, configuration files and languages: " + ", ".join(snapshot.technologies),
            )
        )
    if summary.languages:
        langs = sorted(summary.languages, key=lambda l: l.file_count, reverse=True)
        facts.append(
            AnalysisFact(
                kind="technology",
                title="Languages by file count",
                detail=", ".join(f"{l.language} ({l.file_count} files)" for l in langs[:12]),
            )
        )
    if summary.dependency_manifests:
        facts.append(
            AnalysisFact(
                kind="technology",
                title="Dependency manifests",
                detail=", ".join(summary.dependency_manifests[:12]),
                file_refs=[FileRef(p) for p in summary.dependency_manifests[:12]],
            )
        )
    for integration in analysis.detections.integrations[:8]:
        facts.append(
            AnalysisFact(
                kind="integration",
                title=f"Integration inferred from imports: {integration}",
                detail=f"Detected because recorded imports match known {integration} client modules.",
                file_refs=_integration_refs(analysis, integration),
            )
        )
    if analysis.detections.configuration_files:
        facts.append(
            AnalysisFact(
                kind="technology",
                title="Configuration files",
                detail=", ".join(analysis.detections.configuration_files[:12]),
                file_refs=[FileRef(p) for p in analysis.detections.configuration_files[:12]],
            )
        )
    return facts


def _statistics_facts(snapshot: AnalysisSnapshot, question: str) -> list[AnalysisFact]:
    analysis = snapshot.analysis
    assert analysis is not None
    s = analysis.summary
    facts = [
        AnalysisFact(
            kind="statistics",
            title="Repository statistics",
            detail=(
                f"{s.total_files} files in {s.total_directories} directories; {s.symbol_count} symbols, "
                f"{s.import_count} imports, {s.export_count} exports, {s.route_count} routes extracted "
                f"(deep parsing: {', '.join(s.deep_analysis_languages) or 'none'}). README present: "
                f"{'yes' if s.has_readme else 'no'}. Walk truncated: {'yes' if s.truncated else 'no'}. "
                f"Analyzed branch {analysis.repository.branch} at {_fmt_time(snapshot.analyzed_at)}."
            ),
        )
    ]
    roles = Counter(f.code_role for f in analysis.files)
    categories = Counter(f.category for f in analysis.files)
    facts.append(
        AnalysisFact(
            kind="statistics",
            title="File inventory breakdown",
            detail=(
                "By role: " + ", ".join(f"{k} {v}" for k, v in roles.most_common())
                + ". By category: " + ", ".join(f"{k} {v}" for k, v in categories.most_common(10)) + "."
            ),
        )
    )
    if re.search(r"\b(?:largest|biggest|large|big)\b", question, re.I):
        largest = sorted(analysis.files, key=lambda f: f.size, reverse=True)[:8]
        facts.append(
            AnalysisFact(
                kind="statistics",
                title="Largest files",
                detail=", ".join(f"{f.path} ({f.size // 1024} KB)" for f in largest),
                file_refs=[FileRef(f.path) for f in largest],
            )
        )
    return facts


def _symbol_facts(snapshot: AnalysisSnapshot, question: str) -> list[AnalysisFact]:
    analysis = snapshot.analysis
    assert analysis is not None
    facts: list[AnalysisFact] = []
    for name in _symbol_names_in_question(question):
        matches = [s for s in analysis.symbols if s.name == name]
        if not matches:
            continue
        parts = []
        refs = []
        for sym in matches[:4]:
            ref = FileRef(sym.file_path, sym.start_line, sym.end_line)
            parent = f" in {sym.parent}" if sym.parent else ""
            parts.append(f"{sym.type}{parent} at {ref.render()}")
            refs.append(ref)
        facts.append(
            AnalysisFact(
                kind="symbol",
                title=f"Symbol `{name}` ({len(matches)} definition(s))",
                detail="; ".join(parts),
                file_refs=refs,
            )
        )
        if len(facts) >= MAX_SYMBOL_FACTS:
            break
    return facts


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_analysis_context(
    snapshot: AnalysisSnapshot,
    question: str,
    *,
    extra_topics: set[str] | None = None,
    has_selection: bool = False,
) -> AnalysisContext:
    """``extra_topics`` come from workspace context; ``has_selection`` means "this X" is resolved by the caller."""
    topics = classify_analysis_topics(question) | (extra_topics or set())
    ctx = AnalysisContext(
        wants_code=bool(_WANTS_CODE_RE.search(question)),
        wants_explanation=bool(_WANTS_WHY_RE.search(question)),
    )
    analysis = snapshot.analysis

    symbol_facts = _symbol_facts(snapshot, question) if analysis is not None else []
    if symbol_facts:
        topics.add("symbols")
    ctx.topics = topics
    if not topics:
        return ctx

    ctx.notes = availability_notes(snapshot, topics)
    if analysis is None:
        return ctx

    facts: list[AnalysisFact] = []
    health = snapshot.health
    if health is not None and topics & _HEALTH_TOPICS:
        facts.append(_health_overall_fact(snapshot))
        explain_score = "health" in topics and (ctx.wants_explanation or not topics & {"issues", "recommendations"})
        if explain_score or _mentioned_categories(question) and "health" in topics:
            facts.extend(_health_category_facts(snapshot, question))
        if "issues" in topics:
            facts.extend(_health_issue_facts(snapshot, question))
        if "recommendations" in topics:
            facts.extend(_recommendation_facts(snapshot, question))
        if "strengths" in topics:
            facts.append(_strength_fact(snapshot))
        if explain_score:
            method = _scoring_notes_fact(snapshot)
            if method:
                facts.append(method)

    focus = _focus_terms(question, analysis)
    matched_node = False
    if topics & _ARCH_TOPICS and snapshot.architecture is not None:
        arch_facts, matched_node = _architecture_facts(snapshot, question, focus, topics)
        facts.extend(arch_facts)
    if "dependencies" in topics and focus:
        facts.extend(_dependency_facts(snapshot, question, focus))

    if has_selection:
        pass
    elif topics & _ARCH_TOPICS and _UNRESOLVED_REF_RE.search(question) and not focus and not matched_node:
        kind = _UNRESOLVED_REF_RE.search(question).group(1).lower()  # type: ignore[union-attr]
        ctx.notes.append(
            f"The question refers to 'this {kind}', but no {kind} was named and the assistant cannot see "
            "what is selected on screen. Ask the user to name it; known components are listed in the findings."
        )
    elif "dependencies" in topics and not focus:
        ctx.notes.append(
            "No specific module or file was named, so only graph-level relationships are shown. "
            "Ask the user which module they mean for exact import locations."
        )

    if "routes" in topics:
        facts.extend(_route_facts(snapshot, question))
    if "stack" in topics:
        facts.extend(_stack_facts(snapshot))
    if "statistics" in topics:
        facts.extend(_statistics_facts(snapshot, question))
    facts.extend(symbol_facts)

    ctx.add_facts(facts)
    return ctx


def technology_presence_facts(snapshot: AnalysisSnapshot, technology: str) -> list[AnalysisFact]:
    """Stored evidence that a named technology is (or is declared as) used."""
    analysis = snapshot.analysis
    if analysis is None:
        return []

    needle = technology.lower()
    aliases = {needle}
    if needle in {"postgres", "postgresql"}:
        aliases.update({"postgres", "postgresql", "psycopg"})
    aliases.update(INTEGRATION_HINTS.get(needle, ()))
    alias_re = re.compile(
        r"(?:^|[/.@_-])(?:" + "|".join(re.escape(a) for a in sorted(aliases)) + r")(?:$|[/.@_-])"
    )

    facts: list[AnalysisFact] = []
    labels = [t for t in snapshot.technologies if t.lower() in aliases]
    if labels:
        facts.append(
            AnalysisFact(kind="technology", title="Detected stack labels", detail=", ".join(labels))
        )
    integrations = [i for i in analysis.detections.integrations if i.lower() in aliases]
    for integration in integrations:
        facts.append(
            AnalysisFact(
                kind="integration",
                title=f"Integration inferred from imports: {integration}",
                detail=f"Recorded imports match known {integration} client modules.",
                file_refs=_integration_refs(analysis, integration),
            )
        )
    hits = [imp for imp in analysis.imports if alias_re.search(imp.imported_module.lower())]
    if hits and not integrations:
        facts.append(
            AnalysisFact(
                kind="import",
                title=f"Imports referencing {technology} ({len(hits)})",
                detail="; ".join(
                    f"{imp.source_file}:{imp.line} imports '{imp.imported_module}'" if imp.line
                    else f"{imp.source_file} imports '{imp.imported_module}'"
                    for imp in hits[:8]
                ),
                file_refs=[FileRef(imp.source_file, imp.line) for imp in hits[:8]],
            )
        )
    return facts


def render_analysis_block(ctx: AnalysisContext) -> str:
    lines: list[str] = []
    if ctx.notes:
        lines.append("Availability notes (state these when relevant; never fill the gap with guesses):")
        lines.extend(f"- {note}" for note in ctx.notes)
    if ctx.facts:
        if lines:
            lines.append("")
        lines.append("Findings:")
        for fact in ctx.facts:
            lines.append(f"[{fact.id}] {fact.title}")
            lines.append(f"    {fact.detail}")
            if fact.file_refs:
                lines.append("    Files: " + ", ".join(ref.render() for ref in fact.file_refs))
    return "\n".join(lines)
