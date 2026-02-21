# session-graph

Instructions for Claude Code when working on this project.

## Project Goal

Build a unified developer knowledge graph that connects scattered knowledge from AI coding sessions across multiple platforms:

- Claude Code session logs (`.jsonl`)
- DeepSeek conversation exports (JSON zip)
- Grok conversation exports (JSON zip)
- Warp terminal AI sessions (SQLite)
- Cursor AI sessions (planned)
- VS Code Copilot interactions (planned)
- ChatGPT conversation exports (planned)

The pipeline extracts structured `(subject, predicate, object)` triples from AI assistant messages, links entities to Wikidata via `owl:sameAs`, and loads everything into a SPARQL-queryable triplestore with full provenance.

## Architecture: Ontology + Knowledge Graph + Hybrid Retrieval

### Ontology Stack (Composed W3C Standards)

Do NOT create a custom ontology from scratch. Compose these battle-tested standards:

| Ontology        | Role                                                    | Maturity              |
| --------------- | ------------------------------------------------------- | --------------------- |
| **PROV-O**      | Backbone: who did what, when, from where (provenance)   | W3C Recommendation    |
| **SIOC**        | Conversation structure: messages, threads, platforms    | W3C Member Submission |
| **SKOS**        | Concept taxonomy: topics, skills, technologies          | W3C Recommendation    |
| **Dublin Core** | Universal metadata: dates, titles, creators             | ISO Standard          |
| **Schema.org**  | Cherry-pick: `SoftwareSourceCode`, `Question`, `Answer` | De facto standard     |

Validated by IBM's GRAPH4CODE project (2B triples, same composition approach).

### Triplestore: Apache Jena Fuseki

- SPARQL 1.1 compliant
- Docker or standalone deployment
- Native TDB2 storage
- Handles 100K+ triples without issue

## Ontology: Predicate Vocabulary & Custom Classes

### Custom Classes

- `devkg:Entity` (subclass of `prov:Entity`) -- extracted technical concepts
- `devkg:KnowledgeTriple` -- reified triple for provenance (links to source message + session)
- `devkg:Project` -- software project with working directory and source files

### Curated Predicate Vocabulary (24 OWL ObjectProperties)

Closed-world design: the LLM is instructed to use ONLY these predicates. A normalization step maps any LLM-generated predicate to the closest match (fallback: `relatedTo`).

**Standard-mapped predicates:**

- `devkg:isPartOf` -> `rdfs:subPropertyOf dcterms:isPartOf`
- `devkg:hasPart` -> `rdfs:subPropertyOf dcterms:hasPart`
- `devkg:broader` -> `rdfs:subPropertyOf skos:broader`
- `devkg:narrower` -> `rdfs:subPropertyOf skos:narrower`
- `devkg:relatedTo` -> `rdfs:subPropertyOf skos:related`

**Custom predicates (19):** `uses`, `dependsOn`, `enables`, `implements`, `extends`, `alternativeTo`, `solves`, `produces`, `configures`, `composesWith`, `provides`, `requires`, `isTypeOf`, `builtWith`, `deployedOn`, `storesIn`, `queriedWith`, `integratesWith`, `servesAs`

**Additional properties:** `devkg:hasSourceFile`, `devkg:belongsToProject`, `devkg:hasWorkingDirectory`

## Pipeline Flow

