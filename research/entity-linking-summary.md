# Entity Linking Research Summary

**Date:** 2026-02-14
**Question:** How to use DBpedia/Wikidata for entity disambiguation in DevKG?
**Answer:** Use DBpedia Spotlight (local Docker) as primary, Wikidata as fallback.

---

## TL;DR

✅ **DBpedia Spotlight works well for developer entities**
✅ **Deploy locally via Docker (no rate limits, private)**
✅ **Wikidata better for new tools (post-2020)**
❌ **Both fail on abbreviations (k8s, i18n) — need custom dictionary**
✅ **Use `owl:sameAs` to link DevKG entities to canonical URIs**

---

## API Comparison

| Aspect | DBpedia Spotlight | Wikidata |
|--------|-------------------|----------|
| **Entity Linking** | ✅ One REST call | ❌ Requires NER + SPARQL |
| **Confidence Scoring** | ✅ 0.0-1.0 automatic | ❌ Manual heuristics |
| **Local Deployment** | ✅ Docker (50K+ pulls) | ❌ No official service |
| **Coverage (Established Tech)** | ⭐⭐⭐⭐⭐ Neo4j, K8s, Docker | ⭐⭐⭐⭐⭐ Same + granular |
| **Coverage (New Tech)** | ⭐⭐⭐ Post-2020 tools lag | ⭐⭐⭐⭐⭐ Real-time updates |
| **Abbreviations** | ❌ k8s not linked | ❌ k8s not linked |

---

## Live Test Results

**Input:** "I use Neo4j for graph databases, Kubernetes for container orchestration, FastAPI for web APIs, and Visual Studio Code as my IDE"

### DBpedia Spotlight Response

```json
{
  "Resources": [
    {"@URI": "http://dbpedia.org/resource/Neo4j", "@surfaceForm": "Neo4j", "@similarityScore": "1.0"},
    {"@URI": "http://dbpedia.org/resource/Kubernetes", "@surfaceForm": "Kubernetes", "@similarityScore": "1.0"},
    {"@URI": "http://dbpedia.org/resource/Visual_Studio_Code", "@surfaceForm": "Visual Studio Code", "@similarityScore": "1.0"},
    {"@URI": "http://dbpedia.org/resource/Graph_database", "@surfaceForm": "graph databases", "@similarityScore": "1.0"}
  ]
}
```

**Coverage:**
- ✅ Neo4j: `dbr:Neo4j` (confidence 1.0)
- ✅ Kubernetes: `dbr:Kubernetes` (confidence 1.0)
- ❌ FastAPI: Not found (too new, not in Wikipedia)
- ✅ VS Code: `dbr:Visual_Studio_Code` (confidence 1.0)

### Wikidata Search

**Query:** "FastAPI"

**Result:**
```
Q99182995: FastAPI - modern Python web framework
```

✅ Wikidata has FastAPI (added 2021), DBpedia does not.

---

## Key Findings

### 1. DBpedia Spotlight Accuracy

| Confidence Score | Accuracy | Use Case |
|------------------|----------|----------|
| **1.0** | Exact match | Neo4j, Kubernetes, SPARQL |
| **0.9-0.99** | Very high confidence | IDE, orchestration |
| **0.7-0.89** | Good match | Most technical terms |
| **<0.7** | Ambiguous | "Docker" → Australian football team |

**Recommendation:** Extract at `confidence=0.3`, store only `>=0.7`.

### 2. Entity Coverage Gaps

**DBpedia Missing:**
- New startups (Supabase, founded 2020)
- Python libraries (Pydantic, LangChain)
- JavaScript frameworks (Astro, SolidJS)
- Abbreviations (k8s, i18n, a11y)

**Wikidata Has:**
- FastAPI (Q99182995)
- Supabase (Q98974336)
- Separate entities for `Neo4j` (software) vs `neo4j` (Python library)

### 3. Abbreviation Handling

**Test:** "We use k8s for orchestration"

**DBpedia Result:**
```json
{
  "Resources": [
    {"@URI": "http://dbpedia.org/resource/Orchestration", "@surfaceForm": "orchestration"}
  ]
}
```

❌ "k8s" not recognized.

**Solution:** Pre-processing dictionary

```python
TECH_ABBREVIATIONS = {
    'k8s': 'Kubernetes',
    'GH': 'GitHub',
    'VS Code': 'Visual Studio Code',
}

def normalize_text(text):
    for abbr, full in TECH_ABBREVIATIONS.items():
        text = text.replace(abbr, full)
    return text

# Before: "We use k8s for orchestration"
# After:  "We use Kubernetes for orchestration"
```

---

## Recommended Pipeline

```
Session JSONL
    ↓
Extract entity mentions (Ollama LLM)
    ↓
Normalize abbreviations (dictionary)
    ↓
DBpedia Spotlight (local Docker)
    ↓
Filter: confidence >= 0.7
    ↓
Fallback: Wikidata Entity Search (for not found)
    ↓
Store owl:sameAs in DevKG RDF
```

---

## RDF Integration Example

