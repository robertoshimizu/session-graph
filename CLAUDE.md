# Dev Knowledge Graph

## Origin Session

Initial research session: `ec11ec1e-9d4f-4694-9a7d-b8cfce8e539c`

- Conducted from `~/.claude/` on 2026-02-13
- Copied to this project's session directory for continuity
- Use `/research-sessions` to search it

## Project Goal

Build a unified developer knowledge graph that connects scattered knowledge from:

- Codebases (multiple projects)
- Claude Code session logs (`~/.claude/projects/**/*.jsonl`)
- ChatGPT conversation exports
- Cursor AI sessions
- Warp terminal AI sessions
- VS Code Copilot interactions
- Grok and DeepSeek AI conversations

The system should enable **chatting with your entire knowledge base** (like Google Code Wiki but self-hosted, private, and model-agnostic).

## Architecture Decision: Ontology + Knowledge Graph + Hybrid Retrieval

### Ontology Stack (Existing W3C Standards, Composed)

Do NOT create a custom ontology. Compose these 4+1 battle-tested standards:

| Ontology        | Role                                                    | Maturity              |
| --------------- | ------------------------------------------------------- | --------------------- |
| **PROV-O**      | Backbone: who did what, when, from where (provenance)   | W3C Recommendation    |
| **SIOC**        | Conversation structure: messages, threads, platforms    | W3C Member Submission |
| **SKOS**        | Concept taxonomy: topics, skills, technologies          | W3C Recommendation    |
| **Dublin Core** | Universal metadata: dates, titles, creators             | ISO Standard          |
| **Schema.org**  | Cherry-pick: `SoftwareSourceCode`, `Question`, `Answer` | De facto standard     |

Validated by IBM's GRAPH4CODE project (2B triples, same composition approach).

### Graph Database: Neo4j

- Use **Neo4j Community Edition** (Docker, free) or **AuraDB Free** (cloud)
- Import ontologies via **n10s** (neosemantics) plugin
- Native vector search since v5.x enables hybrid retrieval
- Every AI framework integrates: LangChain, Cognee, Graphiti, Mem0
- LLMs generate valid Cypher reliably (unlike SPARQL)
- Add Apache Jena later only if OWL reasoning is needed

### Key Frameworks

| Framework                         | Purpose                                                                          | Notes                                         |
| --------------------------------- | -------------------------------------------------------------------------------- | --------------------------------------------- |
| **Cognee** (`topoteretes/cognee`) | Ingest 30+ sources, auto-generate KG, entity extraction, user-defined ontologies | 10K+ stars, supports Neo4j                    |
| **Graphiti** (`getzep/graphiti`)  | Temporal KG from conversations, tracks when facts were true, hybrid retrieval    | 3K+ stars, **has MCP server for Claude Code** |
| **LangChain + Neo4j**             | `LLMGraphTransformer`, `GraphCypherQAChain`, hybrid vector+keyword+graph search  | `pip install langchain-neo4j`                 |
| **Microsoft GraphRAG**            | Community-based summarization, multi-hop reasoning                               | Expensive indexing (100-1000x RAG)            |
| **LightRAG**                      | Lightweight alternative to MS GraphRAG                                           | EMNLP 2025                                    |

### Conversation Parsers (Already Exist)

| Source                 | Parser Tool                                                               |
| ---------------------- | ------------------------------------------------------------------------- |
| Claude Code            | `claude-code-log` (714 stars), `claude-code-transcripts` (Simon Willison) |
| ChatGPT                | `chatgpt-exporter` (Tampermonkey script)                                  |
| Cursor                 | `cursor-history` CLI (`@johnlindquist/cursor-history`), SpecStory         |
| VS Code Copilot        | Built-in: `Chat: Export Session...` (Ctrl+Shift+P)                        |
| Multi-IDE              | WayLog VS Code extension (Cursor, Copilot, Lingma, CodeBuddy)             |
| Warp / Grok / DeepSeek | No standardized tools (custom parser needed)                              |

### Code-to-Graph Tools

