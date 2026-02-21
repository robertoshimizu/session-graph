# Changelog

All notable changes to session-graph are documented here.

## [0.3.0] - 2026-02-21

### Added
- **Two-level entity filtering** — Level 1 (`is_valid_entity()`) rejects garbage at extraction time with 13 filter groups: filenames, hex colors, CLI flags, ICD codes, snake_case identifiers, DOM selectors, version strings, CSS dimensions, issue refs, function calls, npm scopes, percentage values. Level 2 (`is_linkable_entity()`) pre-filters before Wikidata API calls.
- **Top-10 extraction cap** — prompt extracts at most 10 triples per message, prioritizing architectural decisions and technology choices. Hard cap enforced in parsing.
- **Frequency-based entity linking** — `--min-sessions N` flag (default: 2) only links entities appearing in N+ sessions. ~77% of entities are single-session noise, reducing linking cost from ~37K to ~8.6K entities.
- **48 whitelisted short terms** (`ai`, `api`, `llm`, `rdf`, `sql`, etc.) bypass all entity filters.

### Changed
- Entity linking pipeline now runs pre-filter before any Wikidata API calls.
- Extraction prompt updated to enforce top-10 cap.

## [0.2.0] - 2026-02-20

### Added
- **Context-aware entity linking** — neighboring KnowledgeTriple relationships extracted from `.ttl` files and passed as disambiguation context to the ReAct agent. Resolves ambiguous labels (e.g., "condition" → disease instead of programming conditional).
- **`snapshot_links.py`** — inspect intermediate entity linking progress without interrupting a running job.
- **`devkg-sparql` skill** — 14 local + 6 Wikidata SPARQL query templates for Claude Code.

### Changed
- Entity linking agent receives triple context for better disambiguation.

## [0.1.0] - 2026-02-16

### Added
- **Batch processing via Vertex AI Batch Prediction** (`bulk_batch.py`) — submit/status/collect workflow with 50% cost discount.
- **Sequential bulk processor** (`bulk_process.py`) — watermarks, subagent filtering, `--dry-run`, `--limit`, `--force`.
- **Agentic entity linking** — LangGraph ReAct agent (Gemini 2.5 Flash + Wikidata API tool) replaces heuristic. 7/7 precision.
- **161 entity alias mappings** (`entity_aliases.json`) — k8s→kubernetes, otel→OpenTelemetry, etc.
- **Multi-platform parsers** — Claude Code (JSONL), DeepSeek (JSON zip), Grok (JSON), Warp (SQLite).
- **OWL ontology** composing PROV-O + SIOC + SKOS + Dublin Core + Schema.org with 24 curated predicates.
- **Dual storage** — direct edges for traversal + reified KnowledgeTriple nodes for provenance.
- **Apache Jena Fuseki** integration for SPARQL queries.

## [0.0.1] - 2026-02-13

### Added
- Initial project: JSONL→RDF pipeline, OWL ontology, Fuseki loader.