```turtle
@prefix ex: <http://devkg.local/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix prov: <http://www.w3.org/ns/prov#> .

# Entity from DBpedia Spotlight
ex:entity-neo4j a skos:Concept ;
    skos:prefLabel "Neo4j"@en ;
    skos:altLabel "neo4j"@en, "Neo4J"@en ;  # Surface form variations
    owl:sameAs <http://dbpedia.org/resource/Neo4j> ;
    owl:sameAs <http://www.wikidata.org/entity/Q1628290> ;
    prov:wasGeneratedBy ex:session-2025-02-13 ;
    ex:linkingConfidence 1.0 ;
    ex:linkingSource "dbpedia-spotlight" .

# Entity from Wikidata fallback
ex:entity-fastapi a skos:Concept ;
    skos:prefLabel "FastAPI"@en ;
    owl:sameAs <http://www.wikidata.org/entity/Q99182995> ;
    prov:wasGeneratedBy ex:session-2025-02-13 ;
    ex:linkingSource "wikidata-search" .

# Message mentions entity
ex:message-001 a sioc:Post ;
    sioc:content "I use Neo4j and FastAPI for my backend" ;
    ex:mentionsEntity ex:entity-neo4j, ex:entity-fastapi .
```

---

## SPARQL Deduplication Query

```sparql
# Find duplicate entities (same owl:sameAs URI)
SELECT ?entity1 ?entity2 ?sameAsURI WHERE {
  ?entity1 owl:sameAs ?sameAsURI .
  ?entity2 owl:sameAs ?sameAsURI .
  FILTER(?entity1 != ?entity2)
}
```

**Merge Strategy:**
1. Keep entity with highest `ex:linkingConfidence`
2. Combine all `skos:altLabel` values
3. Update references to point to canonical entity
4. Delete duplicate

---

## Python Quick Start

```python
import pyspotlight

# Link entities
annotations = pyspotlight.annotate(
    'http://localhost:2222/rest/annotate',
    'I use Neo4j and Kubernetes',
    confidence=0.3
)

for ann in annotations:
    print(f"{ann['surfaceForm']}: {ann['URI']} (confidence: {ann['similarityScore']})")
```

**Output:**
```
Neo4j: http://dbpedia.org/resource/Neo4j (confidence: 1.0)
Kubernetes: http://dbpedia.org/resource/Kubernetes (confidence: 1.0)
```

---

## Docker Deployment

```bash
# Start DBpedia Spotlight (English model)
docker run -d --name dbpedia-spotlight -p 2222:80 \
  dbpedia/dbpedia-spotlight spotlight-english

# Test endpoint
curl -G "http://localhost:2222/rest/annotate" \
  --data-urlencode "text=I use Neo4j" \
  --data-urlencode "confidence=0.3" \
  -H "Accept: application/json" | jq .
```

**Resource Requirements:**
- RAM: 2-4 GB
- Disk: 1-2 GB
- Startup: ~60 seconds

---

## Cost Analysis

| Component | Cost |
|-----------|------|
| DBpedia Spotlight Docker | $0 (compute only) |
| Wikidata SPARQL API | $0 (public endpoint) |
| pyspotlight | $0 (open source) |
| **Total** | **$0** |

**Compute:** ~0.5 vCPU + 3 GB RAM for local Spotlight instance.

---

## Next Steps for DevKG

1. **Deploy DBpedia Spotlight:**
   ```bash
   docker run -d -p 2222:80 dbpedia/dbpedia-spotlight spotlight-english
   ```

2. **Install Python libraries:**
   ```bash
   pip install pyspotlight SPARQLWrapper
   ```

3. **Build abbreviation dictionary:**
   - Extract from session logs (regex: `(\w{2,5})\s*\(([^)]+)\)`)
   - Example: "k8s (Kubernetes)" → `{'k8s': 'Kubernetes'}`

4. **Integrate into `jsonl_to_rdf.py`:**
   - Add entity linking step before RDF generation
   - Store `owl:sameAs` triples

5. **Run on existing sessions:**
   - Test on `ec11ec1e` (research session) and `ddxplus` (medical session)
   - Validate URIs manually

6. **Add deduplication query:**
   - Merge entities with same `owl:sameAs` URI
   - Update SPARQL queries to use canonical entities

---

## References

- **Full Assessment:** `dbpedia-entity-linking-assessment.md`
- **Quick Start Guide:** `entity-linking-quickstart.md`
- **DBpedia Spotlight:** https://www.dbpedia-spotlight.org/
- **Wikidata SPARQL:** https://query.wikidata.org/
- **pyspotlight:** https://github.com/ubergrape/pyspotlight

---

## Decision

✅ **Proceed with DBpedia Spotlight + Wikidata hybrid approach**

**Rationale:**
1. DBpedia Spotlight provides best developer experience (REST API, confidence scoring)
2. Local Docker deployment = no rate limits, no cost, private
3. Wikidata fills coverage gaps for new tools
4. owl:sameAs enables cross-KB queries
5. Total cost: $0 (only compute for Docker container)

**Acceptance Criteria:**
- Link 90%+ of technical entities from session logs
- Confidence threshold >= 0.7 for stored entities
- Deduplication merges entities across sessions
- Abbreviations normalized via pre-processing dictionary
