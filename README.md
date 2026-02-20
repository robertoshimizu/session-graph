# Dev Knowledge Graph (DevKG)

A personal knowledge graph that extracts structured `(subject, predicate, object)` triples from AI coding sessions, links entities to Wikidata, and enables relationship queries via SPARQL — with full provenance back to the source conversation.

## What You Get

From raw session files (JSONL, JSON, SQLite), the pipeline produces:

- **Knowledge triples** — `FastAPI → uses → Pydantic`, `Neo4j → isTypeOf → graph database` — extracted by Gemini 2.5 Flash
- **Wikidata links** — entities linked to Wikidata QIDs via `owl:sameAs` (agentic disambiguation with session context)
- **Full provenance** — every triple traces back to the source message, session, platform, and file path
- **SPARQL queryable** — loaded into Apache Jena Fuseki, queryable via Claude Code's `devkg-sparql` skill

### Current Scale

| Metric | Value |
|--------|-------|
| Triples in Fuseki | 138,802 |
| Claude Code sessions indexed | 52 |
| Knowledge triples | ~2,500+ |
| Distinct entities | ~4,600+ |
| Wikidata-linked entities | ~33% |
| Platforms supported | Claude Code, DeepSeek, Grok, Warp |

## Supported Platforms

| Source | Format | Parser |
|--------|--------|--------|
| **Claude Code** | JSONL (`~/.claude/projects/**/*.jsonl`) | `jsonl_to_rdf.py` |
| **DeepSeek** | JSON zip export | `deepseek_to_rdf.py` |
| **Grok** | JSON (MongoDB export) | `grok_to_rdf.py` |
| **Warp** | SQLite | `warp_to_rdf.py` |
| Cursor | SQLite | Not yet built |
| VS Code Copilot | JSON | Not yet built |
| ChatGPT | JSON export | Not yet built |

All parsers produce the same RDF schema. Entities merge by label across platforms.

## Prerequisites

