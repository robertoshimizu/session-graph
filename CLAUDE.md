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

## Cost Analysis

| Component            | Tool                                                 | Cost           |
| -------------------- | ---------------------------------------------------- | -------------- |
| Graph DB             | Neo4j Community (Docker) or AuraDB Free              | $0             |
| KG framework         | Cognee or Graphiti (open source)                     | $0             |
| Code parsing         | tree-sitter + CodeGraph                              | $0             |
| Conversation parsing | claude-code-log, chatgpt-exporter, cursor-history    | $0             |
| Orchestration        | LangChain + LangGraph                                | $0             |
| Embeddings           | Ollama (nomic-embed-text, local)                     | $0             |
| LLM extraction       | Ollama (llama3/deepseek, local) or Claude via Vertex | $0 or API cost |

## Reference Projects

- **GRAPH4CODE** (IBM Research): 2B triples, composes Schema.org + SKOS + PROV-O + SIOC + SIO
- **Cognee repo-to-knowledge-graph**: `cognee.ai/blog/deep-dives/repo-to-knowledge-graph`
- **Graphiti MCP server**: `github.com/getzep/graphiti` (temporal KG for agent memory)
- **Neo4j LLM Knowledge Graph Builder**: Docker-based, extracts KG from PDFs/web/YouTube
- **Zimin Chen's "Building KG over a Codebase for LLM"**: Neo4j + AST nodes + Cypher queries

## Sprint 1 Results (2026-02-13)

### What Was Built

- [x] OWL ontology composing PROV-O + SIOC + SKOS + DC + Schema.org → `ontology/devkg.ttl`
- [x] rdflib pipeline: JSONL → RDF Turtle → Fuseki → SPARQL → `pipeline/jsonl_to_rdf.py`
- [x] 3,006 triples loaded into Apache Jena Fuseki (2 sessions, 78 tool calls, 103 topics)
- [x] Cognee evaluation → rejected (no RDF output, slow, ontology mismatch)

### Critical Failure: Flat Tags Instead of Knowledge Triples

The pipeline extracts `["Prolog", "Symbolic AI"]` as independent tags per message. It CANNOT answer relationship questions like "how does Prolog fit into neurosymbolic?" because no `(subject, predicate, object)` triples are stored. **A knowledge graph without relationships is just a tag cloud.**

See `README.md` for full post-mortem, multi-platform assessment, and action items.

### Files (Sprint 1 — superseded by Sprint 2)

```
ontology/devkg.ttl              # OWL ontology (extended in Sprint 2)
pipeline/jsonl_to_rdf.py        # JSONL → RDF (flat tags — FIXED in Sprint 2)
pipeline/load_fuseki.py         # Upload Turtle to Fuseki
pipeline/sample_queries.sparql  # 5 structural SPARQL queries (extended in Sprint 2)
cognee_eval/EVALUATION.md       # Cognee evaluation report
cognee_eval/ingest.py           # Cognee ingestion script
cognee_eval/evaluate.py         # Cognee graph inspection
output/ec11ec1e.ttl             # RDF output (research session, flat tags only)
output/ddxplus.ttl              # RDF output (medical session, flat tags only)
README.md                       # Project documentation (includes Sprint 1 post-mortem)
```

## Sprint 2 Results (2026-02-14)

### What Was Built

- [x] **P0 FIXED**: Replaced flat topic extraction with `(subject, predicate, object)` triple extraction
- [x] **P0 FIXED**: Added 3 semantic verification SPARQL queries (Queries 6-8) as acceptance criteria
- [x] Replaced Ollama llama3 with **Gemini 2.5 Flash on Vertex AI** (uses existing GCP credits)
- [x] Defined **curated predicate vocabulary** (24 OWL ObjectProperties) in ontology
- [x] Ontologist prompt with few-shot examples + closed-world predicate enforcement
- [x] Entity normalization (lowercase, dedup, predicate fuzzy matching)
- [x] Dual storage: direct edges (fast traversal) + reified KnowledgeTriple nodes (provenance)

### Sprint 1 → Sprint 2 Comparison

| Metric                    | Sprint 1 (flat tags)  | Sprint 2 (knowledge triples) |
| ------------------------- | --------------------- | ---------------------------- |
| Total RDF triples         | 3,006 (2 sessions)    | 2,185 (1 session)            |
| Knowledge relationships   | **0**                 | **128**                      |
| Distinct entities         | N/A (flat tags)       | **120**                      |
| Predicates used           | 0                     | **18 of 24**                 |
| "How does X relate to Y?" | **Cannot answer**     | **Works with provenance**    |
| LLM backend               | Ollama llama3 (local) | Gemini 2.5 Flash (Vertex AI) |

### Predicate Distribution

```
19x  uses            9x  hasPart          3x  relatedTo
17x  servesAs        9x  enables          3x  produces
16x  isTypeOf        8x  provides         2x  requires
16x  integratesWith  7x  solves           2x  isPartOf
 6x  deployedOn      4x  alternativeTo    2x  broader
 3x  composesWith    1x  storesIn         1x  queriedWith
```

