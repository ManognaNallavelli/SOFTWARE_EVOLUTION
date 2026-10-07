# Canonical Repository Analysis Model

Phase 2 stores one structural analysis document per project in MongoDB collection `repository_analyses`.

## Payload shape

```text
RepositoryAnalysis
  project_id
  repository { name, url, branch, full_name }
  summary
    total_files, total_directories
    languages[{ language, file_count, total_bytes }]
    important_files[], has_readme
    dependency_manifests[]
    deep_analysis_languages[]
    truncated, symbol_count, import_count, export_count, route_count
  files[{ path, language, size, extension, category }]
  symbols[{ name, type, file_path, start_line, end_line, parent }]
  imports[{ source_file, imported_module, names[], line }]
  exports[{ source_file, name, export_type, line }]
  detections
    frontend_components[], backend_services[]
    api_routes[], data_access_modules[]
    configuration_files[], tests[], integrations[]
  limits { caps and parser notes }
```

## Language depth

- **Python:** deep AST (`ast`) for classes, functions/methods, imports, FastAPI-style routes
- **JavaScript/TypeScript:** best-effort regex for imports/exports/functions/classes/interfaces/routes
- **Other languages:** file/language/category metadata only

## Project status lifecycle

`created → validating → cloning → analyzing → completed | failed`

Legacy Phase 1 value `pending` is treated as not analyzed.

## Architecture graph (Phase 3)

Stored separately in MongoDB `architectures` (not as React Flow state):

```text
ArchitectureGraph
  nodes[{ id, label, kind, description?, file_paths[], evidence[] }]
  edges[{ id, source, target, type, label?, evidence[] }]
  summary?, warnings[]
```

Built from a compact brief of `RepositoryAnalysis` via Gemini (or deterministic fallback), then schema-validated against analysis evidence.
