# Dev Knowledge Graph — Implementation Summary

**Last Updated:** 2026-02-14
**Status:** Sprint 3 Complete, Sprint 3.5 (Agentic Linking) Complete

---

## Sprint 2.5: Wikidata Entity Linking (Heuristic)

**Status:** ✅ Proof of Concept Complete

### What Was Built

1. **Research document** (`wikidata_entity_linking_research.md`)
   - Wikidata API docs, coverage analysis (88%), Python library comparison

2. **Heuristic entity linker** (`pipeline/link_entities.py`)
   - Uses qwikidata + direct API (wbsearchentities)
   - Tech keyword disambiguation (prioritizes "software", "framework", "database" in descriptions)
   - Rate limiting (1 req/sec), RDF output with `owl:sameAs`

3. **Validation** (3/3 linked): Neo4j→Q1628290, Python→Q28865, React→Q19399674

### Limitation Discovered

Heuristic disambiguation fails on ambiguous terms:
- "backend" → DaBaby track (music)
- "accuracy" → The Cure track (music)
- "apis" → genus of insects

**Conclusion:** Disambiguation requires LLM + tool (agentic approach), not keyword matching.

---

## Sprint 3: Multi-Platform Pipeline (Complete)

**Status:** ✅ All 13 steps complete

### What Was Built

| Component | File | Description |
|-----------|------|-------------|
| Ontology extensions | `ontology/devkg.ttl` | +Project class, +hasSourceFile, +belongsToProject |
| Shared module | `pipeline/common.py` | Namespaces, slug(), entity_uri(), add_triples_to_graph() |
| DeepSeek parser | `pipeline/deepseek_to_rdf.py` | ZIP→JSON, tree-structured fragments, UTC normalization |
| Grok parser | `pipeline/grok_to_rdf.py` | ZIP→JSON, MongoDB timestamps, explicit sender roles |
| Warp parser | `pipeline/warp_to_rdf.py` | SQLite (142MB), agent_conversations + ai_queries tables |
| Claude Code parser | `pipeline/jsonl_to_rdf.py` | Refactored to use common.py, +hasSourceFile, +Project |
| Triple extraction | `pipeline/triple_extraction.py` | +retry logic for Gemini truncation (2 retries, truncate on retry) |
| Entity linking | `pipeline/link_entities.py` | +SQLite cache, +batch mode, +alias table |
| Alias table | `pipeline/entity_aliases.json` | Known synonyms (vscode→visual studio code, k8s→kubernetes) |
| Batch extraction | `pipeline/batch_extraction.py` | Gemini Batch Prediction via GCS |
| Hook skeleton | `hooks/post_session_hook.sh` | Claude Code post-session automation |
| Sync daemon | `daemon/sync_daemon.py` | Watchdog file watcher with watermarks |
| SPARQL queries | `pipeline/sample_queries.sparql` | +Queries 9-14 (cross-platform, Wikidata, projects) |

### Integration Results

```
5 platforms parsed → 7,462 RDF triples loaded into Fuseki
├── Claude Code:  2,185 triples (128 knowledge triples, 18/24 predicates)
├── DeepSeek:     ~1,200 triples
├── Grok:         ~1,100 triples
├── Warp:         ~900 triples (conditional — only sessions with substance)
└── Wikidata:     owl:sameAs links for ~60% of technical entities
```

### Cross-Platform Verification

14 SPARQL queries validated:
- Q9: Sessions by platform (5 platforms)
- Q10: Shared entities across platforms (entities in 2+ platforms)
- Q11: Knowledge triples by platform
- Q12: Entities with Wikidata links
- Q13: Source file traceability
- Q14: Sessions by project

### Federated SPARQL (Wikidata)

Demonstrated federated queries using `SERVICE <https://query.wikidata.org/sparql>`:
- Local entity → `owl:sameAs` → Wikidata QID → Wikidata properties
- Example: Python → Q28865 → description "general-purpose programming language", inception "1991-02-20"
- Multi-hop: enrich all linked entities with Wikidata descriptions in a single query

---

## Sprint 3.5: Agentic Entity Linking (Complete)

**Status:** ✅ Framework comparison complete, LangGraph selected

### Problem

Heuristic disambiguation (keyword matching) achieves ~50% precision on ambiguous entities. Entity linking requires an LLM that can:
1. Search Wikidata with the entity name
2. Evaluate candidates in context (is "python" a snake or a language?)
3. Try alternative terms if no match ("apis" → "application programming interface")
4. Return structured output (QID, confidence, reasoning)

### Evolution

