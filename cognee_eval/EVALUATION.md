# Cognee Framework Evaluation

## Summary

Cognee v0.5.2 was evaluated as an alternative knowledge graph framework for ingesting Claude Code session logs. While it successfully installs and runs, it has significant limitations for our use case.

## Setup

- **Version**: Cognee 0.5.2
- **LLM**: Ollama llama3 (8B, local)
- **Embeddings**: Ollama nomic-embed-text (local)
- **Graph backend**: Kuzu (default, file-based)
- **Custom ontology**: `ontology/devkg.ttl` (PROV-O + SIOC + SKOS + DC + Schema.org)

## Test Execution

### Installation
- `pip install cognee` installs cleanly in Python 3.12.9
- Many optional dependencies not included (protego, playwright, PyTorch)
- Tokenizer setup triggers HuggingFace download (`nomic-ai/nomic-embed-text-v1.5`)

### Configuration
- Ollama integration works via environment variables:
  - `LLM_PROVIDER=ollama`, `LLM_MODEL=llama3:latest`, `LLM_ENDPOINT=http://localhost:11434/v1`
  - `EMBEDDING_PROVIDER=ollama`, `EMBEDDING_MODEL=nomic-embed-text:latest`
- Custom ontology file path via `ONTOLOGY_FILE_PATH` environment variable

### Ingestion Results
- Data was split into 2 session documents (one per JSONL file)
- Pipeline stages executed: `classify_documents` → `extract_chunks_from_documents` → `extract_graph_from_data`
- **Processing speed**: Very slow with local llama3 (~30s+ per chunk for entity extraction). Timed out after 5 minutes without completing full ingestion.

### Ontology Validation Issues
Cognee's ontology adapter failed to match most extracted entities to our custom ontology:
```
No close match found for 'person' in category 'classes'
No close match found for 'john' in category 'individuals'
No close match found for 'method' in category 'classes'
No close match found for 'package' in category 'classes'
No close match found for 'naive bayes on knowledge base' in category 'individuals'
No close match found for 'collection of scripts' in category 'classes'
```

**Root cause**: Cognee's LLM extracts generic entities (people, methods, packages) while our ontology defines developer session concepts (Session, Message, ToolCall, Topic). The ontology validation is a **post-extraction filter**, not a schema-guided extraction. It can't guide the LLM to extract domain-specific entities matching our ontology.

### Kuzu Database Lock Issues
- Kuzu uses file-level locking — only one process can access the database at a time
- Running ingestion while the database is locked (e.g., from a previous crashed run) causes `IO exception: Could not set lock on file`
- Requires manual cleanup: delete the `.cognee_system/databases/cognee_graph_kuzu/` directory

## Comparison: Cognee vs. rdflib Pipeline

| Aspect | Cognee | rdflib Pipeline |
|--------|--------|-----------------|
| **Schema control** | LLM-driven, generic entity extraction | Deterministic, ontology-driven mapping |
| **Ontology alignment** | Post-hoc validation only; can't guide extraction | Direct mapping to PROV-O/SIOC/SKOS classes |
| **Processing speed** | Very slow with local LLM (30s+/chunk) | Fast parsing + moderate LLM cost (topic extraction only) |
| **Output format** | Kuzu graph (proprietary format) | Standard RDF Turtle (W3C compliant) |
| **SPARQL support** | No (Cypher-like queries via Kuzu) | Yes, via Fuseki |
| **Reproducibility** | Non-deterministic (LLM-dependent) | Deterministic structure + controlled LLM for topics |
| **Interoperability** | Locked to Cognee ecosystem | Standard RDF, importable anywhere |
| **RDF export** | Not supported natively | Native output format |
| **Entity quality** | Generic (people, methods, packages) | Domain-specific (sessions, messages, tool calls) |
| **Relationship quality** | Generic (has, uses, contains) | Ontology-defined (usedInSession, hasParentMessage, invokedTool) |

## Key Findings

### Cognee Strengths
1. **Easy setup** — `pip install cognee` + env vars for LLM config
2. **Automatic chunking** — handles document splitting automatically
3. **Entity extraction** — extracts entities without manual mapping code
4. **Vector search** — built-in embedding + similarity search via LanceDB

### Cognee Weaknesses for Our Use Case
1. **No RDF output** — cannot produce Turtle, N-Triples, or any W3C standard format
2. **Ontology mismatch** — custom ontology is used for validation only, not for guiding extraction. The LLM extracts whatever entities it finds, then checks if they match ontology classes.
3. **Slow with local LLMs** — each chunk requires a full LLM call for entity extraction. With llama3 on CPU, this is impractically slow for even medium datasets.
4. **No SPARQL** — queries use Cognee's custom API or Kuzu's Cypher-like syntax
5. **Non-deterministic** — entity extraction varies between runs
6. **Opaque pipeline** — hard to debug or customize the extraction logic
7. **Kuzu limitations** — file locking, no concurrent access, proprietary format

### Can Cognee Output Be Converted to RDF?
**Theoretically yes, practically difficult.** You would need to:
1. Query all entities and relationships from Kuzu
2. Map Cognee's generic entity types to your ontology classes
3. Serialize to Turtle

But since Cognee's extracted entities don't align with our ontology, this mapping would be lossy and require significant manual effort.

## Recommendation

**Use the rdflib pipeline (Track A) as the primary approach.**

Reasons:
- Full control over ontology mapping
- Standard RDF output (Turtle) loadable into any triplestore
- SPARQL queryable via Fuseki
- Deterministic structure with controlled LLM usage (only for topic extraction)
- Faster processing

**Cognee could be useful later** for:
- Augmenting the KG with fuzzy entity extraction (as a second pass)
- Vector search on message content (Cognee's LanceDB embeddings)
- Quick prototyping when RDF compliance isn't needed

## Files

- `ingest.py` — Cognee ingestion script (functional but slow)
- `evaluate.py` — Graph inspection script (for querying Kuzu after ingestion)