### Sample Knowledge Triples (impossible in Sprint 1)

```
myconnect      --alternativeTo-->  ngrok
myconnect      --enables-->        healthcare erp integration
myconnect      --solves-->         exposing service behind firewall
myconnect      --uses-->           websocket
rock pi #1     --deployedOn-->     hospital dmz
tunnel         --enables-->        sql queries
tunnel         --integratesWith--> oracle database
oracle database--deployedOn-->     on-premises
ngrok          --enables-->        tunneling local services
```

### Ontology Extension: Curated Predicate Vocabulary

The key design decision: define a **closed-world predicate vocabulary** as first-class OWL ObjectProperties, not ad-hoc strings. The LLM is instructed to use ONLY these predicates. A normalization step maps any LLM-generated predicate to the closest match (fallback: `relatedTo`).

**24 predicates defined**, mapped to standards where possible:

- `devkg:isPartOf` → `rdfs:subPropertyOf dcterms:isPartOf`
- `devkg:hasPart` → `rdfs:subPropertyOf dcterms:hasPart`
- `devkg:broader` → `rdfs:subPropertyOf skos:broader`
- `devkg:narrower` → `rdfs:subPropertyOf skos:narrower`
- `devkg:relatedTo` → `rdfs:subPropertyOf skos:related`
- 19 custom predicates: `uses`, `dependsOn`, `enables`, `implements`, `extends`, `alternativeTo`, `solves`, `produces`, `configures`, `composesWith`, `provides`, `requires`, `isTypeOf`, `builtWith`, `deployedOn`, `storesIn`, `queriedWith`, `integratesWith`, `servesAs`

### New Classes

- `devkg:Entity` (subclass of `prov:Entity`) — extracted technical concepts
- `devkg:KnowledgeTriple` — reified triple for provenance (links to source message + session)

### Files

```
ontology/devkg.ttl              # Extended: +Entity, +KnowledgeTriple, +24 predicates (398 lines)
pipeline/vertex_ai.py           # NEW: Vertex AI auth (base64 creds → temp file → init)
pipeline/triple_extraction.py   # NEW: Ontologist prompt, extraction, normalization (224 lines)
pipeline/jsonl_to_rdf.py        # Refactored: Gemini triples replace Ollama tags (330 lines)
pipeline/load_fuseki.py         # Unchanged
pipeline/sample_queries.sparql  # Extended: +3 semantic queries (Queries 6-8)
requirements.txt                # Updated: +google-cloud-aiplatform, -cognee
output/test_triples.ttl         # Sprint 2 output (2,185 triples)
```

### How to Run

```bash
# Start Fuseki
cd ~/opt/apache-jena-fuseki && ./fuseki-server &

# Full extraction (Gemini 2.5 Flash via Vertex AI)
.venv/bin/python -m pipeline.jsonl_to_rdf <input.jsonl> output/<name>.ttl

# Structure only (no API calls)
.venv/bin/python -m pipeline.jsonl_to_rdf <input.jsonl> output/<name>.ttl --skip-extraction

# Custom model
.venv/bin/python -m pipeline.jsonl_to_rdf <input.jsonl> output/<name>.ttl --model gemini-2.5-pro

# Load into Fuseki
.venv/bin/python pipeline/load_fuseki.py output/<name>.ttl

# Query at http://localhost:3030
```

### Verification Queries (Queries 6-8)

```sparql
# Query 6: What relationships exist for entity X?
# → Returns all predicates + objects for a given entity, with source message provenance

# Query 7: How does entity X relate to entity Y?
# → Returns predicates connecting two specific entities, with source text

# Query 8: Entity co-occurrence
# → Counts how often entity pairs appear together across triples
```

### Known Issues