```
1. SOURCE PARSING (per platform -> RDF Turtle)
----------------------------------------------

  Claude Code (.jsonl)  -->  jsonl_to_rdf.py    -->  .ttl
  DeepSeek (.json zip)  -->  deepseek_to_rdf.py -->  .ttl
  Grok (.json zip)      -->  grok_to_rdf.py     -->  .ttl
  Warp (SQLite)         -->  warp_to_rdf.py     -->  .ttl

  Each parser:
  +-- Reads source format
  +-- Creates PROV-O + SIOC structure (sessions, messages, authors)
  +-- Calls triple_extraction.py for each assistant message
  |   +-- SQLite cache check (.triple_cache.db) by message UUID
  |   |   +-- Cache hit -> use cached triples (0 API calls)
  |   |   +-- Cache miss -> call LLM, cache result
  |   +-- Sends text to LLM -> top 10 (subject, predicate, object) triples
  |       +-- Capped at 10 triples per message (top 10 by importance)
  |       +-- Closed-world predicate vocab (24 predicates)
  |       +-- Level 1 entity filter: is_valid_entity() -- 13 filter groups
  |       |   (filenames, hex colors, CLI flags, ICD codes, snake_case,
  |       |    DOM selectors, version strings, CSS dims, issue refs, etc.)
  |       |   48 whitelisted short terms bypass all filters
  |       +-- Entity length filter (1-3 words only)
  |       +-- Retry on JSON truncation (max 2 retries)
  +-- Outputs .ttl with session structure + knowledge triples

  Shared modules:
  +-- common.py          -- namespaces, URI helpers, RDF node builders
  +-- triple_extraction.py -- LLM prompt + parsing + normalization
  +-- vertex_ai.py       -- Vertex AI auth, model factory


2. ENTITY LINKING (RDF -> Wikidata owl:sameAs)
----------------------------------------------

  .ttl files -->  link_entities.py -->  wikidata_links.ttl

  +-- Extracts all devkg:Entity labels from input .ttl files
  +-- Normalizes via entity_aliases.json (161 mappings: k8s->kubernetes, etc.)
  +-- Level 2 pre-filter: is_linkable_entity() -- rejects ~6% garbage
  |   (catches entities that slipped through Level 1 or pre-date the filter)
  +-- Frequency filter: --min-sessions N (default 2) -- only links entities
  |   appearing in 2+ sessions. Reduces linking set by ~77%.
  +-- For each entity that passes:
  |   +-- Check SQLite cache (.entity_cache.db)
  |   +-- If miss -> agentic_linker_langgraph.py (ReAct agent)
  |   |   +-- LangGraph + Gemini 2.5 Flash
  |   |   +-- Tool: search_wikidata (Wikidata API, up to 3 calls)
  |   |   +-- Structured output: WikidataMatch (qid, confidence, reasoning)
  |   |   +-- Caches result in SQLite
  |   +-- Confidence threshold (0.7) -- below -> no owl:sameAs emitted
  +-- Entity dedup: same QID -> owl:sameAs between aliases
  +-- Outputs wikidata_links.ttl


3. BULK PROCESSING (orchestrator)
---------------------------------

  bulk_process.py (sequential, per-session)
  +-- Finds all ~/.claude/projects/**/*.jsonl
  +-- Filters out subagent files (avoids duplicate triples)
  +-- SHA256 watermarks -> skip already-processed sessions
  +-- CLI: --dry-run, --limit N, --skip-linking, --force

  bulk_batch.py (Vertex AI Batch Prediction, 50% cost discount)
  +-- submit: all sessions -> GCS -> single batch job
  +-- status --wait: poll until SUCCEEDED
  +-- collect: download results -> .ttl files


4. LOAD INTO TRIPLESTORE
-------------------------

  load_fuseki.py -->  Apache Jena Fuseki (SPARQL endpoint)


5. QUERY
--------

  +-- SPARQL queries (sample_queries.sparql -- 14 templates)
  +-- Federated queries -> Wikidata
  +-- Claude Code via devkg-sparql skill (auto-generates SPARQL)
```

## File Structure

