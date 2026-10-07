"""Resolve the user's workspace context (current page + selection) for a chat question.

The client sends identifiers only (page name, architecture node id, file path, health
item index + title). Each one is looked up in the project's own stored analysis; a
selection that cannot be found there is reported as unresolved and never reaches the
prompt as client-supplied text. The selection is only used when the question refers to
it, so it never stops the assistant from answering about other parts of the repository.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.analysis_context import (
    MAX_EDGES,
    AnalysisFact,
    AnalysisSnapshot,
    FileRef,
    _category_label,
    _clip,
    _edge_fact,
    _inventory,
    _node_fact,
    _paths_mentioned,
    _tokens,
    classify_analysis_topics,
    module_matches,
)
from app.schemas.health_report import HealthIssue, HealthRecommendation
from app.schemas.rag import ChatContext

PAGE_LABELS = {"overview": "Overview", "health": "Health", "architecture": "Architecture"}
# Analysis topics a question about the page itself ("summarize this page") should draw on.
PAGE_TOPICS: dict[str, set[str]] = {
    "overview": {"health", "statistics", "stack"},
    "health": {"health", "issues", "recommendations"},
    "architecture": {"architecture"},
}

MAX_FILE_SYMBOLS = 8
MAX_FILE_IMPORTS = 8

_REPO_PHRASE_RE = re.compile(
    r"\b(?:this|that|the)\s+(?:repo(?:sitory)?|project|codebase|code\s*base|app(?:lication)?)\b", re.I
)
_DEICTIC_RE = re.compile(
    r"\b(?:this|that|these|those|it|its|here|selected|current(?:ly)?|above)\b", re.I
)
_PAGE_REF_RE = re.compile(
    r"\b(?:this|the|current)\s+(?:page|screen|view|tab|panel)\b|\bwhat am i (?:looking at|seeing)\b"
    r"|\bon (?:the )?screen\b",
    re.I,
)
# Words that carry no subject of their own ("How do I fix?", "Explain more").
_VAGUE_WORDS = {
    "fix", "fixed", "fixing", "mean", "means", "detail", "details", "more", "work", "works",
    "improve", "resolve", "address", "matter", "matters", "important", "summarize", "summary",
    "elaborate", "expand", "again", "happen", "happening", "doing", "need", "start", "first",
}


@dataclass
class Selection:
    kind: str
    label: str
    facts: list[AnalysisFact]
    topics: set[str]
    retrieval_hint: str
    wants_source: bool = False


@dataclass
class PageContext:
    page: str | None = None
    selection: Selection | None = None
    unresolved: str | None = None
    use_selection: bool = False
    page_topics: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    @property
    def applied_label(self) -> str | None:
        if self.use_selection and self.selection is not None:
            return self.selection.label
        if self.page_topics and self.page:
            return f"{PAGE_LABELS[self.page]} page"
        return None

    def retrieval_question(self, question: str) -> str:
        if self.use_selection and self.selection is not None and self.selection.retrieval_hint:
            return f"{question} {self.selection.retrieval_hint}"
        return question

    def prompt_section(self) -> str | None:
        if self.page is None and self.selection is None:
            return None
        lines: list[str] = []
        if self.page:
            lines.append(f"The user is viewing the {PAGE_LABELS[self.page]} page of the repository workspace.")
        if self.selection is not None:
            if self.use_selection:
                ids = ", ".join(f.id for f in self.selection.facts if f.id)
                lines.append(
                    f"They have selected {self.selection.label}. Findings about the selection are listed first"
                    + (f" ({ids})" if ids else "")
                    + "; use them to resolve references such as 'this' or 'it'."
                )
            else:
                lines.append(f"They have {self.selection.label} selected, but the question does not refer to it.")
        lines.append(
            "Treat this as background only. If the question is about a different part of the repository, "
            "answer that question fully and do not steer the answer toward the current page or selection."
        )
        return "\n".join(lines)


def _without_repo_phrases(question: str) -> str:
    return _REPO_PHRASE_RE.sub(" ", question)


def refers_to_selection(question: str) -> bool:
    text = _without_repo_phrases(question)
    return bool(_DEICTIC_RE.search(text) or _PAGE_REF_RE.search(text)) or is_vague(question)


def is_vague(question: str) -> bool:
    """True when the question names no subject, e.g. "Why?" or "How do I fix it?"."""
    if _REPO_PHRASE_RE.search(question):
        return False
    return not (_tokens(question) - _VAGUE_WORDS)


# ---------------------------------------------------------------------------
# Selection resolution (stored data only)
# ---------------------------------------------------------------------------


def _category_fact(snapshot: AnalysisSnapshot, category: str) -> AnalysisFact | None:
    health = snapshot.health
    if health is None or category not in health.categories:
        return None
    cat = health.categories[category]
    score = f"{cat.score}/100" if cat.score is not None else "insufficient data"
    return AnalysisFact(
        kind="health_category",
        title=f"Health category: {_category_label(category)}",
        detail=_clip(f"Score {score}. {cat.summary}"),
    )


def _issue_fact(snapshot: AnalysisSnapshot, issue: HealthIssue, *, selected: bool) -> AnalysisFact:
    assert snapshot.analysis is not None
    inventory = _inventory(snapshot.analysis)
    refs = [FileRef(e) for e in issue.evidence if e in inventory]
    refs.extend(r for r in _paths_mentioned(issue.detail, inventory) if r not in refs)
    evidence = f" Evidence: {', '.join(issue.evidence[:5])}." if issue.evidence else ""
    prefix = "Selected issue" if selected else "Issue"
    return AnalysisFact(
        kind="health_issue",
        title=f"{prefix} ({issue.severity}, {_category_label(issue.category)}): {issue.title}",
        detail=_clip(f"{issue.detail}{evidence}"),
        file_refs=refs,
    )


def _recommendation_fact(rec: HealthRecommendation, *, selected: bool) -> AnalysisFact:
    prefix = "Selected recommendation" if selected else "Recommendation"
    return AnalysisFact(
        kind="recommendation",
        title=f"{prefix} ({rec.priority}, {_category_label(rec.category)}): {rec.title}",
        detail=_clip(f"Reason: {rec.reason} Expected impact: {rec.expected_impact}"),
    )


def _pick(items: list, index: int, title: str):
    if 0 <= index < len(items) and items[index].title == title:
        return items[index]
    return next((item for item in items if item.title == title), None)


def _resolve_health_item(snapshot: AnalysisSnapshot, context: ChatContext) -> Selection | None:
    health = snapshot.health
    sel = context.health_item
    if health is None or sel is None or snapshot.analysis is None:
        return None
    if sel.kind == "issue":
        issue = _pick(health.issues, sel.index, sel.title)
        if issue is None:
            return None
        facts = [_issue_fact(snapshot, issue, selected=True)]
        category = _category_fact(snapshot, issue.category)
        if category:
            facts.append(category)
        facts.extend(
            _recommendation_fact(r, selected=False) for r in health.recommendations if r.category == issue.category
        )
        hint_paths = " ".join(r.file_path for r in facts[0].file_refs[:3])
        return Selection(
            kind="health_issue",
            label=f"Health issue: {issue.title} ({issue.severity}, {_category_label(issue.category)})",
            facts=facts,
            topics={"issues"},
            retrieval_hint=f"{_category_label(issue.category)} {hint_paths}".strip(),
        )

    rec = _pick(health.recommendations, sel.index, sel.title)
    if rec is None:
        return None
    facts = [_recommendation_fact(rec, selected=True)]
    category = _category_fact(snapshot, rec.category)
    if category:
        facts.append(category)
    facts.extend(_issue_fact(snapshot, i, selected=False) for i in health.issues if i.category == rec.category)
    return Selection(
        kind="recommendation",
        label=f"Recommendation: {rec.title} ({rec.priority}, {_category_label(rec.category)})",
        facts=facts,
        topics={"recommendations"},
        retrieval_hint=f"{rec.title} {_category_label(rec.category)}",
    )


def _resolve_node(snapshot: AnalysisSnapshot, node_id: str) -> Selection | None:
    graph = snapshot.architecture
    analysis = snapshot.analysis
    if graph is None or analysis is None:
        return None
    node = next((n for n in graph.nodes if n.id == node_id), None)
    if node is None:
        return None
    inventory = _inventory(analysis)
    labels = {n.id: n.label for n in graph.nodes}
    node_fact = _node_fact(node, analysis, inventory)
    node_fact.title = f"Selected architecture component: {node.label} ({node.kind}, id {node.id})"
    incident = [e for e in graph.edges if e.source == node.id or e.target == node.id]
    facts = [node_fact, *(_edge_fact(e, labels, analysis, inventory) for e in incident[:MAX_EDGES])]
    return Selection(
        kind="architecture_node",
        label=f"Architecture component: {node.label}",
        facts=facts,
        topics={"architecture"},
        retrieval_hint=" ".join([node.label, *node.file_paths[:3]]),
        wants_source=True,
    )


def _resolve_file(snapshot: AnalysisSnapshot, file_path: str) -> Selection | None:
    analysis = snapshot.analysis
    if analysis is None:
        return None
    path = file_path.strip().replace("\\", "/")
    entry = next((f for f in analysis.files if f.path == path), None)
    if entry is None:
        return None

    refs: list[FileRef] = []
    parts = [
        f"{entry.language or 'Unknown-language'} file, category {entry.category}, role {entry.code_role}, "
        f"{entry.size} bytes."
    ]
    symbols = [s for s in analysis.symbols if s.file_path == path]
    if symbols:
        listed = []
        for sym in symbols[:MAX_FILE_SYMBOLS]:
            ref = FileRef(sym.file_path, sym.start_line, sym.end_line)
            refs.append(ref)
            listed.append(f"{sym.name} ({sym.type}) at {ref.render()}")
        more = f" (+{len(symbols) - MAX_FILE_SYMBOLS} more)" if len(symbols) > MAX_FILE_SYMBOLS else ""
        parts.append("Defines: " + "; ".join(listed) + more + ".")
    routes = [r for r in analysis.detections.api_routes if r.file_path == path]
    if routes:
        listed = []
        for route in routes[:MAX_FILE_SYMBOLS]:
            ref = FileRef(route.file_path, route.line)
            refs.append(ref)
            listed.append(f"{route.method} {route.path or '(path unknown)'} at {ref.render()}")
        parts.append("Routes: " + "; ".join(listed) + ".")
    outgoing = [i for i in analysis.imports if i.source_file == path]
    if outgoing:
        listed = [
            f"'{i.imported_module}'" + (f" (line {i.line})" if i.line else "") for i in outgoing[:MAX_FILE_IMPORTS]
        ]
        parts.append(f"Imports {len(outgoing)} module(s): " + ", ".join(listed) + ".")
    incoming = [
        i
        for i in analysis.imports
        if i.source_file != path and i.imported_module not in {".", ""} and module_matches(path, i.imported_module)
    ]
    if incoming:
        listed = []
        for imp in incoming[:MAX_FILE_IMPORTS]:
            listed.append(f"{imp.source_file}:{imp.line}" if imp.line else imp.source_file)
        parts.append("Imported by (matched by module name): " + ", ".join(listed) + ".")
    refs.append(FileRef(path))
    refs.extend(FileRef(i.source_file, i.line) for i in incoming[:3])

    return Selection(
        kind="file",
        label=f"File: {path}",
        facts=[
            AnalysisFact(
                kind="file",
                title=f"Selected file: {path}",
                detail=_clip(" ".join(parts)),
                file_refs=refs,
            )
        ],
        topics={"symbols"},
        retrieval_hint=path,
        wants_source=True,
    )


def _resolve_selection(snapshot: AnalysisSnapshot, context: ChatContext) -> tuple[Selection | None, str | None]:
    """Return (selection, description of an unresolved selection)."""
    if context.health_item is not None:
        kind = "issue" if context.health_item.kind == "issue" else "recommendation"
        found = _resolve_health_item(snapshot, context)
        return (found, None) if found else (None, f"The selected health {kind} was not found in the stored health report; it may have changed after a re-analysis.")
    if context.file_path:
        found = _resolve_file(snapshot, context.file_path)
        return (found, None) if found else (None, "The selected file is not in the stored file inventory for this analysis.")
    if context.architecture_node_id:
        found = _resolve_node(snapshot, context.architecture_node_id)
        return (found, None) if found else (None, "The selected architecture component was not found in the stored architecture graph; it may have been regenerated.")
    return None, None


def resolve_page_context(
    snapshot: AnalysisSnapshot,
    context: ChatContext | None,
    question: str,
) -> PageContext:
    if context is None:
        return PageContext()
    page = context.page if context.page in PAGE_LABELS else None
    pc = PageContext(page=page)
    selection, unresolved = _resolve_selection(snapshot, context)
    pc.selection = selection
    pc.unresolved = unresolved

    refers = refers_to_selection(question)
    pc.use_selection = selection is not None and refers
    if unresolved and refers:
        pc.notes.append(unresolved)

    about_page = bool(_PAGE_REF_RE.search(question)) or is_vague(question)
    if page and not pc.use_selection and about_page and not classify_analysis_topics(question):
        pc.page_topics = set(PAGE_TOPICS[page])
    return pc