- Python 3.11+ with virtualenv
- Google Cloud service account with Vertex AI access (for Gemini 2.5 Flash)
- [Apache Jena Fuseki](https://jena.apache.org/documentation/fuseki2/) (for SPARQL queries)

## Setup

```bash
cd dev-knowledge-graph
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:
```env
GOOGLE_APPLICATION_CREDENTIALS_BASE64=<base64-encoded-service-account-json>
GOOGLE_CLOUD_PROJECT=<your-project-id>
```

## Running the Pipeline

### Recommended: Batch Pipeline (fastest, cheapest)

Three decoupled steps — Vertex AI handles parallelism, 50% cost discount:

```bash
# Step 1: Submit batch job (uploads all unprocessed sessions to Vertex AI)
.venv/bin/python -m pipeline.bulk_batch submit --sort newest

# Step 2: Wait for completion (poll every 60s)
.venv/bin/python -m pipeline.bulk_batch status --wait --poll-interval 60

# Step 3: Collect results → .ttl files
.venv/bin/python -m pipeline.bulk_batch collect

# Step 4: Link entities to Wikidata (parallel, 8 workers by default)
PYTHONUNBUFFERED=1 .venv/bin/python -m pipeline.link_entities \
  --input output/claude/*.ttl --output output/claude/wikidata_links.ttl \
  --workers 8

# Step 5: Load into Fuseki
cd ~/opt/apache-jena-fuseki && ./fuseki-server &
.venv/bin/python pipeline/load_fuseki.py output/claude/*.ttl
```

Use `--limit N` on the submit step to cap the number of sessions.

### Alternative: Sequential Pipeline (simpler, full price)

Processes one session at a time with real-time Gemini calls. Useful for small runs or debugging:

```bash
# Extract triples (skip entity linking, run it separately with --workers)
.venv/bin/python -m pipeline.bulk_process --limit 50 --sort newest --skip-linking

# Then link entities in parallel
PYTHONUNBUFFERED=1 .venv/bin/python -m pipeline.link_entities \
  --input output/claude/*.ttl --output output/claude/wikidata_links.ttl \
  --workers 8

# Load into Fuseki
.venv/bin/python pipeline/load_fuseki.py output/claude/*.ttl
```

### Pipeline Comparison

| | **Batch** (`bulk_batch`) | **Sequential** (`bulk_process`) |
|---|---|---|
| Triple extraction | Vertex AI processes all sessions in parallel | One session at a time, one API call per message |
| Cost | **50% discount** (Batch Prediction API) | Full price |
| Latency | Submit + wait (minutes to hours) | Immediate, but slow overall |
| Best for | Production runs, large volumes | Debugging, small runs (< 5 sessions) |

Both pipelines use the same watermarks — already-processed sessions are skipped automatically.

### Single Session

```bash
# Full extraction
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl

# Structure only (no Gemini calls)
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/result.ttl --skip-extraction
```

### Other Platforms

```bash
.venv/bin/python -m pipeline.deepseek_to_rdf external_knowledge/deepseek_data.zip output/deepseek.ttl --conversation 0
.venv/bin/python -m pipeline.grok_to_rdf external_knowledge/grok_data.zip output/grok.ttl --conversation 0
.venv/bin/python -m pipeline.warp_to_rdf output/warp.ttl --conversation 0 --min-exchanges 5
```

### Inspect Intermediate Results

If entity linking is running (can take hours for thousands of entities), inspect progress without interrupting:

```bash
.venv/bin/python -m pipeline.snapshot_links \
  --input output/claude/*.ttl --output output/claude/wikidata_links_snapshot.ttl
```

## Querying the Knowledge Graph

### Via Claude Code (recommended)

The `devkg-sparql` skill teaches Claude Code to query Fuseki directly. Just ask natural language questions:

- "What do we know about FastAPI?"
- "What sessions discussed authentication?"
- "How does Neo4j relate to knowledge graphs?"
- "What are the most connected entities?"

### Via SPARQL directly

Query at `http://localhost:3030` (Fuseki UI) or via curl:

```bash
# Hub detection — most connected entities
curl -s -X POST 'http://localhost:3030/devkg/sparql' \
  -H 'Accept: application/sparql-results+json' \
  --data-urlencode "query=PREFIX devkg: <http://devkg.local/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?label (COUNT(DISTINCT ?triple) AS ?degree) WHERE {
  { ?triple a devkg:KnowledgeTriple ; devkg:tripleSubject ?e . ?e rdfs:label ?label . FILTER(LANG(?label) = \"\") }
  UNION
  { ?triple a devkg:KnowledgeTriple ; devkg:tripleObject ?e . ?e rdfs:label ?label . FILTER(LANG(?label) = \"\") }
} GROUP BY ?label ORDER BY DESC(?degree) LIMIT 20" \
  | jq -r '.results.bindings[] | [.label.value, .degree.value] | @tsv'
```

See `pipeline/sample_queries.sparql` for 14 query templates. See `.claude/skills/devkg-sparql/SKILL.md` for the full reference (14 local + 6 Wikidata templates).

## How It Works

```
1. SOURCE PARSING (per platform → RDF Turtle)
   Claude Code .jsonl  →  jsonl_to_rdf.py  →  .ttl
   Each assistant message → Gemini 2.5 Flash → (subject, predicate, object) triples
   24 curated predicates (uses, dependsOn, enables, implements, etc.)

2. ENTITY LINKING (context-aware, agentic)
   .ttl files → link_entities.py → wikidata_links.ttl
   For each entity:
   ├── Extract neighboring triples as disambiguation context
   ├── LangGraph ReAct agent (Gemini + Wikidata API tool)
   ├── Confidence threshold 0.7 → owl:sameAs link
   └── SQLite cache (incremental, survives restarts)

3. LOAD → Apache Jena Fuseki (SPARQL endpoint)

4. QUERY → SPARQL (via Claude Code skill or directly)
```

### Deduplication & Incremental Processing

- **Watermarks**: `bulk_process.py` tracks processed sessions by SHA256 hash in `output/watermarks.json`. Re-running skips already-processed sessions.
- **Subagent filtering**: Subagent `.jsonl` files are excluded by default to avoid 76% knowledge triple duplication.
- **Entity cache**: Wikidata lookups cached in `pipeline/.entity_cache.db` (SQLite). Only cache misses trigger the ReAct agent.
- **Entity dedup**: Entities sharing the same Wikidata QID get `owl:sameAs` to each other.

## Ontology

Five W3C/ISO standards composed, plus 24 curated DevKG predicates:

| Standard | Role |
|----------|------|
| **PROV-O** | Provenance: who did what, when, derived from what |
| **SIOC** | Conversation: messages, threads, containers |
| **SKOS** | Taxonomy: topics, broader/narrower hierarchies |
| **Dublin Core** | Metadata: dates, titles, creators |
| **Schema.org** | Cherry-pick: `SoftwareSourceCode` |

**24 predicates**: `uses`, `dependsOn`, `enables`, `isPartOf`, `hasPart`, `implements`, `extends`, `alternativeTo`, `solves`, `produces`, `configures`, `composesWith`, `provides`, `requires`, `isTypeOf`, `builtWith`, `deployedOn`, `storesIn`, `queriedWith`, `integratesWith`, `broader`, `narrower`, `relatedTo`, `servesAs`

Full ontology reference: [DEVKG_ONTOLOGY.md](DEVKG_ONTOLOGY.md) | Visual schema: [ontology/devkg_schema.png](ontology/devkg_schema.png)

## Project Structure

```
dev-knowledge-graph/
├── ontology/devkg.ttl                # OWL ontology (24 predicates)
├── pipeline/
│   ├── common.py                     # Shared RDF logic (namespaces, URI helpers)
│   ├── vertex_ai.py                  # Vertex AI auth (base64 creds → temp file)
│   ├── triple_extraction.py          # Gemini prompt + extraction + normalization
│   ├── jsonl_to_rdf.py               # Claude Code JSONL → RDF
│   ├── deepseek_to_rdf.py            # DeepSeek JSON → RDF
│   ├── grok_to_rdf.py                # Grok JSON → RDF
│   ├── warp_to_rdf.py                # Warp SQLite → RDF
│   ├── link_entities.py              # Wikidata entity linking (context-aware, agentic)
│   ├── agentic_linker_langgraph.py   # LangGraph ReAct agent for disambiguation
│   ├── entity_aliases.json           # 161 tech synonym mappings
│   ├── bulk_process.py               # Sequential bulk processor (watermarks, --sort, --limit)
│   ├── bulk_batch.py                 # Vertex AI Batch Prediction (50% cheaper)
│   ├── batch_extraction.py           # Batch job helpers
│   ├── snapshot_links.py             # Inspect intermediate entity linking (read-only)
│   ├── load_fuseki.py                # Upload .ttl to Fuseki
│   ├── sample_queries.sparql         # 14 SPARQL query templates
│   └── .entity_cache.db              # SQLite cache for Wikidata links (auto-created)
├── .claude/skills/devkg-sparql/      # SPARQL skill for Claude Code
├── output/claude/                    # Generated .ttl files per session
├── external_knowledge/               # DeepSeek/Grok exports
├── research/                         # Entity linking research docs
└── requirements.txt
```

## Cost

| Component | Cost |
|-----------|------|
| Triple extraction | ~$0.60 / 600 sessions (Vertex AI batch, 50% discount) |
| Entity linking | ~$0.10 / 1000 entities (Gemini 2.5 Flash) |
| Fuseki | Free (local) |
| Wikidata API | Free (no auth required for reads) |

## Key Design Decisions

- **Assistant-only extraction** — user messages are short prompts with no extractable knowledge
- **Closed-world predicates** — LLM constrained to 24 predicates; deviations fuzzy-matched (fallback: `relatedTo` < 1%)
- **Context-aware entity linking** — neighboring KnowledgeTriple relationships passed as disambiguation context to the ReAct agent (e.g., "condition" resolves to disease, not programming conditional)
- **Dual storage** — direct edges for fast traversal + reified KnowledgeTriple nodes for provenance
- **Agentic linker over heuristic** — LangGraph ReAct agent achieves 7/7 precision vs ~50% for keyword heuristic

## Lessons Learned

> **A knowledge graph without relationships is just a tag cloud.**
> The minimum viable extraction unit is `(subject, predicate, object)`, not `[topic1, topic2, topic3]`.

> **Put the schema in the prompt, not in post-processing.**
> If you want the LLM to use specific predicates, give it the vocabulary explicitly with examples.

> **"It loads" ≠ "it answers questions."**
> Always verify with semantic queries, not just structural ones.
