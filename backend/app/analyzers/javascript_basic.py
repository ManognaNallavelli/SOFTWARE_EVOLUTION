"""Best-effort JavaScript/TypeScript structural extraction via regex."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.analyzers.python_ast import ExtractedExport, ExtractedImport, ExtractedSymbol


@dataclass
class JsExtractResult:
    symbols: list[ExtractedSymbol]
    imports: list[ExtractedImport]
    exports: list[ExtractedExport]
    routes: list[dict]


_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?:type\s+)?(?:([\w*\s{},]+)\s+from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_EXPORT_FUNC_RE = re.compile(
    r"""export\s+(?:async\s+)?function\s+([A-Za-z_][\w]*)""",
)
_EXPORT_CLASS_RE = re.compile(r"""export\s+(?:default\s+)?class\s+([A-Za-z_][\w]*)""")
_EXPORT_CONST_RE = re.compile(
    r"""export\s+(?:const|let|var|type|interface)\s+([A-Za-z_][\w]*)""",
)
_FUNC_RE = re.compile(
    r"""(?:(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][\w]*)"""
    r"""|(?:(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][\w]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>))"""
)
_CLASS_RE = re.compile(r"""(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_][\w]*)""")
_INTERFACE_RE = re.compile(r"""(?:export\s+)?interface\s+([A-Za-z_][\w]*)""")
_TYPE_RE = re.compile(r"""(?:export\s+)?type\s+([A-Za-z_][\w]*)\s*=""")
_ROUTE_RE = re.compile(
    r"""(?:app|router|Router)\.(get|post|put|patch|delete|options|head|use)\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)


def analyze_js_ts_source(file_path: str, source: str) -> JsExtractResult:
    symbols: list[ExtractedSymbol] = []
    imports: list[ExtractedImport] = []
    exports: list[ExtractedExport] = []
    routes: list[dict] = []

    for match in _IMPORT_RE.finditer(source):
        names_raw = (match.group(1) or "").strip()
        module = match.group(2)
        names = [n.strip() for n in re.split(r"[{},]", names_raw) if n.strip() and n.strip() != "*"]
        line = source[: match.start()].count("\n") + 1
        imports.append(
            ExtractedImport(
                source_file=file_path,
                imported_module=module,
                names=names or ["*"],
                line=line,
            )
        )

    for match in _REQUIRE_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        imports.append(
            ExtractedImport(
                source_file=file_path,
                imported_module=match.group(1),
                names=["require"],
                line=line,
            )
        )

    for match in _CLASS_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        symbols.append(
            ExtractedSymbol(
                name=match.group(1),
                type="class",
                file_path=file_path,
                start_line=line,
                end_line=None,
            )
        )

    for match in _INTERFACE_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        symbols.append(
            ExtractedSymbol(
                name=match.group(1),
                type="interface",
                file_path=file_path,
                start_line=line,
                end_line=None,
            )
        )

    for match in _TYPE_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        symbols.append(
            ExtractedSymbol(
                name=match.group(1),
                type="type",
                file_path=file_path,
                start_line=line,
                end_line=None,
            )
        )

    for match in _FUNC_RE.finditer(source):
        name = match.group(1) or match.group(2)
        if not name:
            continue
        line = source[: match.start()].count("\n") + 1
        symbols.append(
            ExtractedSymbol(
                name=name,
                type="function",
                file_path=file_path,
                start_line=line,
                end_line=None,
            )
        )

    for match in _EXPORT_FUNC_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        exports.append(
            ExtractedExport(
                source_file=file_path,
                name=match.group(1),
                export_type="function",
                line=line,
            )
        )
    for match in _EXPORT_CLASS_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        exports.append(
            ExtractedExport(
                source_file=file_path,
                name=match.group(1),
                export_type="class",
                line=line,
            )
        )
    for match in _EXPORT_CONST_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        exports.append(
            ExtractedExport(
                source_file=file_path,
                name=match.group(1),
                export_type="binding",
                line=line,
            )
        )

    for match in _ROUTE_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        routes.append(
            {
                "file_path": file_path,
                "function": None,
                "method": match.group(1).upper(),
                "path": match.group(2),
                "line": line,
                "evidence": "js_router_call",
            }
        )

    return JsExtractResult(symbols=symbols, imports=imports, exports=exports, routes=routes)