| Tool                                         | What It Does                                               |
| -------------------------------------------- | ---------------------------------------------------------- |
| `CodeGraph` (`ChrisRoyse/CodeGraph`)         | Parses TS/JS, Python, Java, Go, C# via tree-sitter         |
| `code-graph-rag` (`vitali87/code-graph-rag`) | tree-sitter AST to Memgraph (Neo4j-compatible), NL queries |
| `tree-sitter-graph` (official)               | Language-agnostic AST to arbitrary graph                   |

### Hybrid Retrieval (KG + Vector)

Benchmarks show hybrid GraphRAG achieves highest factual correctness (0.58 vs 0.50 graph-only vs 0.48 vector-only).

- Build KG first (the harder, more valuable part)
- Add vector embeddings on `sioc:content` later for fuzzy search
- Neo4j has built-in vector indexes for single-system hybrid queries

## Architecture Diagram

```
Scattered Sources               Adapter Layer              Knowledge Graph
-----------------               -------------              ---------------
Claude Code JSONL  --+
ChatGPT JSON       --+
Cursor Markdown    --+-->  Normalize to  -->  Cognee/Graphiti  -->  Neo4j
VS Code JSON       --+     PROV-O + SIOC       (entity extraction     (n10s)
Warp sessions      --+     + SKOS concepts       + relationship         |
Grok/DeepSeek      --+                            mapping)              |
                                                                        v
Codebases          -->  tree-sitter/CodeGraph  ------------------>  Neo4j
                                                                        |
                                                                        v
                                                              Hybrid Retrieval
                                                          (Cypher + Vector search)
                                                                        |
                                                                        v
                                                              Graphiti MCP Server
                                                                  -> Claude Code
```

## RDF Example (How Ontologies Compose)

```turtle
@prefix prov:    <http://www.w3.org/ns/prov#> .
@prefix sioc:    <http://rdfs.org/sioc/ns#> .
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix schema:  <http://schema.org/> .
@prefix ex:      <http://devkg.local/> .

# A Claude Code session is both a PROV Activity and a SIOC Forum
ex:session-2025-02-13 a prov:Activity, sioc:Forum ;
    dcterms:created "2025-02-13T14:30:00Z"^^xsd:dateTime ;
    dcterms:title "Debugging Supabase auth flow" ;
    prov:wasAssociatedWith ex:developer-roberto, ex:agent-claude-code ;
    sioc:topic ex:concept-supabase-auth .

# A message in that session
ex:message-001 a sioc:Post, prov:Entity ;
    sioc:has_container ex:session-2025-02-13 ;
    sioc:has_creator ex:developer-roberto ;
    sioc:content "How do I handle JWT refresh in Supabase?" ;
    prov:wasGeneratedBy ex:session-2025-02-13 ;
    schema:about ex:concept-jwt, ex:concept-supabase-auth .

# Code artifact produced from that session
ex:file-auth-utils a prov:Entity, schema:SoftwareSourceCode ;
    dcterms:title "auth-utils.ts" ;
    prov:wasGeneratedBy ex:session-2025-02-13 ;
    prov:wasDerivedFrom ex:message-003 .

# Concept taxonomy
ex:concept-supabase-auth a skos:Concept ;
    skos:prefLabel "Supabase Authentication"@en ;
    skos:broader ex:concept-authentication ;
    skos:related ex:concept-jwt .
```

## Ontology: Predicate Vocabulary & Custom Classes

### Custom Classes

- `devkg:Entity` (subclass of `prov:Entity`) — extracted technical concepts
- `devkg:KnowledgeTriple` — reified triple for provenance (links to source message + session)
- `devkg:Project` — software project with working directory and source files

### Curated Predicate Vocabulary (24 OWL ObjectProperties)

Closed-world design: the LLM is instructed to use ONLY these predicates. A normalization step maps any LLM-generated predicate to the closest match (fallback: `relatedTo`).

**Standard-mapped predicates:**

