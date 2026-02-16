# Dev Knowledge Graph (DevKG)

A unified developer knowledge graph that extracts structured `(subject, predicate, object)` triples from AI-assisted coding sessions across multiple platforms, enabling relationship queries like "how does X relate to Y?" with full provenance tracking.

---

## Table of Contents

- [Project Goal](#project-goal)
- [Architecture](#architecture)
- [How to Run](#how-to-run)
- [Project Structure](#project-structure)
- [Sprint 1 — Structural Pipeline (2026-02-13)](#sprint-1--structural-pipeline-2026-02-13)
- [Sprint 2 — Knowledge Triple Extraction (2026-02-14)](#sprint-2--knowledge-triple-extraction-2026-02-14)
- [Multi-Platform Assessment](#multi-platform-assessment)
- [Entity Disambiguation Strategy](#entity-disambiguation-strategy)
- [Ontology Reference](#ontology-reference)
- [Sprint 5 — SPARQL Skill + Wikidata Traversal (2026-02-15)](#sprint-5--sparql-skill--wikidata-traversal-2026-02-15)
- [Sprint 6 — Batch Pipeline + Scale Preparation (2026-02-15/16)](#sprint-6--batch-pipeline--scale-preparation-2026-02-1516)
- [Parking Lot](#parking-lot)
- [Lessons Learned](#lessons-learned)

---

## Project Goal

Build a unified developer knowledge graph that connects scattered knowledge from:
- **Claude Code** session logs (`~/.claude/projects/**/*.jsonl`)
- **Cursor AI** sessions (SQLite at `~/Library/Application Support/Cursor/`)
- **Warp** terminal AI sessions (SQLite at `~/Library/Group Containers/.../warp.sqlite`)
- **VS Code Copilot** chat sessions (JSON files in `workspaceStorage/`)
- **ChatGPT**, **Grok**, **DeepSeek** conversation exports

The system enables **chatting with your entire knowledge base** — self-hosted, private, and model-agnostic.

---

## Architecture

```
Scattered Sources               Adapter Layer              Knowledge Graph
-----------------               -------------              ---------------
Claude Code JSONL  --+
ChatGPT JSON       --+
Cursor SQLite      --+-->  Per-platform   -->  Gemini 2.5    -->  Fuseki
Warp SQLite        --+     parser              Flash             (SPARQL)
VS Code JSON       --+     (normalize to       (triple            |
Grok JSON          --+      common schema)      extraction)        |
DeepSeek JSON      --+                                             v
                                                          Wikidata/DBpedia
                                                          (entity linking
                                                           via owl:sameAs)
                                                                   |
                                                                   v
                                                          Hybrid Retrieval
                                                      (SPARQL + Vector search)
```

### Ontology Stack

Five W3C/ISO standards composed, plus a curated DevKG predicate vocabulary:

| Standard | Role | Maturity |
|---|---|---|
| **PROV-O** | Provenance: who did what, when, derived from what | W3C Recommendation |
| **SIOC** | Conversation: messages, threads, containers | W3C Member Submission |
| **SKOS** | Taxonomy: topics, broader/narrower hierarchies | W3C Recommendation |
| **Dublin Core** | Metadata: dates, titles, creators | ISO Standard |
| **Schema.org** | Cherry-pick: `SoftwareSourceCode` | De facto standard |
| **DevKG** | 24 curated predicates for developer knowledge relationships | Custom OWL |

### Dual Storage Pattern

Every extracted relationship is stored two ways:

1. **Direct edge** — `data:entity/fastapi devkg:uses data:entity/pydantic` (fast traversal)
2. **Reified KnowledgeTriple** — links back to source message and session (provenance)

This enables both "what does FastAPI use?" (single hop) and "where did we learn FastAPI uses Pydantic?" (provenance join).

---

## How to Run

### Prerequisites

- Python 3.11+ with virtualenv
- Google Cloud service account with Vertex AI access
- Apache Jena Fuseki (for SPARQL queries)

### Setup

```bash
cd /Users/robertoshimizu/GitRepo/Hacks/claude_hacks/dev-knowledge-graph

# Create virtualenv
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure .env with Vertex AI credentials
# GOOGLE_APPLICATION_CREDENTIALS_BASE64=<base64-encoded-service-account-json>
# GOOGLE_CLOUD_PROJECT=<your-project-id>
```

### Run Pipeline (Single Session)

```bash
# Full extraction (Gemini 2.5 Flash)
.venv/bin/python -m pipeline.jsonl_to_rdf <input.jsonl> output/<name>.ttl

# Skip extraction (structure only — no API calls)
.venv/bin/python -m pipeline.jsonl_to_rdf <input.jsonl> output/<name>.ttl --skip-extraction
```

### Run Pipeline (Batch — All Sessions, 50% Cost Reduction)

```bash
# Step 1: Submit all unprocessed sessions to Vertex AI Batch Prediction
.venv/bin/python -m pipeline.bulk_batch submit

# Step 2: Wait for completion (~10-20 min)
.venv/bin/python -m pipeline.bulk_batch status --wait --poll-interval 60

# Step 3: Collect results → RDF Turtle files
.venv/bin/python -m pipeline.bulk_batch collect

# Step 4: Entity linking (Wikidata, separate step)
PYTHONUNBUFFERED=1 .venv/bin/python -m pipeline.link_entities \
  --input output/claude/*.ttl --output output/claude/wikidata_links.ttl

# Step 5: Load into Fuseki
.venv/bin/python pipeline/load_fuseki.py output/claude/*.ttl
```

### Run Pipeline (Synchronous — One-at-a-Time)

```bash
# Processes sessions sequentially with real-time Gemini calls
.venv/bin/python -m pipeline.bulk_process --limit 10
```

### Load into Fuseki

```bash
# Start Fuseki
cd ~/opt/apache-jena-fuseki && ./fuseki-server &

# Load Turtle files
.venv/bin/python pipeline/load_fuseki.py output/*.ttl

# Query at http://localhost:3030
```

---

## Project Structure

```
dev-knowledge-graph/
├── CLAUDE.md                        # Project instructions for Claude Code
├── README.md                        # This file
├── DEVKG_ONTOLOGY.md                # Full ontology reference (classes, predicates, examples)
├── requirements.txt                 # Python dependencies
├── .env                             # Vertex AI credentials (not committed)
│
├── ontology/
│   ├── devkg.ttl                    # OWL ontology (398 lines, 24 predicates)
│   ├── devkg_schema.dot             # Graphviz source
│   ├── devkg_schema.png             # Schema diagram (PNG)
│   └── devkg_schema.svg             # Schema diagram (SVG)
│
├── pipeline/
│   ├── vertex_ai.py                 # Vertex AI auth (base64 credentials → temp file)
│   ├── triple_extraction.py         # Ontologist prompt + Gemini extraction + normalization
│   ├── jsonl_to_rdf.py              # Claude Code JSONL → RDF Turtle (main pipeline)
│   ├── bulk_process.py              # Synchronous bulk processing (all sessions)
│   ├── bulk_batch.py                # Batch pipeline via Vertex AI Batch Prediction API
│   ├── batch_extraction.py          # Batch prediction helpers (GCS upload, job polling)
│   ├── link_entities.py             # Wikidata entity linking (agentic LangGraph)
│   ├── agentic_linker_langgraph.py  # ReAct agent for entity disambiguation
│   ├── common.py                    # Shared RDF logic (namespaces, URI helpers)
│   ├── deepseek_to_rdf.py           # DeepSeek JSON → RDF
│   ├── grok_to_rdf.py               # Grok JSON → RDF
│   ├── warp_to_rdf.py               # Warp SQLite → RDF
│   ├── load_fuseki.py               # Upload Turtle to Fuseki
│   ├── entity_aliases.json          # 161 tech synonym mappings
│   └── sample_queries.sparql        # 14 SPARQL queries (structural + semantic)
│
├── external_knowledge/
│   ├── deepseek_data-2026-01-28.zip # DeepSeek export (42 conversations)
│   └── grok_data-2026-01-28.zip     # Grok export (126 conversations)
│
├── research/
│   ├── entity-linking-summary.md    # TL;DR: Wikidata/DBpedia strategy
│   ├── entity-linking-quickstart.md # 3-step deployment guide
│   ├── wikidata_entity_linking_research.md
│   ├── dbpedia-entity-linking-assessment.md
│   ├── entity_linking_integration_approaches.md
│   └── entity_linking_comparison_table.md
│
├── cognee_eval/                     # Cognee framework evaluation (rejected)
│   ├── EVALUATION.md
│   ├── ingest.py
│   └── evaluate.py
│
├── output/
│   ├── claude/                      # Per-session .ttl files + wikidata_links.ttl
│   ├── batch_jobs/                  # Batch prediction manifests
│   ├── test_triples.ttl             # Sprint 2 output (2,185 triples)
│   ├── ec11ec1e.ttl                 # Sprint 1 output (research session)
│   └── ddxplus.ttl                  # Sprint 1 output (medical session)
│
└── test/
    ├── sample_entities.txt          # Entity linking test data
    ├── quick_test.txt
    ├── quick_links.ttl              # Validated Wikidata owl:sameAs output
    └── wikidata_links.ttl
```

---

## Sprint 1 — Structural Pipeline (2026-02-13)

### What Was Built

- OWL ontology composing PROV-O + SIOC + SKOS + DC + Schema.org
- rdflib pipeline: JSONL → RDF Turtle → Fuseki → SPARQL
- 3,006 triples loaded (2 sessions, 78 tool calls, 103 topics)
- Cognee framework evaluated and rejected

### Critical Failure: Flat Tags Instead of Knowledge Triples

The Ollama prompt extracted flat topic labels `["Prolog", "Symbolic AI"]` stored as independent `mentionsTopic` links. The graph could NOT answer "how does Prolog relate to symbolic reasoning?" — it was a tag cloud, not a knowledge graph.

**Root cause:** The plan specified "extract topics" when it should have specified "extract (subject, predicate, object) triples."

> **A knowledge graph without relationships is just a tag cloud.**

See [Lessons Learned](#lessons-learned) for the full post-mortem.

---

## Sprint 2 — Knowledge Triple Extraction (2026-02-14)

### What Changed

| Aspect | Sprint 1 | Sprint 2 |
|--------|----------|----------|
| LLM | Ollama llama3 (local) | Gemini 2.5 Flash (Vertex AI) |
| Extraction | Flat topic tags | (subject, predicate, object) triples |
| Predicate vocabulary | None | 24 curated OWL ObjectProperties |
| Entity model | SKOS Concepts (tags) | devkg:Entity + KnowledgeTriple (reified) |
| Graph answers | "What topics appeared?" | "How does X relate to Y?" |
| Verification | Structural queries only | Semantic relationship queries |

### Results

- **2,185 RDF triples** from one session (ec11ec1e)
- **128 knowledge triples** extracted across 18 predicates
- **120 distinct entities** with labeled relationships
- **905 structural triples** (messages, tool calls, threading)

### Predicate Distribution (Top 10)

| Predicate | Count | Example |
|-----------|-------|---------|
| `uses` | 25 | cognee → neo4j |
| `isTypeOf` | 18 | fuseki → triple store |
| `enables` | 14 | ssh tunnel → sql queries |
| `provides` | 12 | neo4j → native vector search |
| `relatedTo` | 10 | (fallback for uncategorized) |
| `alternativeTo` | 8 | myconnect → ngrok |
| `solves` | 7 | cloudflare bypass → bot detection |
| `dependsOn` | 6 | cognee → python |
| `isPartOf` | 6 | prov-o → devkg ontology |
| `builtWith` | 5 | cognee → python |

### Sample Semantic Queries That Now Work

**"What relationships exist for tunnel?"**
→ Returns: tunnel `enables` sql queries, tunnel `uses` ssh, tunnel `solves` firewall traversal — with provenance back to source messages.

**"How does myconnect relate to ngrok?"**
→ Returns: myconnect `alternativeTo` ngrok, myconnect `composesWith` ngrok — extracted from a specific conversation about tunneling alternatives.

### Known Issues

- ~5% of Gemini responses truncate mid-JSON for long messages (handled gracefully with empty return)
- `relatedTo` fallback is overused (~10% of triples) — could improve prompt specificity
- Entity deduplication needed across sessions (see [Entity Disambiguation](#entity-disambiguation-strategy))

---

## Multi-Platform Assessment

All five additional knowledge sources were scanned and assessed for DevKG integration.

### Data Inventory

| Source | Format | Sessions | Messages | Date Range | Status |
|--------|--------|----------|----------|------------|--------|
| **Claude Code** | JSONL | ongoing | ongoing | ongoing | ✅ Pipeline built |
| **DeepSeek** | JSON (zip) | 42 | 270 | Apr–Aug 2025 | ✅ Ready for parser |
| **Grok** | JSON (MongoDB) | 126 | 888 | Mar 2025–Jan 2026 | ✅ Ready for parser |
| **Warp** | SQLite (142 MB) | 217 | 11,397 | Jan 2025–Feb 2026 | ✅ Rich data |
| **Cursor** | SQLite (729 MB) | 985 | 32,355 | – | ⚠️ Complex extraction |
| **VS Code Copilot** | JSON files | 318 | varies | – Jan 2026 | ✅ Clean format |
| **ChatGPT** | JSON export | TBD | TBD | TBD | Not yet scanned |

### Platform-Specific Notes

**DeepSeek** — Tree-structured conversations with REQUEST/RESPONSE/THINK fragments. No explicit role field (inferred from fragment type). 10 of 42 conversations are dev-related. MongoDB-style timestamps need UTC normalization.

**Grok** — Clean MongoDB export with explicit `sender: "human" | "assistant"`. 6 model variants (grok-3, grok-4, etc.). No tool call details stored.

**Warp** — Richest surprise. 11,397 AI exchanges in SQLite with conversation IDs, model tracking (Claude 3.5 Sonnet), working directories (`prov:atLocation`), and 1,006 terminal commands linked to AI conversations. AI response text is implied by action selection, not stored as a separate field.

**Cursor** — Largest dataset, most complex extraction. Key-value SQLite blobs (`bubbleId:<composer>:<msg>`). No explicit user/assistant role. Workspace-to-project mapping requires joining with `workspace.json` across 179 workspaces. **Decision: Use `cursor-history` CLI tool (S2thend/cursor-history npm package)** instead of writing a custom SQLite parser.

**VS Code Insiders (Copilot)** — Cleanest format. Individual JSON files per session at `workspaceStorage/<hash>/chatSessions/`. Explicit requester/responder. Bonus: `workspace-chunks.json` has pre-computed code embeddings.

### Ontology Compatibility

The DevKG schema works for all platforms without modification. The core pattern (Session → Messages → Entities → KnowledgeTriples) is universal. Each platform needs only a parser adapter — the RDF output schema is identical.

What varies per platform:
- **Parser complexity** — from trivial (VS Code JSON) to complex (Cursor SQLite blobs)
- **Tool call detail** — Claude has full tool_use blocks; Grok has nothing; Warp has action results
- **Role identification** — explicit in Grok/VS Code, inferred in DeepSeek/Cursor

### Pipeline Architecture (Per Platform)

```
deepseek_data.zip    → pipeline/deepseek_to_rdf.py  → output/*.ttl ─┐
grok_data.zip        → pipeline/grok_to_rdf.py      → output/*.ttl  │
warp.sqlite          → pipeline/warp_to_rdf.py       → output/*.ttl  ├→ Fuseki
cursor (via CLI)     → pipeline/cursor_to_rdf.py     → output/*.ttl  │  (merged)
vscode chatSessions  → pipeline/vscode_to_rdf.py     → output/*.ttl  │
claude code JSONL    → pipeline/jsonl_to_rdf.py      → output/*.ttl ─┘
```

All Turtle files load into the same Fuseki dataset. Entities merge by label. Cross-platform queries work immediately.

---

## Entity Disambiguation Strategy

### The Problem

Same entity gets different names across platforms:
- `"VS Code"` vs `"Visual Studio Code"` vs `"vscode"` → three URIs
- `"k8s"` vs `"Kubernetes"` → two URIs
- `"Apollo"` → GraphQL client? Space program?

### Recommended Solution: Hybrid LLM + Wikidata

```
Extracted entity "vs code"
    ↓
Step 1: LLM canonicalizes → "Visual Studio Code"  (Gemini)
    ↓
Step 2: Wikidata API lookup → Q1136656             (wbsearchentities)
    ↓
Step 3: If ambiguous, LLM disambiguates with context
    ↓
Step 4: Store owl:sameAs link
```

**RDF output:**
```turtle
data:entity/visual-studio-code owl:sameAs <http://www.wikidata.org/entity/Q1136656> .
data:entity/devkg-ontology a devkg:Entity ;
    rdfs:label "devkg ontology" .  # No Wikidata match — stays local
```

### Coverage Assessment

| Entity | Wikidata | DBpedia |
|--------|----------|---------|
| Neo4j | ✅ Q1628290 | ✅ |
| Kubernetes | ✅ | ✅ |
| Visual Studio Code | ✅ Q1136656 | ✅ |
| FastAPI | ✅ | ❌ too new |
| Docker | ⚠️ wrong match | ✅ |
| Supabase | ✅ | ❌ too new |

**Wikidata coverage: ~88%** for mainstream dev tools. DBpedia lags on post-2020 tools. ~30-40% of entities will be project-specific (no external match) — these stay as local entities with no knowledge lost.

### Wikidata API Authentication

The Wikidata API **does not require an API key** for read operations. Both the Action API (`wbsearchentities`, `wbgetentities`) and the REST API are fully open for reads without authentication, registration, or OAuth.

**Requirements for read access:**
- **`User-Agent` header** — Wikimedia policy requires a descriptive header (e.g., `DevKnowledgeGraph/1.0 (your-email@example.com)`) for identification, not authentication. Requests without one may be deprioritized or blocked.
- **Rate limiting** — No hard limit on reads, but ~1 request/sec is considered polite. HTTP 429 with `Retry-After` header is returned if exceeded.

**Authentication (OAuth 2.0) is only required for write operations** (creating/editing entities), which this project does not perform.

Reference: [Wikidata:REST_API/Authentication](https://www.wikidata.org/wiki/Wikidata:REST_API/Authentication), [API:Etiquette](https://www.mediawiki.org/wiki/API:Etiquette)

### Why Not LLM-Only QIDs?

LLMs hallucinate Wikidata Q-numbers. QIDs are opaque identifiers — LLMs can't reliably generate `Q1628290` for Neo4j. The hybrid approach uses the LLM for what it's good at (canonicalization, context-aware disambiguation) and the API for what it's good at (authoritative identifiers).

### Research Documents

Full research in `research/`:
- `entity-linking-summary.md` — TL;DR
- `entity_linking_integration_approaches.md` — 4 approaches compared
- `wikidata_entity_linking_research.md` — Wikidata API details
- `dbpedia-entity-linking-assessment.md` — DBpedia Spotlight evaluation

---

## Ontology Reference

See **[DEVKG_ONTOLOGY.md](DEVKG_ONTOLOGY.md)** for the full reference including:
- 12 classes (Structural + Knowledge layers)
- 24 curated predicates with examples
- Reification pattern (dual storage)
- T-BOX Turtle examples
- SPARQL query patterns

Visual schema: **[ontology/devkg_schema.png](ontology/devkg_schema.png)**

### Quick Reference

```
                    prov:Activity
                         |
                   devkg:Session ──── sioc:Forum
                    /    |    \
                   /     |     \
        devkg:Message  ToolCall  CodeArtifact
           /    \        |
     UserMsg  AssistantMsg
                  |
              invokedTool ──> ToolCall ──hasToolResult──> ToolResult

        prov:Agent
         /      \
   Developer   AIModel

        devkg:Entity ──24 predicates──> devkg:Entity
                                            |
                                    devkg:KnowledgeTriple
                                    (reified provenance)
```

---

## Sprint 5 — SPARQL Skill + Wikidata Traversal (2026-02-15)

### Goal

Replace grep-based session search (50K-350K tokens, 5-15 tool calls) with SPARQL queries against the knowledge graph (2K tokens, 1 tool call).

### What Was Built

- **SPARQL skill** (`.claude/skills/devkg-sparql/SKILL.md`) — user-invocable skill teaching Claude Code to query Fuseki via SPARQL
- **14 local graph templates**: single-hop lookups, 2-hop neighborhood traversal, hub detection, path discovery, cross-session overlap, sibling entities, project knowledge maps — all with provenance (source file + content snippet)
- **6 Wikidata traversal templates** (W1-W6): entity properties, peer discovery, disambiguation, category hierarchy, relationship bridge, batch enrichment
- **Workflow**: Local KG → `owl:sameAs` QID → Wikidata SPARQL → discover new knowledge → return to local queries

### SPARQL vs Grep Comparison

| Metric | SPARQL | Grep |
|--------|--------|------|
| Tool calls | **1** | 5-10+ |
| Tokens | **~2K** | 50K-350K |
| Relationship queries | **Yes** | No |
| Cross-platform | **Yes** | No |
| Wikidata enrichment | **Yes** | No |

### Wikidata Enrichment Example

| Source | What we know about Nitrofurantoin |
|--------|----------------------------------|
| **Local KG** | medication, 100mg, every 12h, oral, 7 days, outpatient |
| **Wikidata** | ATC code J01XE01, subclass of nitrofuran, treats UTI, cystitis, gram-negative |

### Data Fix

Fosfomycin `owl:sameAs` corrected: Q421268 (tubocurarine — wrong!) → Q183554 (fosfomycin) via SPARQL UPDATE.

---

## Sprint 6 — Batch Pipeline + Scale Preparation (2026-02-15/16)

### Problem

The synchronous pipeline (`bulk_process.py`) makes one Gemini API call per assistant message, sequentially. For 610 sessions (~6,060 messages), this is slow and full-price. The Vertex AI Batch Prediction API offers 50% cost reduction and processes all requests in a single async job.

### What Was Built

**`pipeline/bulk_batch.py`** — a decoupled 3-step batch pipeline:

| Step | Command | What It Does |
|------|---------|--------------|
| **submit** | `bulk_batch submit` | Extracts assistant messages from JSONL → builds batch JSONL → uploads to GCS → submits Vertex AI batch job |
| **status** | `bulk_batch status --wait` | Polls job state until SUCCEEDED/FAILED |
| **collect** | `bulk_batch collect` | Downloads output shards from GCS → parses Gemini responses → injects triples into RDF graphs → writes `.ttl` files → updates watermarks |

Each run creates a manifest file in `output/batch_jobs/` tracking job state, input/output URIs, session mapping, and results.

### Architecture

```
610 sessions                    Vertex AI Batch Prediction
───────────                     ──────────────────────────
~/.claude/projects/**/*.jsonl
    │
    ▼
extract_messages_from_jsonl()   ← reads raw JSONL, extracts assistant text
    │
    ▼
build_batch_jsonl()             ← builds {request + metadata} per message
    │
    ▼
upload_to_gcs()                 ← gs://devkg-batch-predictions/devkg/input_*.jsonl
    │
    ▼
submit_batch_job()              ← Vertex AI processes all ~6K requests async
    │                              (50% cheaper than real-time)
    ▼
poll_job()                      ← PENDING → QUEUED → RUNNING → SUCCEEDED
    │
    ▼
download_and_parse_batch_output()  ← downloads output shards from GCS
    │
    ▼
build_graph(skip_extraction=True)  ← creates RDF structure (sessions, messages, tools)
    │
    ▼
add_triples_to_graph()          ← injects batch-extracted triples per message
    │
    ▼
output/claude/<session>.ttl     ← combined structure + knowledge triples
```

### E2E Test Results (1 session, 13 messages)

| Metric | Value |
|--------|-------|
| Batch job duration | ~8.5 min |
| Knowledge triples extracted | 150 |
| Entities | 131 |
| Wikidata links | 62 (47.7%) |
| Deduplicated entity pairs | 11 |
| Total RDF triples | 2,457 (structure + knowledge + Wikidata) |

### Bugs Found and Fixed

1. **Metadata serialization** — Vertex AI Batch Prediction only accepts scalar metadata types (STRING, INTEGER, etc.), not nested JSON objects. The error message: `"The column or property 'metadata' in the specified input data is of unsupported type."` Fix: serialize metadata dict to a JSON string, deserialize on collect.

2. **`poll_job` state enum mismatch** — `str(job.state)` returned the raw integer value (e.g., `"5"`) not the enum name (`"JOB_STATE_FAILED"`). The check `"SUCCEEDED" in "5"` never matched, causing infinite polling. The first job actually failed (metadata issue) but the poller ran for 30 minutes before timing out. Fix: use `job.state.value` with numeric comparison against the `JobState` enum (`4=SUCCEEDED`, `5=FAILED`).

### Scale Assessment for Full Run

| Metric | Value |
|--------|-------|
| Sessions to process | 600 (10 already watermarked) |
| Subagent files filtered | 1,022 |
| Estimated assistant messages | ~6,060 |
| Estimated batch JSONL size | ~18 MB |
| Vertex AI batch limit | 10 GB |
| Estimated cost | ~$0.60 (batch 50% discount) |
| Sessions with no assistant messages | ~14% (handled gracefully) |
| Largest session | 36 MB JSONL → only 41 assistant messages |

### Critical Analysis: Remaining Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Entity linking speed** | Medium | ~6K entities × ~5s = ~8h. Run separately with `--skip-linking`, then `link_entities.py` |
| **Collect crash mid-way** | Low | Watermarks saved per-session. Re-run `collect` resumes from where it stopped. Batch output stays in GCS. |
| **Truncated Gemini responses** | Low | `max_output_tokens=8192` + salvage logic in `_parse_triples_response()`. ~5% truncation rate expected. |
| **Batch job timeout** | Low | Default `max_wait=1800s` (30 min). For 6K requests, job may need longer. Use `--poll-interval 120` and re-run `status --wait` if timeout occurs. |
| **GCS costs** | Negligible | ~18 MB input + ~18 MB output. Well under free tier. |

---

## Parking Lot

| # | Item | Status | Description |
|---|------|--------|-------------|
| 1 | ~~`devkg:hasSourceFile`~~ | **Done (Sprint 3)** | Sessions linked to raw source file paths |
| 2 | ~~`devkg:Project`~~ | **Done (Sprint 3)** | Sessions linked to project context |
| 3 | **Cursor extraction** | Dropped (Sprint 4) | `cursor-history` CLI unmaintained, low value |
| 4 | **Post-session hook** | Skeleton only | `hooks/post_session_hook.sh` exists but untested |
| 5 | **Sync daemon** | Skeleton only | `daemon/sync_daemon.py` exists but untested |
| 6 | ~~**Wikidata linking**~~ | **Done (Sprint 3-4)** | Agentic LangGraph linker, 120 links at 33% rate |
| 7 | ~~**Per-platform parsers**~~ | **Done (Sprint 3)** | DeepSeek, Grok, Warp parsers |
| 8 | ~~**Retry logic**~~ | **Done (Sprint 3)** | MAX_RETRIES=2 in triple extraction |
| 9 | **Neo4j migration** | Out of scope | Import RDF via n10s, Cypher + vector search |
| 10 | **Vector embeddings** | Out of scope | Embeddings on `sioc:content` for hybrid retrieval |
| 11 | ~~**Subagent deduplication**~~ | **Done (Sprint 6)** | `find_sessions()` filters 1,022 subagent files |
| 12 | ~~**Batch processing**~~ | **Done (Sprint 6)** | Vertex AI Batch Prediction pipeline, tested E2E |
| 13 | **Full run (600 sessions)** | Ready | Pipeline tested, scale validated, awaiting execution |

---

## Lessons Learned

### Sprint 1 — What Went Wrong

#### 1. Flat Tags Instead of Knowledge Triples (CRITICAL)

The Ollama prompt asked "extract topic strings" and got flat labels `["Prolog", "Symbolic AI"]`. These were stored as independent `mentionsTopic` links. The graph could NOT answer relationship questions.

**What the graph stored:**
```turtle
data:msg-552  devkg:mentionsTopic  data:topic/prolog .
data:msg-552  devkg:mentionsTopic  data:topic/symbolic-ai .
```

**What it should have stored:**
```turtle
data:prolog  devkg:enables      data:symbolic-reasoning .
data:prolog  devkg:servesAs     data:knowledge-oracle .
data:llm     devkg:composesWith data:prolog .
```

**Root cause:** The plan specified "extract topics" when it should have specified "extract (subject, predicate, object) triples." This is the fundamental difference between tagging and knowledge graph construction.

**Fix:** Sprint 2 replaced flat extraction with Gemini-powered triple extraction using a curated 24-predicate vocabulary. The graph now answers "how does Prolog relate to symbolic reasoning?" → `enables`.

#### 2. Cognee Is Validation-Only, Not Schema-Guided

Cognee's custom ontology support post-hoc validates extracted entities against ontology classes — it doesn't guide extraction. Our ontology defines `devkg:Session` and `devkg:ToolCall` but Cognee's LLM extracts "person", "method", "package." The ontology is a filter, not a guide.

**Lesson:** If you need schema-guided extraction, put the schema in the LLM prompt itself (like we did in Sprint 2 with the predicate vocabulary).

#### 3. Ollama Topic Extraction Quality Is Noisy

Bad topics extracted: `"Wider canvas"`, `"Simplified bottom text"`, `"Math.log(p)"`. LLM-based extraction needs better prompting (exclude UI instructions), post-processing (normalize, deduplicate), and a controlled vocabulary.

**Fix:** Sprint 2's few-shot prompt includes an explicit example returning `[]` for formatting-only messages, dramatically reducing noise.

#### 4. Agent Delegation Without Verification Criteria

Agents produced working code that loaded into Fuseki — and success was declared without running semantic verification queries. "It loads" ≠ "it answers questions."

**Lesson:** Every task needs acceptance criteria expressed as questions the graph must answer, not just "create a script."

### Sprint 1 — What Went Right

1. **Ontology composition works** — PROV-O + SIOC + SKOS compose cleanly
2. **rdflib + Fuseki pipeline is solid** — deterministic, standard RDF, SPARQL queryable
3. **JSONL parsing is correct** — threading, tool calls, session metadata all map properly

### Sprint 2 — What Went Right

1. **Curated predicate vocabulary is the crux** — 24 OWL ObjectProperties with definitions, examples, and normalization. No existing ontology (SKOS, Schema.org, DOAP, SWO) covers developer knowledge relationships like `enables`, `configures`, `deployedOn`. The custom vocabulary was the right call.
2. **Few-shot ontologist prompt works** — Gemini 2.5 Flash produces high-quality triples with the right examples. The `[]` example for formatting messages eliminates most noise.
3. **Dual storage pattern (direct edges + reified triples)** — enables both fast traversal and provenance queries without compromise.
4. **Normalization pipeline catches LLM drift** — entity normalization (lowercase, strip, collapse spaces) and predicate normalization (camelCase conversion, case-insensitive matching, `relatedTo` fallback) handle most LLM output variation.
5. **The schema is platform-agnostic** — validated against 5 additional platforms (DeepSeek, Grok, Warp, Cursor, VS Code). The ontology works for all without modification.

### Sprint 2 — What Needs Improvement

1. **Entity deduplication** — "VS Code" and "Visual Studio Code" create separate entities. Wikidata/DBpedia linking (parking lot #6) will fix this.
2. **`relatedTo` overuse** — ~10% of triples fall back to the generic predicate. Could add more domain-specific predicates or improve prompt guidance.
3. **No project context** — sessions lack project association. Parking lot #2.
4. **Single-session tested** — only one session (ec11ec1e) has been fully extracted. Need to run on all sessions before declaring the pipeline production-ready.

### Key Principles

> **A knowledge graph without relationships is just a tag cloud.**
> The minimum viable extraction unit is `(subject, predicate, object)`, not `[topic1, topic2, topic3]`.

> **Put the schema in the prompt, not in post-processing.**
> If you want the LLM to use specific predicates, give it the vocabulary explicitly with examples. Don't hope it guesses right and filter later.

> **"It loads" ≠ "it answers questions."**
> Always verify with semantic queries (Query 6, 7, 8) — not just structural ones (Query 1-5).