| Approach | Script | Precision | Notes |
|----------|--------|-----------|-------|
| Heuristic | `link_entities.py` | ~50% | Keyword matching, no LLM |
| Single-shot LLM | `agentic_linker.py` | 5/7 (71%) | Gemini structured output, no tool loop |
| ReAct Agent (ADK) | `agentic_linker_adk.py` | 4/7 (57%)* | Regex parsing failures |
| **ReAct Agent (LangGraph)** | `agentic_linker_langgraph.py` | **7/7 (100%)** | Native structured output + tools |

*ADK found correct QIDs but regex parsing of free-text output failed 3/7 times.

### Framework Comparison (Ceteris Paribus)

Both implementations use identical:
- LLM: Gemini 2.5 Flash Lite (via Vertex AI)
- Tool: `search_wikidata` (same function, same return format)
- Prompt: Same system prompt with same instructions
- State: Fresh agent per entity (no state leakage)
- Test cases: Same 7 entities with same context strings

| Metric | Google ADK | LangGraph |
|--------|-----------|-----------|
| Framework | `google-adk` v1.25.0 | `langgraph` + `langchain-google-genai` |
| Structured output | Text parsing (regex) | Native Pydantic (`response_format=WikidataMatch`) |
| Tools + structured output | Mutually exclusive (`output_schema` disables tools) | Coexist natively |
| Linked successfully | 4/7 | **7/7** |
| Total time | 33.2s | **16.8s** |
| Avg per entity | 4.7s | **2.4s** |

**Verdict:** LangGraph wins. Native structured output + tool coexistence is the deciding factor.

### Key Design: ReAct Agent

```python
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

class WikidataMatch(BaseModel):
    qid: str = Field(description='Wikidata QID or "none"')
    confidence: float = Field(description="0.0 to 1.0")
    label: str
    description: str
    reasoning: str

agent = create_react_agent(
    model=ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite"),
    tools=[search_wikidata],
    response_format=WikidataMatch,
    prompt=SYSTEM_PROMPT,
)

result = agent.invoke({"messages": [("user", f"Entity: {entity}\nContext: {context}")]})
match = result["structured_response"]  # WikidataMatch instance
```

### Test Results (LangGraph)

```
Entity       QID            Conf   Label                          Time
python       Q28865          0.95  Python                          2.1s
backend      Q3532096        0.70  back end                        2.8s
agent        Q2916665        0.70  software agent                  3.1s
apis         Q165194         0.85  application programming int..   2.0s
neo4j        Q1628290        0.95  Neo4j                           1.9s
k8s          Q22661306       0.95  Kubernetes                      2.5s
js           Q2005          0.95  JavaScript                      2.4s
─────────────────────────────────────────────────────────────────────────
Linked: 7/7 | Total time: 16.8s | Avg: 2.4s per entity
```

### Files

```
pipeline/agentic_linker.py              # v1: single-shot (superseded)
pipeline/agentic_linker_adk.py          # v2: ADK ReAct (comparison only)
pipeline/agentic_linker_langgraph.py    # v3: LangGraph ReAct (WINNER)
```

---

## Pipeline Architecture

```
Data Sources          Parsers              Extraction         RDF Output
────────────          ───────              ──────────         ──────────
Claude Code (.jsonl) → jsonl_to_rdf.py ──┐
DeepSeek (.json zip) → deepseek_to_rdf.py┤                  .ttl files
Grok (.json zip)     → grok_to_rdf.py ───┼→ Gemini 2.5 Flash ──→ (per platform)
Warp (SQLite)*       → warp_to_rdf.py ───┤  triple_extraction.py      │
                                          │                            │
                     common.py ───────────┘                            │
                     (shared RDF logic)                                │
                                                                       │
              Entity Linking                    Triplestore            │
              ──────────────                    ───────────            │
              ReAct Agent ←──── .ttl files ────────────────→ Apache Jena
              (LangGraph +          │                         Fuseki
               Gemini)              │                           │
                  │                 │                           │
              Wikidata API          │                     SPARQL Queries
              wbsearchentities      │                           │
                  │                 │                     Wikidata SPARQL
              owl:sameAs ───────────┘                     (federated via
              links (.ttl)                                 SERVICE)

devkg.ttl (Ontology: PROV-O + SIOC + SKOS + Dublin Core + Schema.org)
```

*Warp: included only for sessions with substantive developer content.

Diagram also available as Excalidraw PNG/SVG at `~/Downloads/Excalidraw/dev-knowledge-graph-pipeline.png`.

---

## Sprint 4: Roadmap

### P0 — Core Pipeline