- `devkg:isPartOf` → `rdfs:subPropertyOf dcterms:isPartOf`
- `devkg:hasPart` → `rdfs:subPropertyOf dcterms:hasPart`
- `devkg:broader` → `rdfs:subPropertyOf skos:broader`
- `devkg:narrower` → `rdfs:subPropertyOf skos:narrower`
- `devkg:relatedTo` → `rdfs:subPropertyOf skos:related`

**Custom predicates (19):** `uses`, `dependsOn`, `enables`, `implements`, `extends`, `alternativeTo`, `solves`, `produces`, `configures`, `composesWith`, `provides`, `requires`, `isTypeOf`, `builtWith`, `deployedOn`, `storesIn`, `queriedWith`, `integratesWith`, `servesAs`

**Additional properties:** `devkg:hasSourceFile`, `devkg:belongsToProject`, `devkg:hasWorkingDirectory`

## Pipeline Flow

```
1. SOURCE PARSING (per platform → RDF Turtle)
──────────────────────────────────────────────

  Claude Code (.jsonl)  ──→  jsonl_to_rdf.py    ──→  .ttl
  DeepSeek (.json zip)  ──→  deepseek_to_rdf.py ──→  .ttl
  Grok (.json zip)      ──→  grok_to_rdf.py     ──→  .ttl
  Warp (SQLite)         ──→  warp_to_rdf.py     ──→  .ttl

  Each parser:
  ├── Reads source format
  ├── Creates PROV-O + SIOC structure (sessions, messages, authors)
  ├── Calls triple_extraction.py for each assistant message
  │   └── Sends text to Gemini 2.5 Flash → (subject, predicate, object) triples
  │       ├── Closed-world predicate vocab (24 predicates)
  │       ├── Stopword filter (rejects /exit, 1400px, single chars)
  │       ├── Entity length filter (1-3 words only)
  │       └── Retry on JSON truncation (max 2 retries)
  └── Outputs .ttl with session structure + knowledge triples

  Shared modules:
  ├── common.py          — namespaces, URI helpers, RDF node builders
  ├── triple_extraction.py — Gemini prompt + parsing + normalization
  └── vertex_ai.py       — Vertex AI auth (base64 creds), model factory
                           (Gemini + Claude wrappers, global endpoint for Gemini 3)


2. ENTITY LINKING (RDF → Wikidata owl:sameAs)
──────────────────────────────────────────────

  .ttl files ──→ link_entities.py ──→ wikidata_links.ttl

  ├── Extracts all devkg:Entity labels from input .ttl files
  ├── Normalizes via entity_aliases.json (161 mappings: k8s→kubernetes, etc.)
  ├── For each entity:
  │   ├── Check SQLite cache (.entity_cache.db)
  │   ├── If miss → agentic_linker_langgraph.py (ReAct agent)
  │   │   ├── LangGraph + Gemini 2.5 Flash
  │   │   ├── Tool: search_wikidata (Wikidata API, up to 3 calls)
  │   │   ├── Structured output: WikidataMatch (qid, confidence, reasoning)
  │   │   └── Caches result in SQLite
  │   └── Confidence threshold (0.7) — below → no owl:sameAs emitted
  ├── Entity dedup: same QID → owl:sameAs between aliases
  └── Outputs wikidata_links.ttl


3. BULK PROCESSING (orchestrator — Claude Code sessions only)
─────────────────────────────────────────────────────────────

  bulk_process.py (sequential, per-session)
  ├── Finds all ~/.claude/projects/**/*.jsonl
  ├── Filters out subagent files (avoids duplicate triples)
  ├── SHA256 watermarks → skip already-processed sessions
  ├── For each new session:
  │   ├── Step 1: jsonl_to_rdf.py → output/claude/<session>.ttl
  │   └── Step 2: link_entities.py → output/claude/wikidata_links.ttl
  └── CLI: --dry-run, --limit N, --skip-linking, --force

  bulk_batch.py (Vertex AI Batch Prediction, 50% cost discount)
  ├── submit: all sessions → GCS → single batch job
  ├── status --wait: poll until SUCCEEDED
  ├── collect: download results → .ttl files
  └── Entity linking run separately after collect


4. LOAD INTO TRIPLESTORE
────────────────────────

  load_fuseki.py ──→ Apache Jena Fuseki (SPARQL endpoint)

  ├── Uploads .ttl files via Fuseki's /data endpoint
  └── Query at http://localhost:3030


5. QUERY (human or Claude Code)
───────────────────────────────

  ├── SPARQL queries (sample_queries.sparql — 14 templates)
  ├── Federated queries → Wikidata (SERVICE <https://query.wikidata.org/sparql>)
  └── Claude Code via devkg-sparql skill (auto-generates SPARQL)
```

