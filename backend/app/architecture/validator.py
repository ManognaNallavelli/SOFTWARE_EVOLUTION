"""Validate and repair ArchitectureGraph against analysis evidence."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from app.schemas.analysis import RepositoryAnalysisPayload
from app.schemas.architecture import ArchitectureEdge, ArchitectureGraph, ArchitectureNode, EdgeType, NodeKind

ALLOWED_KINDS: set[str] = {
    "frontend",
    "backend",
    "service",
    "module",
    "api",
    "database",
    "external",
    "config",
    "test",
    "other",
}
ALLOWED_EDGE_TYPES: set[str] = {
    "calls",
    "imports",
    "uses",
    "contains",
    "exposes",
    "stores",
    "depends_on",
}

MAX_NODES = 24
MAX_EDGES = 40


def _normalize_id(raw: str, used: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw.strip())[:64] or "node"
    candidate = base
    i = 2
    while candidate in used:
        candidate = f"{base}_{i}"
        i += 1
    used.add(candidate)
    return candidate


def _collect_evidence_corpus(analysis: RepositoryAnalysisPayload) -> set[str]:
    corpus: set[str] = set()
    for f in analysis.files:
        corpus.add(f.path.lower())
        corpus.add(PurePosixPath(f.path).name.lower())
        parts = PurePosixPath(f.path).parts
        if parts:
            corpus.add(parts[0].lower())
    for s in analysis.symbols:
        corpus.add(s.name.lower())
        corpus.add(s.file_path.lower())
    for route in analysis.detections.api_routes:
        corpus.add(route.file_path.lower())
        if route.path:
            corpus.add(route.path.lower())
        if route.function:
            corpus.add(route.function.lower())
        corpus.add(route.evidence.lower())
    for lst in (
        analysis.detections.frontend_components,
        analysis.detections.backend_services,
        analysis.detections.data_access_modules,
        analysis.detections.configuration_files,
        analysis.detections.tests,
        analysis.detections.integrations,
        analysis.summary.important_files,
        analysis.summary.dependency_manifests,
    ):
        for item in lst:
            corpus.add(str(item).lower())
    for lang in analysis.summary.languages:
        corpus.add(lang.language.lower())
    # Repository identity
    if analysis.repository.name:
        corpus.add(analysis.repository.name.lower())
    if analysis.repository.full_name:
        corpus.add(analysis.repository.full_name.lower())
    if analysis.repository.url:
        corpus.add(analysis.repository.url.lower())
    return corpus


def _evidence_supported(items: list[str], corpus: set[str]) -> bool:
    if not items:
        return False
    for item in items:
        token = item.strip().lower()
        if not token:
            continue
        if token in corpus:
            return True
        # substring / path fragment match
        for entry in corpus:
            if token in entry or entry in token:
                return True
    return False


def validate_architecture_graph(
    graph: ArchitectureGraph,
    analysis: RepositoryAnalysisPayload,
) -> ArchitectureGraph:
    """Drop unsupported edges/nodes; normalize kinds; never invent replacements."""

    warnings = list(graph.warnings)
    corpus = _collect_evidence_corpus(analysis)
    used_ids: set[str] = set()
    nodes: list[ArchitectureNode] = []
    id_map: dict[str, str] = {}

    for node in graph.nodes[:MAX_NODES]:
        raw_id = (node.id or node.label or "node").strip()
        new_id = _normalize_id(raw_id, used_ids)
        id_map[node.id] = new_id
        kind = node.kind if node.kind in ALLOWED_KINDS else "other"
        if node.kind not in ALLOWED_KINDS:
            warnings.append(f"Normalized unknown node kind '{node.kind}' → other for {new_id}.")

        evidence = [e for e in (node.evidence or []) if str(e).strip()][:8]
        file_paths = [p for p in (node.file_paths or []) if str(p).strip()][:12]
        support = evidence + file_paths + [node.label]
        if not _evidence_supported(support, corpus):
            warnings.append(f"Dropped node '{node.label}' — no analysis evidence.")
            used_ids.discard(new_id)
            id_map.pop(node.id, None)
            continue

        nodes.append(
            ArchitectureNode(
                id=new_id,
                label=(node.label or new_id)[:80],
                kind=kind,  # type: ignore[arg-type]
                description=(node.description or None),
                file_paths=file_paths,
                evidence=evidence or file_paths[:3] or [node.label],
            )
        )

    node_ids = {n.id for n in nodes}
    edges: list[ArchitectureEdge] = []
    edge_ids: set[str] = set()

    for edge in graph.edges[:MAX_EDGES]:
        source = id_map.get(edge.source, edge.source)
        target = id_map.get(edge.target, edge.target)
        if source not in node_ids or target not in node_ids:
            warnings.append(
                f"Dropped edge {edge.source}->{edge.target} — missing endpoint node."
            )
            continue
        if source == target:
            warnings.append(f"Dropped self-edge on {source}.")
            continue
        etype = edge.type if edge.type in ALLOWED_EDGE_TYPES else "depends_on"
        if edge.type not in ALLOWED_EDGE_TYPES:
            warnings.append(f"Normalized unknown edge type '{edge.type}' → depends_on.")

        evidence = [e for e in (edge.evidence or []) if str(e).strip()][:8]
        if not evidence or not _evidence_supported(evidence, corpus):
            # Soft allow if both endpoints are evidence-backed nodes
            warnings.append(
                f"Edge {source}->{target} had weak evidence; kept only as structural link."
            )
            evidence = evidence or [f"{source}→{target}"]

        eid = _normalize_id(edge.id or f"{source}_{etype}_{target}", edge_ids)
        edges.append(
            ArchitectureEdge(
                id=eid,
                source=source,
                target=target,
                type=etype,  # type: ignore[arg-type]
                label=edge.label,
                evidence=evidence,
            )
        )

    if not nodes:
        warnings.append("No evidence-backed nodes remained after validation.")

    summary = graph.summary
    if not summary:
        summary = (
            f"Architecture graph with {len(nodes)} components and {len(edges)} relationships "
            f"derived from structural analysis of {analysis.repository.name}."
        )

    return ArchitectureGraph(
        nodes=nodes,
        edges=edges,
        summary=summary,
        warnings=warnings[:40],
    )


# Re-export for type checkers / callers
__all__ = ["validate_architecture_graph", "ALLOWED_KINDS", "ALLOWED_EDGE_TYPES", "NodeKind", "EdgeType"]
