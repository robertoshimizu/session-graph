# session-graph

**Turn your scattered AI coding sessions into a queryable knowledge graph.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![RDF](https://img.shields.io/badge/data-RDF%2FTurtle-orange.svg)](https://www.w3.org/RDF/)
[![SPARQL](https://img.shields.io/badge/query-SPARQL-green.svg)](https://www.w3.org/TR/sparql11-query/)
[![Apache Jena Fuseki](https://img.shields.io/badge/triplestore-Apache%20Jena%20Fuseki-red.svg)](https://jena.apache.org/documentation/fuseki2/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

---

## The Problem

Developers use 5+ AI tools every day -- Claude Code, ChatGPT, Cursor, Copilot, Grok, DeepSeek, Warp. Each session is an isolated silo. Knowledge dies when the tab closes.

You have solved the same problem three times across different tools and cannot find any of them. You debugged a Supabase auth flow in Claude Code last Tuesday, discussed the same pattern in ChatGPT a month ago, and asked Grok about JWT refresh tokens somewhere in between. None of these tools talk to each other.

Existing solutions are single-platform and flat-file. They give you search over one tool's history, not structured relationships across all of them. A grep over session logs does not tell you that `FastAPI uses Pydantic` or that `Neo4j is a type of graph database`. It just gives you walls of text.

**session-graph** fixes this.

## The Solution

session-graph extracts structured knowledge triples -- `(subject, predicate, object)` -- from all your AI coding sessions, links entities to Wikidata for universal disambiguation, and loads everything into a SPARQL-queryable triplestore with full provenance back to the source conversation.

```
"What technologies have I used across all sessions?"  -->  SPARQL query  -->  structured answer
"How does FastAPI relate to Pydantic?"                 -->  FastAPI --uses--> Pydantic
"What sessions discussed authentication?"              -->  3 sessions across Claude Code + DeepSeek
```

The key insight: **a knowledge graph without relationships is just a tag cloud.** The minimum viable extraction unit is `(subject, predicate, object)`, not `[topic1, topic2, topic3]`.

### What makes this different

- **Multi-platform**: Ingests Claude Code, ChatGPT, DeepSeek, Grok, and Warp into a single unified graph. No other tool does this.
- **Formal ontology**: Composes 5 W3C/ISO standards (PROV-O, SIOC, SKOS, Dublin Core, Schema.org) instead of inventing a custom schema.
- **Wikidata linking**: Entities are disambiguated against 100M+ Wikidata items via `owl:sameAs`. "k8s", "kubernetes", and "K8s" all resolve to [Q22661306](https://www.wikidata.org/wiki/Q22661306).
- **Full provenance**: Every knowledge triple traces back to the exact source message, session, platform, and file path.
- **Federated queries**: SPARQL can query your local graph and Wikidata in a single query.

## Results

From real-world usage across 52 sessions:

| Metric | Value |
|--------|-------|
| Total triples in Fuseki | 1,334,432 |
| Sessions indexed | 607+ |
| Knowledge triples extracted | 47,868+ |
| Distinct entities | ~8,000+ |
| Wikidata-linked entities | 4,774 (~33%) |
| Curated predicates | 24 (with <1% `relatedTo` fallback) |
| Platforms supported | 4 (Claude Code, DeepSeek, Grok, Warp) |
| Entity linking precision | 7/7 (agentic ReAct linker) |
| Cost per 600 sessions | ~$0.60 (Vertex AI batch pricing) |

### Graph Preview

Real data from SPARQL — technologies, concepts, and session provenance linked across multiple Claude Code sessions:

![Knowledge Graph Preview](docs/graph-preview.png)

*Hub nodes (large blue) are highly connected technologies. Green nodes are concepts/outputs. Purple rectangles are session IDs with dashed provenance edges. The "W" badge indicates entities linked to Wikidata.*

## Architecture

```
Scattered Sources              Adapter Layer           Knowledge Graph
-----------------              -------------           ---------------
Claude Code (.jsonl)  --+
DeepSeek (.json zip)  --+     triple_extraction.py
Grok (.json zip)      --+--->  (LLM extracts s,p,o   ---> Apache Jena Fuseki
Warp (SQLite)         --+      from each assistant         (SPARQL endpoint)
ChatGPT (planned)     --+      message using 24                 |
Cursor (planned)      --+      curated predicates)              |
                                     |                          v
                                     v                    SPARQL Queries
                            link_entities.py           (14 local templates
                             (LangGraph ReAct           + 6 Wikidata templates)
                              agent links to                    |
                              Wikidata QIDs)                    v
                                                        Claude Code Skill
                                                     (natural language -> SPARQL)

Real-time Loop (Claude Code):
  Session pause → stop_hook.sh → RabbitMQ → pipeline-runner → Fuseki
                                              (triple cache: 0 API calls for seen messages)
```

### Pipeline in Detail

```
1. SOURCE PARSING (per platform --> RDF Turtle)
   Each parser reads a platform-specific format and produces
   PROV-O + SIOC session structure plus knowledge triples.

2. TRIPLE EXTRACTION (LLM-powered)
   Each assistant message --> LLM --> top 10 (subject, predicate, object) triples
   24 curated predicates | capped at 10 triples/message (prioritizes architecture)
   Closed-world vocabulary (deviations fuzzy-matched) | retry on JSON truncation

3. ENTITY FILTERING (two-level)
   Level 1: is_valid_entity() in triple_extraction.py -- rejects garbage at extraction
   Level 2: is_linkable_entity() in link_entities.py -- pre-filters before Wikidata
   Catches: filenames (*.py), hex colors (#8776f6), CLI flags (--force),
            ICD codes (j458), snake_case identifiers, DOM selectors, etc.
   48 whitelisted short terms bypass filters (ai, api, llm, rdf, sql, etc.)

4. ENTITY LINKING (context-aware, agentic)
   For each entity:
   +-- Normalize via entity_aliases.json (161 mappings: k8s-->kubernetes, etc.)
   +-- Frequency filter: --min-sessions 2 (default) -- only links entities
   |   appearing in 2+ sessions (~77% reduction)
   +-- Check SQLite cache
   +-- If miss --> LangGraph ReAct agent (LLM + Wikidata API tool)
   +-- Confidence threshold 0.7 --> owl:sameAs link
   +-- Entity dedup: same QID --> owl:sameAs between aliases

5. LOAD --> Apache Jena Fuseki (SPARQL endpoint)

6. QUERY --> SPARQL (via Claude Code skill or directly)
```

## Supported Platforms

| Platform | Parser | Format | Status |
|----------|--------|--------|--------|
| Claude Code | `jsonl_to_rdf.py` | JSONL | Production |
| DeepSeek | `deepseek_to_rdf.py` | JSON zip export | Production |
| Grok | `grok_to_rdf.py` | JSON (MongoDB export) | Production |
| Warp | `warp_to_rdf.py` | SQLite | Production |
| ChatGPT | -- | JSON export | Planned |
| Cursor | -- | SQLite / Markdown | Planned |
| VS Code Copilot | -- | JSON | Planned |

All parsers produce the same RDF schema. Entities merge by label across platforms.

## Quick Start

```bash
git clone https://github.com/robertoshimizu/session-graph.git
cd session-graph
./setup.sh
```

The setup script checks prerequisites, creates `.env` with your LLM provider, installs Python dependencies, starts Docker services (Fuseki + RabbitMQ), and runs a smoke test — all interactively.

After setup: **http://localhost:3030** (Fuseki SPARQL UI) and **http://localhost:15672** (RabbitMQ, devkg/devkg).

<details>
<summary>Manual setup (without setup.sh)</summary>

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your LLM provider API key (see Provider Support below)

# 2. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Create output directories
mkdir -p output/claude output/deepseek output/grok output/warp logs

# 4. Start all services (Fuseki + RabbitMQ + pipeline-runner)
docker compose up -d
# Fuseki SPARQL UI: http://localhost:3030
# RabbitMQ Management UI: http://localhost:15672 (devkg/devkg)

# 5. Process a single session (manual)
python -m pipeline.jsonl_to_rdf path/to/session.jsonl output/claude/session.ttl

# 6. Link entities to Wikidata
PYTHONUNBUFFERED=1 python -m pipeline.link_entities \
  --input output/*.ttl --output output/wikidata_links.ttl

# 7. Load into Fuseki (--auth required for Docker Fuseki)
python -m pipeline.load_fuseki output/*.ttl --auth admin:admin

# 8. Query at http://localhost:3030
```
</details>

### Automatic Processing (Recommended)

With Docker Compose running, every Claude Code session is automatically processed:

```
Claude Code session ends
  → stop_hook.sh publishes to RabbitMQ (~33ms, non-blocking)
  → pipeline-runner container picks up the job
  → Extracts triples, generates .ttl, uploads to Fuseki
  → Failed jobs go to dead-letter queue for inspection
```

Configure the hook in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [{"hooks": [{"type": "command", "command": "/path/to/hooks/stop_hook.sh", "timeout": 5}]}]
  }
}
```

### Bulk Processing (Backfill Your History)

Once automatic processing is running, it only captures **new** sessions going forward. But you likely have weeks or months of past Claude Code sessions already sitting on disk — and that's where most of the value is.

Claude Code stores every session as a `.jsonl` file under `~/.claude/projects/`. Each project directory contains one file per session. A typical developer accumulates hundreds of sessions over a few months. Bulk processing lets you backfill all of them into the knowledge graph in one shot.

**This is optional but highly recommended.** The more sessions in the graph, the richer the connections — you'll find patterns and relationships you didn't know existed across your past work.

```bash
source .venv/bin/activate

# Option A: Batch (50% cheaper, parallel via Vertex AI — requires GCP setup)
python -m pipeline.bulk_batch submit --sort newest
python -m pipeline.bulk_batch status --wait --poll-interval 60
python -m pipeline.bulk_batch collect

# Option B: Sequential (simpler, works with any provider)
python -m pipeline.bulk_process --limit 50 --sort newest --skip-linking

# Then link entities to Wikidata (both options)
PYTHONUNBUFFERED=1 python -m pipeline.link_entities \
  --input output/claude/*.ttl --output output/claude/wikidata_links.ttl --workers 8

# Load into Fuseki (--auth required for Docker Fuseki)
python -m pipeline.load_fuseki output/claude/*.ttl --auth admin:admin
```

After the backfill, automatic processing takes over — every future session is indexed as you work, with no manual steps.

### Other Platforms

```bash
python -m pipeline.deepseek_to_rdf data/deepseek_export.zip output/deepseek.ttl
python -m pipeline.grok_to_rdf data/grok_export.zip output/grok.ttl
python -m pipeline.warp_to_rdf output/warp.ttl --min-exchanges 5
```

## Why RDF/SPARQL?

Most developer tools reach for Neo4j, vector databases, or JSON files. Here is why session-graph uses RDF and SPARQL instead.

### Formal ontology composition

session-graph does not invent a custom schema. It composes 5 battle-tested W3C/ISO standards:

| Standard | Role | Maturity |
|----------|------|----------|
| **PROV-O** | Provenance: who did what, when, derived from what | W3C Recommendation |
| **SIOC** | Conversation structure: messages, threads, containers | W3C Member Submission |
| **SKOS** | Taxonomy: topics, broader/narrower hierarchies | W3C Recommendation |
| **Dublin Core** | Metadata: dates, titles, creators | ISO 15836 |
| **Schema.org** | Cherry-pick: `SoftwareSourceCode` | De facto standard |

This same composition approach was validated by IBM's [GRAPH4CODE](https://arxiv.org/abs/2002.09440) project at 2 billion triples.

### Wikidata linking

Every entity in the graph can be linked to Wikidata via `owl:sameAs`. This gives you:

- **Universal disambiguation**: "k8s", "kubernetes", and "K8s" all resolve to the same Wikidata item.
- **Cross-language dedup**: "medication" and "medicamento" both map to [Q12140](https://www.wikidata.org/wiki/Q12140).
- **External enrichment**: Query Wikidata to discover that Neo4j is written in Java, or that fosfomycin is an antibiotic -- knowledge that does not exist in your local sessions.

### Lightweight triplestore

Apache Jena Fuseki runs as a single JAR file. No JVM tuning required. It handles 138K+ triples without breaking a sweat. Compare this to Neo4j (Docker + plugins + configuration) or a hosted vector database (monthly fees).

### Federated queries

SPARQL's `SERVICE` keyword lets you query your local graph and Wikidata in a single request:

```sparql
# Find what Wikidata knows about entities in your local graph
SELECT ?localLabel ?wikidataDescription WHERE {
  ?entity a devkg:Entity ;
          rdfs:label ?localLabel ;
          owl:sameAs ?wd .
  SERVICE <https://query.wikidata.org/sparql> {
    ?wd schema:description ?wikidataDescription .
    FILTER(LANG(?wikidataDescription) = "en")
  }
}
```

No other query language can do this.

### Provenance built-in

PROV-O gives you provenance for free. Every knowledge triple links back to:
- The exact **message** it was extracted from (with full text)
- The **session** it belongs to
- The **platform** (Claude Code, DeepSeek, Grok, Warp)
- The **source file** on disk

### No vendor lock-in

RDF is an ISO standard (W3C). Your data is portable. You can move it to any triplestore (Fuseki, Blazegraph, GraphDB, Stardog, Amazon Neptune) or convert it to Neo4j via n10s. Try doing that with a proprietary vector database.

## Provider Support

session-graph supports multiple LLM providers for triple extraction and entity linking:

| Provider | Triple Extraction | Entity Linking | Batch Processing |
|----------|-------------------|----------------|------------------|
| Google Gemini (Vertex AI) | Yes | Yes | Yes (50% discount) |
| Google Gemini (AI Studio) | Yes | Yes | No |
| OpenAI | Yes | Yes | No |
| Anthropic (Claude) | Yes | Yes | No |
| Ollama (local) | Yes | Yes | No |

Configure your provider in `.env`:

```env
# Pick one:
PROVIDER=gemini-vertex    # Google Vertex AI (supports batch)
PROVIDER=gemini           # Google AI Studio
PROVIDER=openai           # OpenAI API
PROVIDER=anthropic        # Anthropic API
PROVIDER=ollama           # Local Ollama
```

## Example SPARQL Queries

### What technologies have I used across all sessions?

```sparql
PREFIX devkg: <http://devkg.local/ontology#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?label (COUNT(DISTINCT ?triple) AS ?degree) WHERE {
  { ?triple a devkg:KnowledgeTriple ; devkg:tripleSubject ?e .
    ?e rdfs:label ?label . FILTER(LANG(?label) = "") }
  UNION
  { ?triple a devkg:KnowledgeTriple ; devkg:tripleObject ?e .
    ?e rdfs:label ?label . FILTER(LANG(?label) = "") }
}
GROUP BY ?label
ORDER BY DESC(?degree)
LIMIT 20
```

This returns the most connected entities in your graph -- the core technologies and concepts across all your sessions.

### How does FastAPI relate to Pydantic?

```sparql
PREFIX devkg: <http://devkg.local/ontology#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX sioc:  <http://rdfs.org/sioc/ns#>

SELECT DISTINCT ?predicate (SUBSTR(?content, 1, 150) AS ?sourceSnippet) WHERE {
  ?triple a devkg:KnowledgeTriple ;
          devkg:tripleSubject ?s ;
          devkg:triplePredicateLabel ?predicate ;
          devkg:tripleObject ?o ;
          devkg:extractedFrom ?msg .
  ?s rdfs:label ?sLabel .
  ?o rdfs:label ?oLabel .
  OPTIONAL { ?msg sioc:content ?content }
  FILTER(
    CONTAINS(LCASE(STR(?sLabel)), "fastapi") &&
    CONTAINS(LCASE(STR(?oLabel)), "pydantic")
  )
}
```

Result: `FastAPI --uses--> Pydantic`, with a snippet from the source conversation.

### What entities appear across multiple platforms?

```sparql
PREFIX devkg: <http://devkg.local/ontology#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?label (GROUP_CONCAT(DISTINCT ?platform; separator=", ") AS ?platforms)
       (COUNT(DISTINCT ?platform) AS ?platformCount) WHERE {
  ?triple a devkg:KnowledgeTriple ;
          devkg:tripleSubject ?e ;
          devkg:extractedInSession ?session .
  ?session devkg:hasSourcePlatform ?platform .
  ?e rdfs:label ?label .
}
GROUP BY ?label
HAVING(COUNT(DISTINCT ?platform) > 1)
ORDER BY DESC(?platformCount)
```

This reveals knowledge that spans platforms -- things you discussed in both Claude Code and DeepSeek, for example.

### Federated query: What is Kubernetes according to Wikidata?

```sparql
PREFIX devkg: <http://devkg.local/ontology#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>
PREFIX wd:    <http://www.wikidata.org/entity/>

SELECT ?label ?wikidataURI WHERE {
  ?entity a devkg:Entity ;
          rdfs:label ?label ;
          owl:sameAs ?wikidataURI .
  FILTER(STRSTARTS(STR(?wikidataURI), "http://www.wikidata.org"))
  FILTER(CONTAINS(LCASE(STR(?label)), "kubernetes"))
}
```

The full SPARQL skill includes 14 local query templates and 6 Wikidata traversal templates. See [`pipeline/sample_queries.sparql`](pipeline/sample_queries.sparql) for the complete reference.

## Ontology

session-graph composes 5 W3C/ISO standards into a minimal OWL ontology with 24 curated predicates for developer knowledge:

```turtle
@prefix prov:    <http://www.w3.org/ns/prov#> .
@prefix sioc:    <http://rdfs.org/sioc/ns#> .
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix schema:  <http://schema.org/> .
@prefix devkg:   <http://devkg.local/ontology#> .

# A session is both a PROV Activity (provenance) and a SIOC Forum (conversation)
ex:session-001 a prov:Activity, sioc:Forum ;
    dcterms:created "2026-02-13T14:30:00Z"^^xsd:dateTime ;
    dcterms:title "Debugging auth flow" ;
    prov:wasAssociatedWith ex:developer, ex:agent-claude-code .

# A message in that session
ex:message-001 a sioc:Post, prov:Entity ;
    sioc:has_container ex:session-001 ;
    sioc:content "How do I handle JWT refresh?" ;
    prov:wasGeneratedBy ex:session-001 .

# An extracted knowledge triple with full provenance
ex:triple-001 a devkg:KnowledgeTriple ;
    devkg:tripleSubject ex:entity-fastapi ;
    devkg:triplePredicateLabel "uses" ;
    devkg:tripleObject ex:entity-pydantic ;
    devkg:extractedFrom ex:message-042 ;
    devkg:extractedInSession ex:session-001 .
```

### The 24 Predicates

Closed-world design: the LLM is constrained to use only these predicates. Any deviation is fuzzy-matched to the closest one (fallback: `relatedTo`, kept under 1%).

| Category | Predicates |
|----------|-----------|
| **Dependencies** | `uses`, `dependsOn`, `requires`, `builtWith` |
| **Capabilities** | `enables`, `provides`, `solves`, `produces` |
| **Structure** | `isPartOf`, `hasPart`, `extends`, `implements` |
| **Taxonomy** | `isTypeOf`, `broader`, `narrower` |
| **Infrastructure** | `deployedOn`, `storesIn`, `queriedWith`, `configures` |
| **Relationships** | `integratesWith`, `composesWith`, `alternativeTo`, `servesAs`, `relatedTo` |

Full ontology: [`ontology/devkg.ttl`](ontology/devkg.ttl)

## Project Structure

```
session-graph/
+-- ontology/devkg.ttl                    # OWL ontology (24 predicates)
+-- pipeline/
|   +-- common.py                         # Shared: namespaces, URI helpers
|   +-- llm_providers.py                   # LLM provider abstraction (Gemini, OpenAI, Anthropic, Ollama)
|   +-- triple_extraction.py              # LLM prompt, extraction, normalization
|   +-- jsonl_to_rdf.py                   # Claude Code JSONL --> RDF
|   +-- deepseek_to_rdf.py                # DeepSeek JSON --> RDF
|   +-- grok_to_rdf.py                    # Grok JSON --> RDF
|   +-- warp_to_rdf.py                    # Warp SQLite --> RDF
|   +-- link_entities.py                  # Wikidata entity linking (agentic)
|   +-- agentic_linker_langgraph.py       # LangGraph ReAct agent
|   +-- entity_aliases.json               # 161 tech synonym mappings
|   +-- bulk_process.py                   # Sequential bulk processor
|   +-- bulk_batch.py                     # Vertex AI Batch Prediction
|   +-- snapshot_links.py                 # Inspect entity linking progress
|   +-- load_fuseki.py                    # Upload .ttl to Fuseki
|   +-- sample_queries.sparql             # 14 SPARQL query templates
|   +-- .entity_cache.db                  # SQLite cache for Wikidata links (auto-created)
|   +-- .triple_cache.db                  # SQLite cache for extracted triples (auto-created)
+-- docker/
|   +-- queue_consumer.py                 # RabbitMQ consumer: dequeues jobs, runs pipeline
+-- hooks/stop_hook.sh                    # Post-session hook: publishes to RabbitMQ (~33ms)
+-- Dockerfile.pipeline                   # Python 3.12 image with pipeline deps
+-- docker-compose.yml                    # fuseki + rabbitmq + pipeline-runner
+-- .claude/skills/devkg-sparql/          # SPARQL skill for Claude Code
+-- tests/test_integration.sh             # 16-point end-to-end integration test
+-- output/                               # Generated .ttl files
+-- requirements.txt
+-- .env.example
+-- LICENSE
```

## Adding a New Parser

To add support for a new AI platform, implement a parser that reads the platform's native format and produces an `rdflib.Graph` with the same schema.

The key contract:

1. Create sessions as `devkg:Session` (subclass of `prov:Activity` + `sioc:Forum`)
2. Create messages as `devkg:UserMessage` or `devkg:AssistantMessage`
3. Call `triple_extraction.extract_triples(text)` on each assistant message
4. Use `common.py` helpers for URI generation and namespace management

See any existing parser (e.g., `pipeline/jsonl_to_rdf.py`) as a template. The shared modules handle all RDF construction, triple extraction, and entity normalization.

## Cost

| Component | Cost |
|-----------|------|
| Triple extraction (batch) | ~$0.60 / 600 sessions |
| Triple extraction (real-time) | ~$1.20 / 600 sessions |
| Entity linking | ~$0.10 / 1,000 entities |
| Apache Jena Fuseki | Free (local) |
| Wikidata API | Free (no auth required) |
| **Total for 600 sessions** | **~$0.70 - $1.30** |

The entire pipeline runs for less than $2 on a typical developer's full session history.

## Key Design Decisions

- **Assistant-only extraction**: Only assistant messages are sent to the LLM for triple extraction. User messages are short prompts with no extractable knowledge.
- **Closed-world predicates**: The LLM is constrained to 24 predicates. The prompt includes wrong/correct examples to keep `relatedTo` fallback under 1%.
- **Top-10 extraction cap**: Extracts at most 10 triples per message, prioritizing architectural decisions and technology choices over trivial details.
- **Two-level entity filtering**: `is_valid_entity()` at extraction time + `is_linkable_entity()` before Wikidata linking. Rejects ~6% garbage (filenames, hex colors, CLI flags, ICD codes, DOM selectors, version strings). 48 whitelisted short terms bypass all filters.
- **Frequency-based linking**: `--min-sessions 2` (default) only links entities appearing in 2+ sessions. ~77% of entities are single-session noise, dramatically reducing linking cost.
- **Dual storage**: Direct edges for fast graph traversal AND reified `KnowledgeTriple` nodes for provenance. Query either depending on your needs.
- **Context-aware entity linking**: Neighboring KnowledgeTriple relationships are passed as disambiguation context to the ReAct agent. "condition" resolves to disease (not programming conditional) when surrounded by medical triples.
- **Agentic linker over heuristic**: LangGraph ReAct agent (LLM + Wikidata API tool) achieves 7/7 precision vs ~50% for keyword heuristic. Resolves abbreviations like k8s, otel, tf.
- **Triple extraction cache**: SQLite cache (`.triple_cache.db`) keyed by message UUID. The stop hook fires on every Claude Code pause, causing re-processing. The cache ensures each message's LLM extraction only happens once — re-runs rebuild the RDF graph but skip API calls for cached messages.
- **Incremental real-time ingestion**: Stop hook → RabbitMQ → pipeline-runner → Fuseki. Each session pause triggers automatic extraction and loading. The triple cache makes repeated processing free.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| **Fuseki returns 401 Unauthorized** | Docker Fuseki requires auth. Use `--auth admin:admin` with `load_fuseki.py`, or pass `auth=('admin', 'admin')` to the Python functions. |
| **RabbitMQ management UI unreachable** | Wait 30s after `docker compose up`. Check with `docker compose logs rabbitmq`. Default credentials: devkg/devkg. |
| **No sessions to process** | `bulk_process.py` looks for `.jsonl` files under `~/.claude/projects/`. Run at least one Claude Code session first. |
| **`link_entities.py` output buffered** | Use `PYTHONUNBUFFERED=1` prefix: `PYTHONUNBUFFERED=1 python -m pipeline.link_entities ...` |
| **Stop hook not firing** | Verify `~/.claude/settings.json` has the hook entry. The path must be absolute. Run `./setup.sh` to install it automatically. |
| **`ModuleNotFoundError`** | Activate the virtualenv first: `source .venv/bin/activate` |

## Lessons Learned

> **A knowledge graph without relationships is just a tag cloud.**
> The minimum viable extraction unit is `(subject, predicate, object)`, not `[topic1, topic2, topic3]`.

> **Put the schema in the prompt, not in post-processing.**
> If you want the LLM to use specific predicates, give it the vocabulary explicitly with examples.

> **"It loads" does not mean "it answers questions."**
> Always verify with semantic queries, not just structural ones.

## References

- [GRAPH4CODE](https://arxiv.org/abs/2002.09440) (IBM Research) -- 2B triples, same ontology composition approach
- [PROV-O: The PROV Ontology](https://www.w3.org/TR/prov-o/) -- W3C Recommendation
- [SIOC Core Ontology](http://rdfs.org/sioc/spec/) -- Semantically-Interlinked Online Communities
- [SKOS Reference](https://www.w3.org/TR/skos-reference/) -- Simple Knowledge Organization System
- [Apache Jena Fuseki](https://jena.apache.org/documentation/fuseki2/) -- SPARQL server
- [LangGraph](https://github.com/langchain-ai/langgraph) -- Agent orchestration framework

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on adding parsers, improving extraction, and submitting pull requests.

## License

[Apache License 2.0](LICENSE)