## File Structure

```
ontology/devkg.ttl                    # OWL ontology (PROV-O + SIOC + SKOS + DC + Schema.org + 24 predicates)
pipeline/
├── common.py                        # Shared: namespaces, URI helpers, RDF node builders
├── vertex_ai.py                     # Vertex AI auth, Gemini + Claude model wrappers
├── triple_extraction.py             # Ontologist prompt, extraction, normalization, stopwords
├── jsonl_to_rdf.py                  # Claude Code JSONL → RDF (assistant-only extraction)
├── deepseek_to_rdf.py               # DeepSeek JSON zip → RDF
├── grok_to_rdf.py                   # Grok MongoDB JSON → RDF
├── warp_to_rdf.py                   # Warp SQLite → RDF (--min-exchanges, --min-triples)
├── link_entities.py                 # Wikidata entity linking (agentic default, --heuristic fallback)
├── agentic_linker_langgraph.py      # LangGraph ReAct agent for Wikidata disambiguation
├── entity_aliases.json              # 161 tech synonym mappings (k8s→kubernetes, etc.)
├── bulk_process.py                  # Sequential bulk processor (watermarks, --dry-run)
├── bulk_batch.py                    # Vertex AI Batch Prediction (submit/status/collect)
├── batch_extraction.py              # Batch job helpers (GCS upload, polling)
├── snapshot_links.py                # Inspect intermediate entity linking (reads cache read-only)
├── load_fuseki.py                   # Upload .ttl to Apache Jena Fuseki
├── sample_queries.sparql            # 14 SPARQL query templates
├── .entity_cache.db                 # SQLite cache for Wikidata links (auto-created)
├── agentic_linker.py                # Single-shot Gemini linker (prototype, superseded)
└── agentic_linker_adk.py            # Google ADK agent (superseded by LangGraph)
.claude/skills/devkg-sparql/SKILL.md # SPARQL skill (14 local + 6 Wikidata templates)
cognee_eval/                         # Cognee evaluation (rejected — no RDF output)
research/                            # Wikidata entity linking research docs
hooks/post_session_hook.sh           # Automation skeleton
daemon/sync_daemon.py                # Watchdog file watcher skeleton
output/                              # Generated .ttl files and batch job manifests
requirements.txt                     # Python dependencies
```

## How to Run

```bash
# Start Fuseki
cd ~/opt/apache-jena-fuseki && ./fuseki-server &

# Option A: Bulk process all Claude Code sessions (sequential)
.venv/bin/python -m pipeline.bulk_process

# Option A2: Bulk process via Vertex AI Batch Prediction (cheaper, faster)
.venv/bin/python -m pipeline.bulk_batch submit
.venv/bin/python -m pipeline.bulk_batch status --wait --poll-interval 60
.venv/bin/python -m pipeline.bulk_batch collect

# Option B: Single session
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl

# Option C: Other platforms
.venv/bin/python -m pipeline.deepseek_to_rdf external_knowledge/deepseek_data.zip output/deepseek.ttl --conversation 0
.venv/bin/python -m pipeline.grok_to_rdf external_knowledge/grok_data.zip output/grok.ttl --conversation 0
.venv/bin/python -m pipeline.warp_to_rdf output/warp.ttl --conversation 0 --min-exchanges 5

# Custom model (default: gemini-2.5-flash)
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl --model gemini-2.5-flash-lite
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl --model gemini-3-flash-preview
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl --model claude-haiku-4-5@20251001

# Structure only (no LLM API calls)
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl --skip-extraction

# Entity linking (agentic, default — use PYTHONUNBUFFERED=1 to see progress)
PYTHONUNBUFFERED=1 .venv/bin/python -m pipeline.link_entities --input output/*.ttl --output output/wikidata_links.ttl

# Entity linking (heuristic fallback)
.venv/bin/python -m pipeline.link_entities --heuristic --input output/*.ttl --output output/wikidata_links.ttl

# Load into Fuseki
.venv/bin/python pipeline/load_fuseki.py output/*.ttl

# Query at http://localhost:3030
```