1. **Integrate agentic linker into main pipeline** — Replace heuristic `link_entities.py` with LangGraph ReAct agent (`agentic_linker_langgraph.py`) for production entity linking
2. **Process ALL Claude Code sessions** — Bulk run across `~/.claude/projects/**/*.jsonl` (1,494 sessions)
3. **Entity deduplication** — Merge variants ("oracle" / "oracle database", "websocket" / "websocket server") using Wikidata canonical labels
4. **Stopword filter** — Remove non-technical entities (`/exit`, `command name`, single characters)

### P1 — Quality

5. **Confidence threshold** — Only emit `owl:sameAs` for confidence ≥ 0.7; log low-confidence for review
6. **Predicate coverage** — Analyze which of 24 predicates are underused; tune prompt to increase coverage
7. **Warp quality filter** — Only include Warp sessions with substantive developer content (not casual terminal commands)

### P2 — Infrastructure

8. **Neo4j migration** — Import RDF into Neo4j via n10s (neosemantics); enable Cypher queries + native vector search
9. **Vector embeddings** — Add embeddings on `sioc:content` for hybrid retrieval (KG + vector)
10. **Graphiti evaluation** — Test temporal KG for tracking when facts were true (e.g., "used FastAPI" vs "migrated to Django")

### Dropped

- **Cursor parser** — `cursor-history` CLI is unmaintained; SQLite schema undocumented. Not worth the effort.

---

## Wikidata API Reference

### wbsearchentities (Search)
```bash
curl 'https://www.wikidata.org/w/api.php?action=wbsearchentities&search=Neo4j&language=en&format=json&limit=5'
```

### wbgetentities (Details)
```bash
curl 'https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q1628290&format=json&languages=en'
```

### SPARQL Endpoint
```sparql
SELECT ?item ?itemLabel WHERE {
  VALUES ?item { wd:Q1628290 wd:Q22661306 }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
```

### Rate Limits
- Unauthenticated: ~200 req/min (soft limit)
- SPARQL: 60s timeout per query
- User-Agent header required

---

## Files Index

```
# Ontology
ontology/devkg.ttl                          # OWL ontology (PROV-O + SIOC + SKOS + DC + Schema.org)

# Pipeline
pipeline/common.py                          # Shared RDF construction logic
pipeline/jsonl_to_rdf.py                    # Claude Code parser
pipeline/deepseek_to_rdf.py                 # DeepSeek parser
pipeline/grok_to_rdf.py                     # Grok parser
pipeline/warp_to_rdf.py                     # Warp parser
pipeline/triple_extraction.py               # Gemini triple extraction + retry
pipeline/link_entities.py                   # Heuristic entity linker (Sprint 2.5)
pipeline/agentic_linker.py                  # Single-shot Gemini linker (Sprint 3.5 v1)
pipeline/agentic_linker_adk.py              # ADK ReAct agent (comparison)
pipeline/agentic_linker_langgraph.py        # LangGraph ReAct agent (PRODUCTION)
pipeline/entity_aliases.json                # Known synonyms
pipeline/batch_extraction.py                # Gemini Batch Prediction
pipeline/load_fuseki.py                     # Upload Turtle to Fuseki
pipeline/sample_queries.sparql              # 14 SPARQL queries

# Automation
hooks/post_session_hook.sh                  # Claude Code hook skeleton
daemon/sync_daemon.py                       # File watcher skeleton
daemon/watermarks.json                      # Tracking state

# Research
research/wikidata_entity_linking_research.md # Full Wikidata research
research/IMPLEMENTATION_SUMMARY.md          # This file

# Output
output/claude_sample.ttl                    # Claude Code RDF
output/deepseek_sample.ttl                  # DeepSeek RDF
output/grok_sample.ttl                      # Grok RDF
output/warp_sample.ttl                      # Warp RDF
output/wikidata_links.ttl                   # owl:sameAs links
```

---

## How to Run

```bash
# Start Fuseki
cd ~/opt/apache-jena-fuseki && ./fuseki-server &

# Run parsers (1 conversation each)
.venv/bin/python -m pipeline.jsonl_to_rdf <session.jsonl> output/claude_sample.ttl
.venv/bin/python -m pipeline.deepseek_to_rdf external_knowledge/deepseek_data-2026-01-28.zip output/deepseek_sample.ttl --conversation 0
.venv/bin/python -m pipeline.grok_to_rdf external_knowledge/grok_data-2026-01-28.zip output/grok_sample.ttl --conversation 0
.venv/bin/python -m pipeline.warp_to_rdf output/warp_sample.ttl --conversation 0

# Entity linking (agentic — LangGraph ReAct)
.venv/bin/python -m pipeline.agentic_linker_langgraph

# Load into Fuseki
.venv/bin/python pipeline/load_fuseki.py output/*_sample.ttl output/wikidata_links.ttl

# Query at http://localhost:3030
```