- ~5% of Gemini responses truncate mid-JSON (long outputs) — extraction gracefully returns `[]`. A retry mechanism would help.
- `vertexai` SDK deprecation warning (cosmetic, won't affect until June 2026)
- Some noisy entities slip through (`/exit`, `command name`) — could add a stopword filter

## Sprint 2.5 Results (2026-02-14): Wikidata Entity Linking

### What Was Built

- [x] **Comprehensive Wikidata research** (`research/wikidata_entity_linking_research.md`)
  - API documentation (wbsearchentities, wbgetentities, SPARQL)
  - Coverage analysis (8/9 major developer tools found in Wikidata)
  - Python library comparison (qwikidata, WikidataIntegrator, spaCyOpenTapioca)
  - Integration architecture (post-processing vs real-time)
  - Rate limits and best practices

- [x] **Entity linking script** (`pipeline/link_entities.py`)
  - Wikidata search API integration (qwikidata + direct API calls)
  - Tech keyword disambiguation heuristic (prefers software/database/framework in description)
  - RDF output with owl:sameAs triples
  - Rate limiting (1 req/sec + User-Agent header)

- [x] **Proof of concept validated** (3/3 entities successfully linked)

**Test Results:**

```
Neo4j    → Q1628290 ✅ (graph database management system implemented in Java)
Python   → Q28865 ✅ (general-purpose programming language)
React    → Q19399674 ✅ (JavaScript library for building user interfaces)
```

**Ambiguity Detection Working:**

- Neo4j: 4 candidates → selected Q1628290 (database), not Q107381824 (Python library)
- React: 2 candidates → selected Q19399674 (JS library), not Q2134522 (chemical)

### Wikidata Coverage Assessment

| Entity                 | QID        | Status  | Description                                                            |
| ---------------------- | ---------- | ------- | ---------------------------------------------------------------------- |
| **Neo4j**              | Q1628290   | ✅      | graph database management system implemented in Java                   |
| **Kubernetes**         | Q22661306  | ✅      | software to manage containers on a server-cluster                      |
| **Visual Studio Code** | Q19841877  | ✅      | source code editor developed by Microsoft                              |
| **FastAPI**            | Q101119404 | ✅      | software framework for developing web applications in Python           |
| **Pydantic**           | Q107381687 | ✅      | Python library for data parsing and validation using Python type hints |
| **Apache Jena**        | Q1686799   | ✅      | open source semantic web framework for Java                            |
| **SPARQL**             | Q54871     | ✅      | RDF query language                                                     |
| **Supabase**           | Q136776342 | ✅      | open source backend platform for app development                       |
| **Docker**             | ❌         | Missing | (returns "stevedore" occupation instead)                               |

**Coverage:** 88% of major developer tools

### Example RDF Output

```turtle
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix devkg: <http://devkg.local/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wd: <http://www.wikidata.org/entity/> .

devkg:Neo4j rdfs:label "Neo4j"@en ;
    dcterms:description "graph database management system implemented in Java"@en ;
    owl:sameAs wd:Q1628290 .
```

### Usage

```bash
# Create entity list
cat > entities.txt <<EOF
Neo4j
Kubernetes
Visual Studio Code
EOF

# Run linking
python pipeline/link_entities.py entities.txt output.ttl

# Load into Fuseki
python pipeline/load_fuseki.py output.ttl
```

### Files

```
research/wikidata_entity_linking_research.md  # Full research (16,000+ words)
research/IMPLEMENTATION_SUMMARY.md            # Quick reference guide
pipeline/link_entities.py                     # Entity linking script
test/quick_links.ttl                           # Validated RDF output
```

---

## Sprint 3 Results (2026-02-14): Multi-Platform Pipeline + Entity Linking

### What Was Built

- [x] **Ontology extensions**: `devkg:Project`, `devkg:hasSourceFile`, `devkg:belongsToProject`, `devkg:hasWorkingDirectory`
- [x] **Shared module** (`pipeline/common.py`, 219 lines): Namespace constants, URI helpers, RDF node builders — used by all 5 parsers
- [x] **DeepSeek parser** (`pipeline/deepseek_to_rdf.py`, 370 lines): JSON zip with tree-structured mapping
- [x] **Grok parser** (`pipeline/grok_to_rdf.py`, 267 lines): MongoDB JSON with `$date.$numberLong` timestamps
- [x] **Warp parser** (`pipeline/warp_to_rdf.py`, 313 lines): SQLite with `ai_queries` table. Only useful when sessions have bulk content; most Warp AI sessions are too thin (user queries only, no assistant responses stored)
- [x] **Retry logic** in `triple_extraction.py`: MAX_RETRIES=2, shorter input on retry
- [x] **Enhanced entity linking** (`pipeline/link_entities.py`, 422 lines): SQLite cache, batch mode from .ttl files, 31 alias mappings
- [x] **Batch extraction skeleton** (`pipeline/batch_extraction.py`, 252 lines): Gemini Batch Prediction via GCS
- [x] **Automation skeletons**: `hooks/post_session_hook.sh`, `daemon/sync_daemon.py`
- [x] **SPARQL queries 9-14**: Cross-platform verification
- [x] **Refactored `jsonl_to_rdf.py`**: imports from common.py, hasSourceFile + Project detection

### Integration Results

| Platform    | Messages | Knowledge Triples | Notes                         |
| ----------- | -------- | ----------------- | ----------------------------- |
| Claude Code | 55       | 180               | Full session with tool calls  |
| DeepSeek    | 8        | 111               | MCP integration conversation  |
| Grok        | 14       | 165               | Medical diagnosis logic       |
| Warp        | 12       | 3                 | User queries only (thin data) |

- **7,462 total RDF triples** loaded in Fuseki
- **233 Wikidata owl:sameAs links** (51.8% of 450 entities)
- **8 cross-platform entities**: api, server, python, database, client, http, go, db
- **Federated SPARQL → Wikidata** verified working (e.g., "What is Python?" returns Wikidata description + local KG relationships)

### Agentic Entity Linking (Sprint 3.5)

Replaced naive heuristic entity linker with **ReAct agent** using LLM + Wikidata API tool:

| Approach            | Precision | Avg Latency | Notes                                  |
| ------------------- | --------- | ----------- | -------------------------------------- |
| Heuristic (old)     | ~50%      | <1s         | Keyword matching, many false positives |
| Agentic (ADK)       | 7/7       | 4.7s        | Google ADK, text parsing (fragile)     |
| Agentic (LangGraph) | 7/7       | 4.3s        | LangGraph + structured output (robust) |

**Winner: LangGraph** — same precision as ADK, but native structured output (`response_format=WikidataMatch`) eliminates parsing failures. In fair ceteris paribus test, ADK failed 3/7 due to regex parsing of free-text output.

Key capability: **ReAct loop resolves abbreviations and synonyms**:

- "apis" → searches "application programming interface" → Q165194 ✅
- "k8s" → searches "kubernetes" → Q22661306 ✅
- "js" → searches "javascript" → Q2005 ✅
- "agent" → searches "software agent" → Q2297769 ✅

### Files Created/Modified (Sprint 3)

```
ontology/devkg.ttl                    # +Project, hasSourceFile, belongsToProject, hasWorkingDirectory
pipeline/common.py                    # NEW: shared RDF logic (219 lines)
pipeline/jsonl_to_rdf.py              # Refactored: imports common.py, +hasSourceFile, +Project
pipeline/deepseek_to_rdf.py           # NEW: DeepSeek parser (370 lines)
pipeline/grok_to_rdf.py               # NEW: Grok parser (267 lines)
pipeline/warp_to_rdf.py               # NEW: Warp parser (313 lines)
pipeline/cursor_to_rdf.py             # NEW: Cursor parser (246 lines) — NOT integrated, see Sprint 4
pipeline/triple_extraction.py         # +retry logic (MAX_RETRIES=2)
pipeline/link_entities.py             # Enhanced: SQLite cache, batch mode, aliases
pipeline/entity_aliases.json          # NEW: 31 tech synonym mappings
pipeline/batch_extraction.py          # NEW: Gemini batch prediction (252 lines)
pipeline/sample_queries.sparql        # +Queries 9-14
pipeline/agentic_linker.py            # NEW: single-shot Gemini linker (prototype)
pipeline/agentic_linker_adk.py        # NEW: Google ADK ReAct agent (317 lines)
pipeline/agentic_linker_langgraph.py  # NEW: LangGraph ReAct agent (307 lines) — WINNER
hooks/post_session_hook.sh            # NEW: automation skeleton
daemon/sync_daemon.py                 # NEW: watchdog file watcher
daemon/watermarks.json                # NEW: tracking state
requirements.txt                      # +qwikidata, google-cloud-storage, watchdog
output/claude_sample.ttl              # Sprint 3 output
output/deepseek_sample.ttl            # Sprint 3 output
output/grok_sample.ttl                # Sprint 3 output
output/warp_sample.ttl                # Sprint 3 output
output/wikidata_links.ttl             # Sprint 3 entity links
```

### How to Run

```bash
# Start Fuseki
cd ~/opt/apache-jena-fuseki && ./fuseki-server &

# Run parsers (1 conversation each)
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/claude_sample.ttl
.venv/bin/python -m pipeline.deepseek_to_rdf external_knowledge/deepseek_data-2026-01-28.zip output/deepseek_sample.ttl --conversation 0
.venv/bin/python -m pipeline.grok_to_rdf external_knowledge/grok_data-2026-01-28.zip output/grok_sample.ttl --conversation 0
.venv/bin/python -m pipeline.warp_to_rdf output/warp_sample.ttl --conversation 0

# Entity linking (batch across all outputs)
.venv/bin/python -m pipeline.link_entities --input output/*_sample.ttl --output output/wikidata_links.ttl

# Load into Fuseki
.venv/bin/python pipeline/load_fuseki.py output/*_sample.ttl output/wikidata_links.ttl

# Agentic linker (LangGraph)
.venv/bin/python pipeline/agentic_linker_langgraph.py
```

---

## Sprint 4 Results (2026-02-14): Agentic Linker Integration + Bulk Pipeline

### What Was Built

- [x] **P0 DONE**: Integrated LangGraph ReAct agent into `link_entities.py` — replaces heuristic `select_best_match()` with LLM-powered disambiguation. `--heuristic` flag preserved as fallback.
- [x] **P0 DONE**: Bulk processing script (`pipeline/bulk_process.py`) — finds all `~/.claude/projects/**/*.jsonl`, runs parse+extract+link. SHA256 content hashing for watermarks (skip already-processed). CLI: `--dry-run`, `--limit N`, `--skip-linking`, `--force`.
- [x] **P1 DONE**: Stopword filter in `triple_extraction.py` — rejects single chars, paths (`/exit`), dimension strings (`1400px`), generic noise (`command name`, `exit`). Applied in `_parse_triples_response()`.
- [x] **P1 DONE**: Entity deduplication — post-processing in `link_entity_list()`: entities sharing the same Wikidata QID get `owl:sameAs` to each other (e.g., `medication` == `medicamento` via Q12140).
- [x] **P1 DONE**: Confidence threshold `CONFIDENCE_THRESHOLD = 0.7` — only emits `owl:sameAs` for high-confidence matches. Low-confidence logged to stderr.
- [x] **Dropped**: Cursor parser deleted (`pipeline/cursor_to_rdf.py`) — unmaintained CLI, low value.
- [x] **Done**: Warp quality filter — `--min-exchanges N` (default: 5) and `--min-triples N` (default: 1) flags in `warp_to_rdf.py`.
- [x] **Dependencies**: Added `langchain-google-genai`, `langgraph`, `pydantic` to `requirements.txt`.

### E2E Pipeline Test (13 Sessions)

| Metric                      | Value                      |
| --------------------------- | -------------------------- |
| Sessions processed          | 13 (8 unique + 5 subagent) |
| Total RDF triples in Fuseki | 7,181                      |
| Entities                    | 360                        |
| Knowledge triples           | 420 (413 unique)           |
| Wikidata owl:sameAs links   | 120 (33% link rate)        |
| Deduplicated entity pairs   | 19                         |
| Low-confidence rejected     | 4                          |
| Predicates used             | 20 of 24                   |

### What Worked Well

- Stopword filter correctly rejected non-entities (`/exit`, `1400px+ width`, single letters)
- Confidence threshold (0.7) filtered noise like `hardcoding token value` → Q631425 (conf=0.60)
- Entity deduplication caught 19 pairs (e.g., `medication` == `medicamento` via same QID Q12140, `otel` == `opentelemetry` via Q121746046)
- SHA256 watermarks prevent reprocessing on re-runs
- Agentic linker resolves abbreviations: `otel` → OpenTelemetry, `npm` → Q7067518

### Known Issues

- **76% knowledge triple duplication** from subagent files sharing parent session content — subagent `.jsonl` files contain overlapping context with their parent session. Needs subagent deduplication logic (skip subagent files, or detect parent session overlap).
- **`GOOGLE_API_KEY` warning floods stderr** — cosmetic, from `langchain-google-genai` creating fresh model instances per entity. Could suppress with `warnings.filterwarnings`.
- **33% Wikidata link rate** — many extracted entities are domain-specific (medical terms in Portuguese, internal config paths) that don't exist in Wikidata. Expected for a personal KG.

### Files Created/Modified (Sprint 4)

```
pipeline/bulk_process.py          # NEW: bulk session processor (watermarks, --dry-run, --limit)
pipeline/triple_extraction.py     # +STOPWORDS set, +is_valid_entity(), filter in _parse_triples_response()
pipeline/link_entities.py         # +agentic mode (LangGraph), +confidence threshold, +entity dedup, +--heuristic flag
pipeline/warp_to_rdf.py           # +--min-exchanges, +--min-triples quality filters
pipeline/common.py                # Removed Cursor from docstring
pipeline/cursor_to_rdf.py         # DELETED
requirements.txt                  # +langchain-google-genai, langgraph, pydantic
output/claude/*.ttl               # 13 session outputs + wikidata_links.ttl
output/claude/watermarks.json     # SHA256 hashes for processed sessions
```

### How to Run

```bash
# Start Fuseki
cd ~/opt/apache-jena-fuseki && ./fuseki-server &

# Bulk process (all sessions)
.venv/bin/python -m pipeline.bulk_process

# Bulk process (limited, dry-run)
.venv/bin/python -m pipeline.bulk_process --dry-run
.venv/bin/python -m pipeline.bulk_process --limit 10

# Entity linking only (agentic, default)
.venv/bin/python -m pipeline.link_entities --input output/claude/*.ttl --output output/claude/wikidata_links.ttl

# Entity linking (heuristic fallback)
.venv/bin/python -m pipeline.link_entities --heuristic --input output/claude/*.ttl --output output/claude/wikidata_links.ttl

# Load into Fuseki
.venv/bin/python pipeline/load_fuseki.py output/claude/*.ttl

# Warp with quality filter
.venv/bin/python -m pipeline.warp_to_rdf output/warp.ttl --conversation 0 --min-exchanges 5
```

---

## Sprint 5 Results (2026-02-15): DevKG SPARQL Skill + Wikidata Traversal

### What Was Built

- [x] **SPARQL skill** (`.claude/skills/devkg-sparql/SKILL.md`, 611 lines) — teaches Claude Code to query Fuseki via SPARQL instead of grepping raw JSONL files
- [x] **14 local graph query templates**: entity lookup (with provenance), entity-to-entity, predicate search, session listing, topic search, cross-platform overlap, Wikidata enrichment, full-text search, 2-hop neighborhood, hub detection, cross-session overlap, path discovery, project knowledge map, sibling entities
- [x] **6 Wikidata traversal templates** (W1-W6): entity properties, peer discovery, disambiguation, category hierarchy, relationship bridge, batch enrichment
- [x] **Fosfomycin Wikidata link fixed**: was incorrectly linked to Q421268 (tubocurarine), corrected to Q183554 (fosfomycin) via SPARQL UPDATE
- [x] **`.gitignore` updated**: `.claude/*` with `!.claude/skills/` exception to track skills in git

### Key Design Decisions

- **Provenance in every query**: Templates 1 and 5 include `sourceFile`, `platform`, and content snippet so the agent can trace back to the original document
- **Bidirectional traversal**: Template 1 uses UNION to search both outbound and inbound edges (relationships may be stored in either direction)
- **`FILTER(LANG(?label) = "")` everywhere**: Avoids duplicate rows from lang-tagged vs untagged literals (data quality issue from earlier sprints)
- **Wikidata as enrichment layer**: local KG knows dosing protocols and integrations; Wikidata knows drug classifications, software ecosystems, and peer alternatives. The skill teaches a Local→Wikidata→Back workflow.
- **Multi-line `--data-urlencode` with double quotes**: avoids shell escaping issues with `!=` and `""` in SPARQL operators

### Comparison: SPARQL vs Grep

| Metric                 | SPARQL (new) | Grep (old) |
| ---------------------- | ------------ | ---------- |
| Tool calls             | **1**        | 5-10+      |
| Token consumption      | **~2K**      | 50K-350K   |
| Relationship questions | **Yes**      | **No**     |
| Cross-platform queries | **Yes**      | No         |
| Provenance tracking    | **Yes**      | Manual     |
| Wikidata enrichment    | **Yes**      | No         |

### Graph Traversal Examples Validated

- **2-hop**: `warp plugin --uses--> warp native notification system --uses--> osc 777 escape sequences`
- **Hub detection**: `suggestion mode` (69 edges), `claude code` (22), `excel spreadsheet` (18)
- **Siblings**: fosfomycin → nitrofurantoin, phenazopyridine (share `isTypeOf medication`, `servesAs outpatient treatment`)
- **Wikidata enrichment**: nitrofurantoin local (dosing) + Wikidata (ATC code J01XE01, treats UTI, cystitis, gram-negative)

### Files Created/Modified

```
.claude/skills/devkg-sparql/SKILL.md  # NEW: SPARQL skill (611 lines, 14 local + 6 Wikidata templates)
.gitignore                            # Updated: .claude/* with !.claude/skills/ exception
```

### Data Fixes

- Fosfomycin `owl:sameAs` corrected: Q421268 (tubocurarine) → Q183554 (fosfomycin) via SPARQL UPDATE on Fuseki
- Total triples in Fuseki: 7,183

---

## Sprint 6 Session 1 (2026-02-15): Pre-Sprint Fixes + Model Comparison

### What Was Done (Previous Session — NOT YET COMMITTED)

6 pre-sprint fixes (built by a team of agents):

- Subagent dedup in `bulk_process.py` — 998 files filtered
- `relatedTo` overuse — prompt guide + wrong/correct examples → 10% → 0.3%
- Gemini JSON truncation — `max_output_tokens` 4096→8192, salvage partial triples
- Wikidata aliases — 31→161 mappings in `entity_aliases.json`
- API key warning suppression + model singleton in `agentic_linker_langgraph.py`
- Pipeline readiness verified — 594 sessions, ~$6.77 estimated cost

3 bugs found and fixed during testing:

- Entity boundaries — prompt enforces 1-3 words, `is_valid_entity()` rejects 4+
- Agent hallucinating QIDs — upgraded gemini-2.5-flash-lite → gemini-2.5-flash, added "only return QIDs from search results" rules
- Cache corruption — cleaned false matches, removed orphaned transformers package, added singleton for Vertex AI init

### What Was Done (This Session)

1. **Assistant-only extraction** — `jsonl_to_rdf.py` now only sends assistant messages to Gemini (user messages are short prompts, assistant messages contain the actual knowledge analysis). Line 210: `entry_type == "assistant"` guard added.

2. **5-model comparison** on enterprise-ontology session (79 assistant messages):

| Model                  | Triples | Predicates | relatedTo | Verdict                         |
| ---------------------- | ------- | ---------- | --------- | ------------------------------- |
| **Gemini 2.5 Flash**   | **142** | **15**     | 1 (0.7%)  | **Best overall**                |
| Gemini 3 Flash Preview | 123     | 18         | 2 (1.6%)  | Close second, widest vocab      |
| Gemini 2.5 Flash-Lite  | 109     | 13         | 12 (11%)  | Noisy                           |
| Claude Haiku 4.5       | 37      | 9          | 0         | High precision, terrible recall |
| Gemini 2.0 Flash       | 30      | 10         | 3 (10%)   | Poor                            |

Key finding: only 20% triple overlap between models — extraction is highly model-dependent.

3. **Claude Vertex AI support** — Added `ClaudeModelWrapper` in `vertex_ai.py` wrapping `AnthropicVertex` client to match Gemini's `generate_content()` interface. Usage: `--model claude-haiku-4-5@20251001`

4. **Gemini 3 Flash Preview support** — Requires `global` endpoint (not regional). Added `_GLOBAL_ONLY_MODELS` set and auto re-init with `location="global"` in `get_gemini_model()`.

5. **Entity linking test** — Cache working correctly (all 241 entities served from SQLite cache for previously seen entities, agentic LLM calls only for new ones). Fixed region mismatch: `agentic_linker_langgraph.py` was using `CLOUD_ML_REGION`/`us-east5`, changed to `VERTEX_AI_LOCATION`/`us-central1`.

### Known Issues / Broken State

- **Entity linking output buffering** — `link_entities.py` output doesn't appear when piped. Fix: use `PYTHONUNBUFFERED=1` env var when running.
- **Cache quality concerns** — Some cached Wikidata links are questionable: `agent` → Q37281213 (family name), `astrobee` → Q63976358 (ISS robot, not the data company). Consider cache cleanup or re-linking with stricter context.
- **`vertexai` SDK deprecation warning** — cosmetic, won't affect until June 2026.
- **Previous session's 6 fixes are NOT committed** — need to commit before further changes.

### Files Modified (This Session)

```
pipeline/jsonl_to_rdf.py              # +assistant-only extraction filter (line 210)
pipeline/vertex_ai.py                 # +ClaudeModelWrapper, +get_claude_model(), +_GLOBAL_ONLY_MODELS, +global endpoint re-init
pipeline/agentic_linker_langgraph.py  # Fixed: CLOUD_ML_REGION → VERTEX_AI_LOCATION for region
requirements.txt                      # +anthropic[vertex] (needs adding)
output/test_run/                      # Test outputs (enterprise_ontology.ttl, slack_tmux.ttl, enterprise_flash_lite.ttl, enterprise_haiku.ttl, enterprise_gemini3_flash.ttl)
```

### How to Run Model Comparison

```bash
# Default (gemini-2.5-flash)
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl

# Flash-Lite (cheaper, noisier)
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl --model gemini-2.5-flash-lite

# Gemini 3 Flash Preview (needs global endpoint)
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl --model gemini-3-flash-preview

# Claude Haiku 4.5 via Vertex AI (needs us-east5)
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl --model claude-haiku-4-5@20251001

# Entity linking (use PYTHONUNBUFFERED=1 to see progress)
PYTHONUNBUFFERED=1 .venv/bin/python -m pipeline.link_entities --input output/*.ttl --output output/wikidata_links.ttl
```

---

## Pipeline Flow (Current)

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

  bulk_process.py
  ├── Finds all ~/.claude/projects/**/*.jsonl
  ├── Filters out subagent files (avoids duplicate triples)
  ├── SHA256 watermarks → skip already-processed sessions
  ├── For each new session:
  │   ├── Step 1: jsonl_to_rdf.py → output/claude/<session>.ttl
  │   └── Step 2: link_entities.py → output/claude/wikidata_links.ttl
  └── CLI: --dry-run, --limit N, --skip-linking, --force


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

### How to Run (Full Pipeline)

```bash
# Start Fuseki
cd ~/opt/apache-jena-fuseki && ./fuseki-server &

# Option A: Bulk process all Claude Code sessions
.venv/bin/python -m pipeline.bulk_process

# Option B: Single session
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl

# Option C: Other platforms (run individually)
.venv/bin/python -m pipeline.deepseek_to_rdf external_knowledge/deepseek_data.zip output/deepseek.ttl --conversation 0
.venv/bin/python -m pipeline.grok_to_rdf external_knowledge/grok_data.zip output/grok.ttl --conversation 0
.venv/bin/python -m pipeline.warp_to_rdf output/warp.ttl --conversation 0 --min-exchanges 5

# Entity linking (all outputs)
PYTHONUNBUFFERED=1 .venv/bin/python -m pipeline.link_entities --input output/*.ttl --output output/wikidata_links.ttl

# Load into Fuseki
.venv/bin/python pipeline/load_fuseki.py output/*.ttl
```

---

## Sprint 6 Session 2 (2026-02-15): Cache Cleanup + Pipeline Docs

### What Was Done

1. **Verified entity linking works** — tested 4 entities (neo4j, k8s, react, agent), all resolved correctly with confidence 1.0 via agentic linker (Gemini 2.5 Flash)
2. **Inspected entity cache** — found 1,328 entries, ~90 with bad links from old heuristic linker (caching→animal behavior, rock pi→pigeon, ecs→endocannabinoid system, etc.)
3. **Wiped entity cache** — deleted `.entity_cache.db` for clean start with agentic linker only
4. **Documented pipeline flow** — added full pipeline flow diagram to CLAUDE.md

### Files Modified

```
CLAUDE.md                          # +Pipeline Flow section, +Sprint 6 Session 2 progress
pipeline/.entity_cache.db          # DELETED (wiped for clean re-linking)
```

---

## Sprint 6 Session 3 (2026-02-16): Batch Pipeline via Vertex AI Batch Prediction API

### What Was Built

- [x] **`pipeline/bulk_batch.py`** (~350 lines) — 3-subcommand batch pipeline: `submit` → `status` → `collect`
- [x] **GCS bucket** `gs://devkg-batch-predictions` created in `us-central1`
- [x] **`output/batch_jobs/.gitkeep`** — directory for job manifests

### E2E Test (1 session, 13 messages)

| Step | Result |
|------|--------|
| `submit --limit 2` | 13 messages → GCS → Vertex AI batch job |
| `status --wait` | PENDING → QUEUED → RUNNING → SUCCEEDED (~8.5 min) |
| `collect` | 150 knowledge triples, 131 entities → `.ttl` |
| Entity linking | 62/130 linked (47.7%), 11 dedup pairs |
| Fuseki load | 2,457 triples |

### Bugs Found and Fixed

1. **Metadata serialization** — Vertex AI Batch Prediction rejects nested JSON objects in metadata field. Fixed: serialize metadata dict to JSON string, deserialize on collect.
2. **`poll_job` state enum mismatch** — `str(job.state)` returned raw int (e.g., `"5"`) not enum name. `"SUCCEEDED" in "5"` never matched → infinite polling. Fixed: use `job.state.value` with numeric comparison against `JobState` enum values.

### Scale Estimate for Full Run

| Metric | Value |
|--------|-------|
| Total sessions (excl. subagents) | 610 |
| Already watermarked | 10 |
| Pending | 600 |
| Est. assistant messages | ~6,060 |
| Est. batch JSONL size | ~18 MB (limit: 10 GB) |
| Largest session | 36 MB JSONL → 41 assistant messages |

### Critical Analysis: Ready for Full Run?

**Go / No-Go Assessment:**

| Concern | Status | Detail |
|---------|--------|--------|
| Batch API works | ✅ | Tested E2E with real data |
| Metadata serialization | ✅ | Fixed (JSON string) |
| State polling | ✅ | Fixed (numeric enum) |
| Subagent filtering | ✅ | 1,022 subagents filtered |
| Empty sessions | ✅ | `build_graph` handles gracefully (34 structural triples) |
| Large sessions (36MB) | ✅ | Only 41 assistant messages, text truncated to 1500 chars |
| Batch size limits | ✅ | 18 MB << 10 GB limit |
| `max_output_tokens` | ✅ | Set to 8192 (was 4096 in old `batch_extraction.py`) |
| Collect idempotency | ⚠️ | **Watermarks updated per-session during collect — if collect crashes mid-way, partial progress is saved but batch output must be re-downloaded** |
| Entity linking at scale | ⚠️ | **~6K entities × ~5s/entity = ~8 hours for agentic linking. Consider `--skip-linking` on first run, link separately.** |
| Cost | ✅ | Batch API = 50% discount. ~6K requests × $0.0001 ≈ $0.60 |

**Recommendation:** Ready for full run. Use `submit` without `--limit`, then `status --wait`, then `collect` (without `--link` first). Run entity linking separately after.

### Files Created/Modified

```
pipeline/bulk_batch.py             # NEW: 3-subcommand batch pipeline (~350 lines)
pipeline/batch_extraction.py       # MODIFIED: fixed poll_job state enum handling
output/batch_jobs/.gitkeep         # NEW: directory for manifests
output/batch_jobs/20260215_*.json  # Test manifests (2 runs)
```

### How to Run (Full Pipeline)

```bash
# 1. Submit all 600 sessions
.venv/bin/python -m pipeline.bulk_batch submit

# 2. Wait for completion (~10-20 min for batch)
.venv/bin/python -m pipeline.bulk_batch status --wait --poll-interval 60

# 3. Collect results (without entity linking)
.venv/bin/python -m pipeline.bulk_batch collect

# 4. Entity linking (separate, slower step)
PYTHONUNBUFFERED=1 .venv/bin/python -m pipeline.link_entities \
  --input output/claude/*.ttl --output output/claude/wikidata_links.ttl

# 5. Load into Fuseki
.venv/bin/python pipeline/load_fuseki.py output/claude/*.ttl
```

---

## Next Steps

1. **P0**: Commit all Sprint 6 changes
2. **P0**: Run full batch pipeline (600 sessions)
3. **P1**: Entity linking on all extracted entities
4. **P1**: Load everything into Fuseki, run hub detection + cross-session overlap queries

Neo4j migration and hybrid vector retrieval are out of scope.