## Key Design Decisions & Learnings

- **Assistant-only extraction**: Only assistant messages are sent to Gemini for triple extraction. User messages are short prompts with no extractable knowledge.
- **Closed-world predicate vocabulary**: 24 predicates defined as OWL ObjectProperties. LLM is constrained to this set; any deviation is fuzzy-matched to the closest predicate (fallback: `relatedTo`). Prompt includes wrong/correct examples to keep `relatedTo` usage under 1%.
- **Dual storage**: Direct edges for fast traversal + reified `KnowledgeTriple` nodes for provenance (links back to source message + session).
- **Provenance in every SPARQL query**: Templates include `sourceFile`, `platform`, and content snippet. Bidirectional traversal via UNION (relationships may be stored in either direction).
- **Agentic linker over heuristic**: LangGraph ReAct agent (Gemini 2.5 Flash + Wikidata API tool) achieves 7/7 precision vs ~50% for keyword heuristic. Resolves abbreviations (k8s→kubernetes, otel→OpenTelemetry). ADK agent had same precision but failed 3/7 due to text parsing fragility.
- **Confidence threshold 0.7**: Only emits `owl:sameAs` for high-confidence Wikidata matches. Low-confidence logged to stderr.
- **Entity deduplication**: Entities sharing the same Wikidata QID get `owl:sameAs` to each other (e.g., `medication` == `medicamento` via Q12140).
- **Subagent filtering**: `bulk_process.py` filters out subagent `.jsonl` files to avoid 76% knowledge triple duplication from overlapping content with parent sessions.
- **Model comparison** (on 79 assistant messages): Gemini 2.5 Flash is best overall (142 triples, 15 predicates, 0.7% relatedTo). Flash-Lite is noisy (11% relatedTo). Claude Haiku 4.5 has high precision but terrible recall (37 triples). Only 20% triple overlap between models.
- **`FILTER(LANG(?label) = "")`**: Used in all SPARQL queries to avoid duplicate rows from lang-tagged vs untagged literals.
- **Entity boundaries**: Prompt enforces 1-3 word entities; `is_valid_entity()` rejects 4+ words, paths, dimension strings, single chars.
- **Context-aware entity linking**: `link_entities.py` extracts neighboring KnowledgeTriple relationships from .ttl files and passes them as context to the ReAct agent. Dramatically improves disambiguation for ambiguous labels (e.g., "condition" → disease instead of programming conditional).

## Known Issues & Troubleshooting

- **Entity linking output buffering**: `link_entities.py` output doesn't appear when piped. Fix: use `PYTHONUNBUFFERED=1` env var.
- **`vertexai` SDK deprecation warning**: Cosmetic, won't affect until June 2026.
- **Cache quality**: Some cached Wikidata links may be questionable if created by the old heuristic linker. Wipe `.entity_cache.db` and re-link with agentic linker if needed.
- **33% Wikidata link rate**: Expected for a personal KG — many entities are domain-specific (medical terms in Portuguese, internal config paths) that don't exist in Wikidata.
- **Gemini JSON truncation**: ~5% of responses truncate mid-JSON on long outputs. `max_output_tokens` set to 8192 with retry logic (max 2 retries, shorter input on retry).
- **Gemini 3 Flash Preview**: Requires `global` endpoint (not regional). `get_gemini_model()` auto-reinitializes with `location="global"`.
- **Batch collect idempotency**: Watermarks updated per-session during collect. If collect crashes mid-way, partial progress is saved but batch output must be re-downloaded.

