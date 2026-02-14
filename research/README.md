# DevKG Research Documents

This directory contains research findings for the Developer Knowledge Graph project.

---

## Entity Linking Research (2026-02-14)

**Question:** How to use DBpedia/Wikidata for entity disambiguation and linking?

**Answer:** Use DBpedia Spotlight (local Docker) as primary, Wikidata as fallback.

### Documents

| File | Purpose | Read First? |
|------|---------|-------------|
| **entity-linking-summary.md** | TL;DR - key findings, decision, next steps | ⭐ START HERE |
| **entity-linking-quickstart.md** | 3-step guide to deploy and use entity linking | ⭐ IMPLEMENTATION |
| **dbpedia-entity-linking-assessment.md** | Full research report (18 KB) - API docs, coverage tests, comparisons | 📚 REFERENCE |
| **entity_linking_integration_approaches.md** | Alternative approaches evaluated | 📚 BACKGROUND |
| **entity_linking_comparison_table.md** | Framework comparison matrix | 📚 BACKGROUND |

---

## Quick Links

### Start Implementation

1. **Read:** `entity-linking-quickstart.md` (5 min)
2. **Deploy:** DBpedia Spotlight Docker
3. **Test:** `devkg_entity_linker.py` script
4. **Integrate:** Add to `jsonl_to_rdf.py` pipeline

### Deep Dive

- **Full assessment:** `dbpedia-entity-linking-assessment.md`
- **Live API tests:** Section 1.2 (coverage analysis)
- **Python code examples:** Section 6.2
- **RDF integration:** Section 6.3

---

## Key Findings

✅ **DBpedia Spotlight works well** for established tech (Neo4j, Kubernetes, Docker)
✅ **Local Docker deployment** = no rate limits, $0 cost, private
✅ **Wikidata better for new tools** (FastAPI, Supabase, post-2020 startups)
❌ **Both fail on abbreviations** (k8s, i18n) — need custom dictionary
✅ **owl:sameAs links** enable cross-KB queries

---

## Decision

**Proceed with hybrid approach:**

```
DBpedia Spotlight (primary)
    ↓
Filter: confidence >= 0.7
    ↓
Fallback: Wikidata (for not found)
    ↓
Store owl:sameAs in DevKG RDF
```

**Cost:** $0 (only compute for local Docker)

---

## Next Steps

- [ ] Deploy DBpedia Spotlight Docker
- [ ] Install `pyspotlight` + `SPARQLWrapper`
- [ ] Build abbreviation dictionary from session logs
- [ ] Integrate into `jsonl_to_rdf.py`
- [ ] Test on existing sessions (ec11ec1e, ddxplus)
- [ ] Add deduplication SPARQL query

---

## Related Documents

- **Project overview:** `/dev-knowledge-graph/CLAUDE.md`
- **Sprint 1 lessons:** `/dev-knowledge-graph/LESSONS_LEARNED.md`
- **Ontology:** `/dev-knowledge-graph/ontology/devkg.ttl`
- **Pipeline:** `/dev-knowledge-graph/pipeline/jsonl_to_rdf.py`

---

## Session Provenance

- **Research session:** `/sessions/entity-linking-research-2026-02-14/`
- **Researcher:** Claude Code Sonnet 4.5 (Vertex AI)
- **User:** Roberto Shimizu
- **Date:** 2026-02-14