```
ontology/devkg.ttl                    # OWL ontology (PROV-O + SIOC + SKOS + DC + Schema.org + 24 predicates)
pipeline/
+-- common.py                        # Shared: namespaces, URI helpers, RDF node builders
+-- vertex_ai.py                     # Vertex AI auth, Gemini + Claude model wrappers
+-- triple_extraction.py             # LLM prompt, extraction, normalization, stopwords
+-- jsonl_to_rdf.py                  # Claude Code JSONL -> RDF (assistant-only extraction)
+-- deepseek_to_rdf.py               # DeepSeek JSON zip -> RDF
+-- grok_to_rdf.py                   # Grok MongoDB JSON -> RDF
+-- warp_to_rdf.py                   # Warp SQLite -> RDF (--min-exchanges, --min-triples)
+-- link_entities.py                 # Wikidata entity linking (agentic default, --heuristic fallback)
+-- agentic_linker_langgraph.py      # LangGraph ReAct agent for Wikidata disambiguation
+-- entity_aliases.json              # 161 tech synonym mappings (k8s->kubernetes, etc.)
+-- bulk_process.py                  # Sequential bulk processor (watermarks, --dry-run)
+-- bulk_batch.py                    # Vertex AI Batch Prediction (submit/status/collect)
+-- batch_extraction.py              # Batch job helpers (GCS upload, polling)
+-- snapshot_links.py                # Inspect intermediate entity linking (reads cache read-only)
+-- load_fuseki.py                   # Upload .ttl to Apache Jena Fuseki
+-- sample_queries.sparql            # 14 SPARQL query templates
+-- .entity_cache.db                 # SQLite cache for Wikidata links (auto-created)
+-- .triple_cache.db                 # SQLite cache for extracted triples by message UUID (auto-created)
.claude/skills/devkg-sparql/SKILL.md # SPARQL skill (14 local + 6 Wikidata templates)
cognee_eval/                         # Cognee evaluation (rejected -- no RDF output)
research/                            # Wikidata entity linking research docs
docker/
+-- __init__.py                      # Package marker
+-- queue_consumer.py                # RabbitMQ consumer (pika): dequeues jobs, runs pipeline, uploads to Fuseki
Dockerfile.pipeline                   # Python 3.12 image with pipeline deps + pika
docker-compose.yml                    # fuseki + rabbitmq + pipeline-runner
hooks/stop_hook.sh                    # Post-session hook: curl POST to RabbitMQ HTTP API (~33ms)
tests/test_integration.sh             # 16-point end-to-end integration test
output/                               # Generated .ttl files and batch job manifests
requirements.txt                      # Python dependencies
```

## How to Run

```bash
# Start all services (Fuseki + RabbitMQ + pipeline-runner)
docker compose up -d

# RabbitMQ Management UI: http://localhost:15672 (devkg/devkg)
# Fuseki SPARQL UI: http://localhost:3030

# The stop hook (hooks/stop_hook.sh) auto-publishes to RabbitMQ after each Claude Code session.
# The pipeline-runner container processes the queue automatically.

# Manual: single session (Claude Code)
source .venv/bin/activate
python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl

# Other platforms
python -m pipeline.deepseek_to_rdf <zip_path> output/deepseek.ttl --conversation 0
python -m pipeline.grok_to_rdf <zip_path> output/grok.ttl --conversation 0
python -m pipeline.warp_to_rdf output/warp.ttl --conversation 0 --min-exchanges 5

# Bulk process all Claude Code sessions
python -m pipeline.bulk_process

# Bulk via Vertex AI Batch Prediction (50% cheaper)
python -m pipeline.bulk_batch submit
python -m pipeline.bulk_batch status --wait --poll-interval 60
python -m pipeline.bulk_batch collect

# Entity linking
PYTHONUNBUFFERED=1 python -m pipeline.link_entities \
  --input output/*.ttl --output output/wikidata_links.ttl

# Load .ttl files into Docker Fuseki (requires auth)
python -c "
from pipeline.load_fuseki import ensure_dataset, upload_turtle
import glob
auth = ('admin', 'admin')
ensure_dataset('http://localhost:3030', 'devkg', auth=auth)
for f in glob.glob('output/claude/*.ttl'):
    upload_turtle('http://localhost:3030', 'devkg', f, auth=auth)
"

# Integration test
bash tests/test_integration.sh

# Query at http://localhost:3030
```

## Key Design Decisions

