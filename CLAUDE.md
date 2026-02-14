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

| Ontology | Role | Maturity |
|---|---|---|
| **PROV-O** | Backbone: who did what, when, from where (provenance) | W3C Recommendation |
| **SIOC** | Conversation structure: messages, threads, platforms | W3C Member Submission |
| **SKOS** | Concept taxonomy: topics, skills, technologies | W3C Recommendation |
| **Dublin Core** | Universal metadata: dates, titles, creators | ISO Standard |
| **Schema.org** | Cherry-pick: `SoftwareSourceCode`, `Question`, `Answer` | De facto standard |

Validated by IBM's GRAPH4CODE project (2B triples, same composition approach).

### Graph Database: Neo4j

- Use **Neo4j Community Edition** (Docker, free) or **AuraDB Free** (cloud)
- Import ontologies via **n10s** (neosemantics) plugin
- Native vector search since v5.x enables hybrid retrieval
- Every AI framework integrates: LangChain, Cognee, Graphiti, Mem0
- LLMs generate valid Cypher reliably (unlike SPARQL)
- Add Apache Jena later only if OWL reasoning is needed

### Key Frameworks

| Framework | Purpose | Notes |
|---|---|---|
| **Cognee** (`topoteretes/cognee`) | Ingest 30+ sources, auto-generate KG, entity extraction, user-defined ontologies | 10K+ stars, supports Neo4j |
| **Graphiti** (`getzep/graphiti`) | Temporal KG from conversations, tracks when facts were true, hybrid retrieval | 3K+ stars, **has MCP server for Claude Code** |
| **LangChain + Neo4j** | `LLMGraphTransformer`, `GraphCypherQAChain`, hybrid vector+keyword+graph search | `pip install langchain-neo4j` |
| **Microsoft GraphRAG** | Community-based summarization, multi-hop reasoning | Expensive indexing (100-1000x RAG) |
| **LightRAG** | Lightweight alternative to MS GraphRAG | EMNLP 2025 |

### Conversation Parsers (Already Exist)

| Source | Parser Tool |
|---|---|
| Claude Code | `claude-code-log` (714 stars), `claude-code-transcripts` (Simon Willison) |
| ChatGPT | `chatgpt-exporter` (Tampermonkey script) |
| Cursor | `cursor-history` CLI (`@johnlindquist/cursor-history`), SpecStory |
| VS Code Copilot | Built-in: `Chat: Export Session...` (Ctrl+Shift+P) |
| Multi-IDE | WayLog VS Code extension (Cursor, Copilot, Lingma, CodeBuddy) |
| Warp / Grok / DeepSeek | No standardized tools (custom parser needed) |

### Code-to-Graph Tools

| Tool | What It Does |
|---|---|
| `CodeGraph` (`ChrisRoyse/CodeGraph`) | Parses TS/JS, Python, Java, Go, C# via tree-sitter |
| `code-graph-rag` (`vitali87/code-graph-rag`) | tree-sitter AST to Memgraph (Neo4j-compatible), NL queries |
| `tree-sitter-graph` (official) | Language-agnostic AST to arbitrary graph |

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

| Component | Tool | Cost |
|---|---|---|
| Graph DB | Neo4j Community (Docker) or AuraDB Free | $0 |
| KG framework | Cognee or Graphiti (open source) | $0 |
| Code parsing | tree-sitter + CodeGraph | $0 |
| Conversation parsing | claude-code-log, chatgpt-exporter, cursor-history | $0 |
| Orchestration | LangChain + LangGraph | $0 |
| Embeddings | Ollama (nomic-embed-text, local) | $0 |
| LLM extraction | Ollama (llama3/deepseek, local) or Claude via Vertex | $0 or API cost |

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

| Metric | Sprint 1 (flat tags) | Sprint 2 (knowledge triples) |
|--------|---------------------|------------------------------|
| Total RDF triples | 3,006 (2 sessions) | 2,185 (1 session) |
| Knowledge relationships | **0** | **128** |
| Distinct entities | N/A (flat tags) | **120** |
| Predicates used | 0 | **18 of 24** |
| "How does X relate to Y?" | **Cannot answer** | **Works with provenance** |
| LLM backend | Ollama llama3 (local) | Gemini 2.5 Flash (Vertex AI) |

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

| Entity | QID | Status | Description |
|--------|-----|--------|-------------|
| **Neo4j** | Q1628290 | ✅ | graph database management system implemented in Java |
| **Kubernetes** | Q22661306 | ✅ | software to manage containers on a server-cluster |
| **Visual Studio Code** | Q19841877 | ✅ | source code editor developed by Microsoft |
| **FastAPI** | Q101119404 | ✅ | software framework for developing web applications in Python |
| **Pydantic** | Q107381687 | ✅ | Python library for data parsing and validation using Python type hints |
| **Apache Jena** | Q1686799 | ✅ | open source semantic web framework for Java |
| **SPARQL** | Q54871 | ✅ | RDF query language |
| **Supabase** | Q136776342 | ✅ | open source backend platform for app development |
| **Docker** | ❌ | Missing | (returns "stevedore" occupation instead) |

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

## Next Steps (Sprint 3)

1. **P0**: Wikidata entity linking integration
   - Extract unique entities from existing RDF triples
   - Run batch Wikidata linking on all sessions
   - Update SPARQL queries to leverage owl:sameAs + Wikidata properties
   - Entity normalization via Wikidata canonical labels

2. **P0**: Process ALL Claude Code sessions (not just 1) — bulk run across `~/.claude/projects/**/*.jsonl`

3. **P1**: Add retry logic for truncated Gemini responses (currently ~5% loss)

4. **P1**: Entity deduplication — merge `oracle` and `oracle database`, `websocket` and `websocket server`

5. **P1**: Stopword filter for non-technical entities (`/exit`, `command name`)

6. **P2**: Evaluate LangChain `LLMGraphTransformer` for comparison

7. **P2**: Evaluate Graphiti for temporal relationship tracking

8. **P2**: Set up Neo4j locally as alternative/complement to Fuseki

9. **P3**: Add vector embeddings on `sioc:content` for hybrid retrieval

10. **P3**: Expand to other data sources (ChatGPT, Cursor, VS Code Copilot)
