"""Deterministic Python AST extraction."""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass
class ExtractedSymbol:
    name: str
    type: str
    file_path: str
    start_line: int | None
    end_line: int | None
    parent: str | None = None


@dataclass
class ExtractedImport:
    source_file: str
    imported_module: str
    names: list[str]
    line: int | None = None


@dataclass
class ExtractedExport:
    source_file: str
    name: str
    export_type: str
    line: int | None = None


@dataclass
class PythonExtractResult:
    symbols: list[ExtractedSymbol]
    imports: list[ExtractedImport]
    exports: list[ExtractedExport]
    routes: list[dict]
    parse_error: str | None = None


def analyze_python_source(file_path: str, source: str) -> PythonExtractResult:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return PythonExtractResult([], [], [], [], parse_error=str(exc))

    symbols: list[ExtractedSymbol] = []
    imports: list[ExtractedImport] = []
    exports: list[ExtractedExport] = []
    routes: list[dict] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            symbols.append(
                ExtractedSymbol(
                    name=node.name,
                    type="class",
                    file_path=file_path,
                    start_line=getattr(node, "lineno", None),
                    end_line=getattr(node, "end_lineno", None),
                )
            )
            exports.append(
                ExtractedExport(
                    source_file=file_path,
                    name=node.name,
                    export_type="class",
                    line=getattr(node, "lineno", None),
                )
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(
                        ExtractedSymbol(
                            name=child.name,
                            type="method",
                            file_path=file_path,
                            start_line=getattr(child, "lineno", None),
                            end_line=getattr(child, "end_lineno", None),
                            parent=node.name,
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                ExtractedSymbol(
                    name=node.name,
                    type="function",
                    file_path=file_path,
                    start_line=getattr(node, "lineno", None),
                    end_line=getattr(node, "end_lineno", None),
                )
            )
            exports.append(
                ExtractedExport(
                    source_file=file_path,
                    name=node.name,
                    export_type="function",
                    line=getattr(node, "lineno", None),
                )
            )
            route = _extract_fastapi_route(file_path, node)
            if route:
                routes.append(route)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.extend(_imports_from_node(file_path, node))

    # Nested decorator routes on methods already covered for module-level; also scan all functions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            route = _extract_fastapi_route(file_path, node)
            if route and route not in routes:
                routes.append(route)

    return PythonExtractResult(symbols=symbols, imports=imports, exports=exports, routes=routes)


def _imports_from_node(file_path: str, node: ast.AST) -> list[ExtractedImport]:
    results: list[ExtractedImport] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            results.append(
                ExtractedImport(
                    source_file=file_path,
                    imported_module=alias.name,
                    names=[alias.asname or alias.name],
                    line=getattr(node, "lineno", None),
                )
            )
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        names = [alias.name for alias in node.names]
        results.append(
            ExtractedImport(
                source_file=file_path,
                imported_module=module or ".",
                names=names,
                line=getattr(node, "lineno", None),
            )
        )
    return results


def _extract_fastapi_route(file_path: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict | None:
    for decorator in node.decorator_list:
        method = None
        path = None
        target = decorator
        if isinstance(decorator, ast.Call):
            target = decorator.func
            if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                path = decorator.args[0].value
        name = _decorator_name(target)
        if name in {"get", "post", "put", "patch", "delete", "options", "head"}:
            method = name.upper()
        elif name in {"route", "api_route"}:
            method = "ROUTE"
        if method:
            return {
                "file_path": file_path,
                "function": node.name,
                "method": method,
                "path": path,
                "line": getattr(node, "lineno", None),
                "evidence": "python_decorator",
            }
    return None


def _decorator_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None