## Sprint History

| Sprint | Date       | Key Accomplishments |
| ------ | ---------- | ------------------- |
| 1      | 2026-02-13 | OWL ontology (PROV-O+SIOC+SKOS+DC+Schema.org), JSONL→RDF pipeline, Fuseki. Cognee rejected. **Post-mortem: flat tags, no relationships.** |
| 2      | 2026-02-14 | Fixed: `(s,p,o)` triple extraction, 24-predicate vocabulary, Gemini 2.5 Flash, dual storage (direct edges + reified triples). 128 knowledge triples. |
| 2.5    | 2026-02-14 | Wikidata entity linking via `owl:sameAs`. 88% coverage on major dev tools. |
| 3      | 2026-02-14 | Multi-platform parsers (DeepSeek, Grok, Warp), shared `common.py`, retry logic, enhanced entity linking (SQLite cache, batch mode, 31 aliases). |
| 3.5    | 2026-02-14 | Agentic entity linking: LangGraph ReAct agent replaced heuristic. 7/7 precision, resolves abbreviations. |
| 4      | 2026-02-14 | `bulk_process.py` (watermarks, subagent filtering), stopword filter, entity dedup, confidence threshold. E2E: 13 sessions, 7K triples, 420 knowledge triples. |
| 5      | 2026-02-15 | SPARQL skill for Claude Code (14 local + 6 Wikidata templates). 1 tool call replaces 5-10+ grep calls. |
| 6.1    | 2026-02-15 | 6 pre-sprint fixes (subagent dedup, relatedTo overuse, JSON truncation, 161 aliases). 5-model comparison. Claude Vertex AI + Gemini 3 support. Assistant-only extraction. |
| 6.2    | 2026-02-15 | Entity cache wiped (90 bad links from heuristic era). Pipeline flow documented. |
| 6.3    | 2026-02-16 | `bulk_batch.py` — Vertex AI Batch Prediction (submit/status/collect). E2E validated. 50% cost discount. |
| 7      | 2026-02-20 | Context-aware entity linking (KG triple context → ReAct agent). Fixed 8 mislinked entities. `snapshot_links.py`. Hybrid KG+grep skills. 138K triples in Fuseki. |

## Cost Analysis

| Component            | Tool                                                 | Cost           |
| -------------------- | ---------------------------------------------------- | -------------- |
| Graph DB             | Neo4j Community (Docker) or AuraDB Free              | $0             |
| KG framework         | Cognee or Graphiti (open source)                     | $0             |
| Code parsing         | tree-sitter + CodeGraph                              | $0             |
| Conversation parsing | claude-code-log, chatgpt-exporter, cursor-history    | $0             |
| Orchestration        | LangChain + LangGraph                                | $0             |
| Embeddings           | Ollama (nomic-embed-text, local)                     | $0             |
| LLM extraction       | Gemini 2.5 Flash via Vertex AI                       | ~$0.60/600 sessions (batch) |

## Reference Projects

- **GRAPH4CODE** (IBM Research): 2B triples, composes Schema.org + SKOS + PROV-O + SIOC + SIO
- **Cognee repo-to-knowledge-graph**: `cognee.ai/blog/deep-dives/repo-to-knowledge-graph`
- **Graphiti MCP server**: `github.com/getzep/graphiti` (temporal KG for agent memory)
- **Neo4j LLM Knowledge Graph Builder**: Docker-based, extracts KG from PDFs/web/YouTube
- **Zimin Chen's "Building KG over a Codebase for LLM"**: Neo4j + AST nodes + Cypher queries

## Next Steps

1. **P0**: Run full bulk pipeline on remaining sessions (`--sort newest`, incremental via watermarks)
2. **P1**: Reload Fuseki after bulk run, run hub detection + cross-session overlap queries
3. **P2**: Index other platform sessions (DeepSeek, Grok, Warp) into the KG

Neo4j migration and hybrid vector retrieval are out of scope.