- **Assistant-only extraction**: Only assistant messages are sent to the LLM for triple extraction. User messages are short prompts with no extractable knowledge.
- **Closed-world predicate vocabulary**: 24 predicates defined as OWL ObjectProperties. LLM is constrained to this set; any deviation is fuzzy-matched to the closest predicate (fallback: `relatedTo`). Prompt includes wrong/correct examples to keep `relatedTo` usage under 1%.
- **Dual storage**: Direct edges for fast traversal + reified `KnowledgeTriple` nodes for provenance (links back to source message + session).
- **Provenance in every SPARQL query**: Templates include `sourceFile`, `platform`, and content snippet. Bidirectional traversal via UNION (relationships may be stored in either direction).
- **Agentic linker over heuristic**: LangGraph ReAct agent (Gemini 2.5 Flash + Wikidata API tool) achieves 7/7 precision vs ~50% for keyword heuristic. Resolves abbreviations (k8s->kubernetes, otel->OpenTelemetry).
- **Confidence threshold 0.7**: Only emits `owl:sameAs` for high-confidence Wikidata matches. Low-confidence logged to stderr.
- **Entity deduplication**: Entities sharing the same Wikidata QID get `owl:sameAs` to each other (e.g., `medication` == `medicamento` via Q12140).
- **Subagent filtering**: `bulk_process.py` filters out subagent `.jsonl` files to avoid 76% knowledge triple duplication from overlapping content with parent sessions.
- **Model comparison** (on 79 assistant messages): Gemini 2.5 Flash is best overall (142 triples, 15 predicates, 0.7% relatedTo). Flash-Lite is noisy (11% relatedTo). Claude Haiku 4.5 has high precision but low recall (37 triples). Only 20% triple overlap between models.
- **Top-10 extraction cap**: Prompt instructs "extract at most 10 triples per message, prioritize architectural decisions and technology choices". Hard cap enforced in parsing. Median extraction rate is ~1.4 triples/message so most messages are unaffected; caps the noisy long tail.
- **Two-level entity filtering**: Level 1 (`is_valid_entity()` in `triple_extraction.py`) prevents garbage at extraction time -- 13 filter groups covering filenames, hex colors, CLI flags, ICD codes, snake_case identifiers, DOM selectors, version strings, CSS dimensions, issue refs, function calls, npm scopes, percentage values. Level 2 (`is_linkable_entity()` in `link_entities.py`) pre-filters before Wikidata API calls. Both share a 48-term whitelist of known-good short terms (`ai`, `api`, `llm`, `rdf`, etc.).
- **Frequency-based linking threshold**: `--min-sessions 2` (default) only links entities appearing in 2+ sessions. ~77% of entities appear in only 1 session (noise), dramatically reducing linking cost.
- **Entity boundaries**: Prompt enforces 1-3 word entities; `is_valid_entity()` rejects 4+ words, paths, dimension strings, single chars.
- **Context-aware entity linking**: `link_entities.py` extracts neighboring KnowledgeTriple relationships from .ttl files and passes them as context to the ReAct agent. Improves disambiguation for ambiguous labels (e.g., "condition" -> disease vs programming conditional).
- **`FILTER(LANG(?label) = "")`**: Used in all SPARQL queries to avoid duplicate rows from lang-tagged vs untagged literals.
- **Triple extraction cache**: SQLite cache (`.triple_cache.db`) keyed by message UUID. The stop hook fires on every Claude Code pause (not just session end), causing the same JSONL to be re-processed repeatedly. The cache ensures each message's LLM extraction only happens once — re-runs rebuild the full RDF graph (cheap) but skip API calls for cached messages. Stores `text_hash` for auditability. Shared between local CLI and Docker container via volume mount.

## Known Issues

- **Entity linking output buffering**: `link_entities.py` output doesn't appear when piped. Fix: use `PYTHONUNBUFFERED=1` env var.
- **~33% Wikidata link rate**: Expected -- many entities are domain-specific or internal and don't exist in Wikidata.
- **Gemini JSON truncation**: ~5% of responses truncate mid-JSON on long outputs. `max_output_tokens` set to 8192 with retry logic (max 2 retries, shorter input on retry).
- **Cache quality**: Some cached Wikidata links may be low quality if created by an older heuristic linker. Wipe `.entity_cache.db` and re-link with the agentic linker if needed.

## Adding a New Parser

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. In short:

1. Create `pipeline/<platform>_to_rdf.py`
2. Implement `build_graph(input_path, skip_extraction, model) -> Graph`
3. Use helpers from `pipeline/common.py` (do not duplicate RDF construction)
4. Set `platform` correctly in `create_session_node()`
5. Only extract triples from assistant messages
6. Support `--skip-extraction` and `--model` CLI flags

## Reference Projects

- **GRAPH4CODE** (IBM Research): 2B triples, composes Schema.org + SKOS + PROV-O + SIOC + SIO
- **Graphiti MCP server**: `github.com/getzep/graphiti` (temporal KG for agent memory)
- **Neo4j LLM Knowledge Graph Builder**: Docker-based, extracts KG from PDFs/web/YouTube
