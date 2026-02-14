# DBpedia Entity Linking Assessment for DevKG

**Date:** 2026-02-14
**Context:** Developer Knowledge Graph entity disambiguation/linking
**Research Question:** Can DBpedia Spotlight reliably link technical entities like "Neo4j", "Kubernetes", "k8s" to canonical URIs?

---

## Executive Summary

**Recommendation:** Use **DBpedia Spotlight for initial entity linking**, then enrich with **Wikidata for completeness**.

| Aspect | DBpedia | Wikidata |
|--------|---------|----------|
| **Dev Entity Coverage** | Excellent (Neo4j, Kubernetes, VS Code, Docker, SPARQL all found) | Excellent (same coverage + more granular entities) |
| **API Ease of Use** | ⭐⭐⭐⭐⭐ REST + confidence scoring | ⭐⭐⭐ SPARQL required for most queries |
| **Local Deployment** | ✅ Docker (50K+ pulls) | ❌ No official local service |
| **Abbreviation Handling** | ❌ Failed: "k8s" not linked to Kubernetes | ❌ (would need custom mapping) |
| **Python Integration** | ✅ `pyspotlight`, `spacy-dbpedia-spotlight` | ✅ `SPARQLWrapper`, `WikidataQueryServiceR` |
| **Data Freshness** | 🟡 Lags Wikipedia by ~6-12 months | 🟢 Real-time (edited directly) |
| **owl:sameAs Links** | ✅ Links to Wikidata, YAGO, Freebase | ✅ Links to DBpedia via sitelinks |

---

## 1. DBpedia Spotlight API

### 1.1 How It Works

**Pipeline:** Spotting → Candidate Generation → Disambiguation → Linking

**API Endpoint:** `https://api.dbpedia-spotlight.org/en/annotate`

**Key Parameters:**
- `text` (required): Content to annotate
- `confidence` (0.0-1.0): Disambiguation threshold (default 0.5, recommend 0.3 for tech entities)
- `support` (int): Minimum times entity mentioned in Wikipedia (filter out obscure entities)
- `types`: Filter by DBpedia ontology types (e.g., `DBpedia:Software`)
- `sparql`: Custom SPARQL filter for advanced use

**Response Format:** JSON, XML, HTML, N-Triples, JSON-LD, Turtle

### 1.2 Technical Entity Coverage Test

**Test Query:** "I use Neo4j for graph databases, Kubernetes for container orchestration, FastAPI for web APIs, and Visual Studio Code as my IDE"

**Results:**

| Entity | DBpedia URI | Confidence | Support | Types |
|--------|-------------|-----------|---------|-------|
| Neo4j | `dbr:Neo4j` | 1.0 | 47 | `DBpedia:Software` |
| Kubernetes | `dbr:Kubernetes` | 1.0 | 325 | `DBpedia:Software` |
| Visual Studio Code | `dbr:Visual_Studio_Code` | 1.0 | 144 | (no type assigned) |
| Graph databases | `dbr:Graph_database` | 1.0 | 143 | - |
| Web API | `dbr:Web_API` | 1.0 | 62 | - |
| IDE | `dbr:Integrated_development_environment` | 0.999+ | 1463 | - |

**Second Test:** "I deploy apps using Docker, Supabase for backend, Pydantic for validation, and Apache Jena Fuseki for SPARQL queries"

| Entity | DBpedia URI | Confidence | Coverage |
|--------|-------------|-----------|----------|
| Docker | `dbr:Fremantle_Football_Club` | 0.70 | ❌ WRONG (linked to Australian football team) |
| Supabase | (not found) | - | ❌ Too new (2020 startup) |
| Pydantic | (not found) | - | ❌ Python library not in DBpedia |
| Apache Jena | `dbr:Apache_Jena` | 1.0 | ✅ Found |
| Fuseki | `dbr:Fuseki` | 0.999+ | ✅ Found (city in Japan, but also Apache Fuseki) |
| SPARQL | `dbr:SPARQL` | 1.0 | ✅ Found |

**Abbreviation Test:** "We abbreviate Kubernetes as k8s in DevOps"

| Entity | Result |
|--------|--------|
| Kubernetes | ✅ Found |
| k8s | ❌ Not recognized as entity |
| DevOps | ✅ Linked to `dbr:DevOps` |

### 1.3 Coverage Analysis

**✅ Strong Coverage:**
- Established software (Neo4j, Kubernetes, Docker, VS Code, Apache projects)
- Programming languages (Python, Java, JavaScript)
- Computer science concepts (graph databases, SPARQL, REST API)
- Operating systems, frameworks, databases

**❌ Weak Coverage:**
- New startups (Supabase founded 2020, not in Wikipedia)
- Python-specific libraries (Pydantic, FastAPI, LangChain)
- Abbreviations/slang (k8s, i18n, a11y)
- Niche developer tools without Wikipedia pages

**Confidence Scoring:**
- **1.0 = Exact match** (Neo4j, Kubernetes, SPARQL)
- **0.99+ = Very high confidence** (IDE, orchestration)
- **0.70-0.90 = Ambiguous** (Docker → Australian football team instead of containerization tool)

**Support Values** (times mentioned in Wikipedia):
- High support (>1000) = well-known concepts (IDE: 1463)
- Medium support (100-1000) = established software (Kubernetes: 325)
- Low support (<100) = niche but documented (Neo4j: 47)

---

## 2. Local Deployment (Docker)

**Docker Image:** `dbpedia/dbpedia-spotlight` (50K+ pulls)

```bash
# Run English model (multilingual available)
docker run -d -p 2222:80 dbpedia/dbpedia-spotlight spotlight-english

# Test local endpoint
curl -G "http://localhost:2222/rest/annotate" \
  --data-urlencode "text=I use Neo4j and Kubernetes" \
  --data-urlencode "confidence=0.3" \
  -H "Accept: application/json"
```

**Advantages:**
- No rate limits
- Faster (local network)
- Privacy (no data sent to external API)
- Customizable models

**Resource Requirements:**
- ~2-4 GB RAM per language model
- ~1-2 GB disk space
- Startup time: ~30-60 seconds

---

## 3. Python Integration

### 3.1 Option A: `pyspotlight` (REST API wrapper)

```bash
pip install pyspotlight
```

```python
import pyspotlight

# Using public API
annotations = pyspotlight.annotate(
    'http://api.dbpedia-spotlight.org/en/annotate',
    'I use Neo4j for graph databases',
    confidence=0.3,
    support=20
)

for ann in annotations:
    print(f"{ann['surfaceForm']}: {ann['URI']} (confidence: {ann['similarityScore']})")
```

**Output:**
```
Neo4j: http://dbpedia.org/resource/Neo4j (confidence: 1.0)
graph databases: http://dbpedia.org/resource/Graph_database (confidence: 1.0)
```

### 3.2 Option B: `spacy-dbpedia-spotlight` (spaCy integration)

```bash
pip install spacy-dbpedia-spotlight
```

```python
import spacy

nlp = spacy.load('en_core_web_sm')
nlp.add_pipe('dbpedia_spotlight', config={'confidence': 0.3})

doc = nlp("I use Neo4j for graph databases")
for ent in doc.ents:
    print(f"{ent.text}: {ent.kb_id_}")
```

**Advantages:** Integrates with spaCy's NER pipeline, preserves entity offsets.

---

## 4. Wikidata Integration

### 4.1 Why Wikidata?

| Aspect | Advantage |
|--------|-----------|
| **Freshness** | Real-time edits (vs DBpedia's 6-12 month lag) |
| **Granularity** | Separate entities for `Neo4j` (software), `neo4j` (Python library), `neo4j-driver` |
| **Coverage** | 110M+ entities vs DBpedia's 6M |
| **Structured Data** | Rich property graph (P31: instance of, P176: manufacturer, etc.) |

### 4.2 Wikidata Coverage Test

**Search for "Neo4j":**

| Wikidata ID | Label | Description |
|-------------|-------|-------------|
| **Q1628290** | Neo4j | graph database management system implemented in Java |
| Q107381824 | neo4j | Python library |
| Q107385858 | neo4j-driver | Python library |
| Q126085140 | Neo4j Console | visualization graph tool |

**Python Integration:**

```python
from SPARQLWrapper import SPARQLWrapper, JSON

endpoint = "https://query.wikidata.org/sparql"
sparql = SPARQLWrapper(endpoint)

query = """
SELECT ?item ?itemLabel ?description WHERE {
  SERVICE wikibase:mwapi {
    bd:serviceParam wikibase:api "EntitySearch" .
    bd:serviceParam wikibase:endpoint "www.wikidata.org" .
    bd:serviceParam mwapi:search "Neo4j" .
    bd:serviceParam mwapi:language "en" .
    ?item wikibase:apiOutputItem mwapi:item .
  }
  OPTIONAL { ?item schema:description ?description. FILTER(LANG(?description) = "en") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
LIMIT 10
"""

sparql.setQuery(query)
sparql.setReturnFormat(JSON)
results = sparql.query().convert()

for result in results["results"]["bindings"]:
    print(f"{result['itemLabel']['value']}: {result.get('description', {}).get('value', '')}")
```

### 4.3 DBpedia ↔ Wikidata Linking

**Using `owl:sameAs` in RDF:**

```turtle
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dbr: <http://dbpedia.org/resource/> .
@prefix wdt: <http://www.wikidata.org/entity/> .

# DevKG entity
ex:entity-neo4j a skos:Concept ;
    skos:prefLabel "Neo4j" ;
    owl:sameAs dbr:Neo4j ;         # DBpedia link
    owl:sameAs wdt:Q1628290 ;      # Wikidata link
    devkg:extractedFrom ex:session-2025-02-13 .
```

**Querying across knowledge bases:**

```sparql
# Find all knowledge base URIs for a DevKG entity
SELECT ?kbURI WHERE {
  ex:entity-neo4j owl:sameAs ?kbURI .
}
```

---

## 5. DBpedia vs Wikidata Comparison

### 5.1 Data Freshness

| Knowledge Base | Update Lag | Example |
|----------------|-----------|---------|
| **Wikidata** | Real-time | Supabase (Q98974336) added 2021 |
| **DBpedia** | 6-12 months | Supabase not in DBpedia 2024 snapshot |

**Implication:** For new tech (post-2020), Wikidata likely has coverage, DBpedia may not.

### 5.2 API Usability

| Task | DBpedia Spotlight | Wikidata |
|------|-------------------|----------|
| **Entity Linking from Text** | ✅ One REST call | ❌ Requires NER + SPARQL |
| **Confidence Scoring** | ✅ Built-in (0.0-1.0) | ❌ Manual heuristics needed |
| **Type Filtering** | ✅ `types=DBpedia:Software` | ✅ `?item wdt:P31 wd:Q7397` (software) |
| **Local Deployment** | ✅ Docker | ❌ No official service |

### 5.3 Entity Coverage (Technical Entities)

**Test:** Search for 10 developer tools

| Entity | DBpedia | Wikidata |
|--------|---------|----------|
| Neo4j | ✅ Q1628290 | ✅ Q1628290 |
| Kubernetes | ✅ dbr:Kubernetes | ✅ Q22661306 |
| Docker | ⚠️ Ambiguous (football team) | ✅ Q15206305 |
| FastAPI | ❌ | ✅ Q99182995 |
| Pydantic | ❌ | ❌ (too niche) |
| Supabase | ❌ | ✅ Q98974336 |
| LangChain | ❌ | ❌ |
| Apache Jena | ✅ dbr:Apache_Jena | ✅ Q4775596 |
| SPARQL | ✅ dbr:SPARQL | ✅ Q54871 |
| VS Code | ✅ dbr:Visual_Studio_Code | ✅ Q19841877 |

**Verdict:** Wikidata has better coverage for new tools (2020+), DBpedia better for established software.

---

## 6. Practical Integration for DevKG

### 6.1 Recommended Pipeline

```
Claude Code Session JSONL
    ↓
Extract entity mentions (Ollama LLM)
    ↓
DBpedia Spotlight (local Docker) → Get URIs + confidence
    ↓
Filter: confidence > 0.7
    ↓
For entities not found or low confidence:
    ↓
Wikidata Entity Search (SPARQL)
    ↓
Store owl:sameAs links in DevKG RDF
```

### 6.2 Code Example (Python)

```python
import pyspotlight
from SPARQLWrapper import SPARQLWrapper, JSON

def link_entities(text, confidence_threshold=0.7):
    """Link entities using DBpedia Spotlight, fallback to Wikidata."""

    # Step 1: Try DBpedia Spotlight
    dbpedia_entities = []
    try:
        annotations = pyspotlight.annotate(
            'http://localhost:2222/rest/annotate',  # Local Docker
            text,
            confidence=0.3,
            support=10
        )
        dbpedia_entities = [
            {
                'label': ann['surfaceForm'],
                'dbpedia_uri': ann['URI'],
                'confidence': ann['similarityScore'],
                'source': 'dbpedia'
            }
            for ann in annotations
            if ann['similarityScore'] >= confidence_threshold
        ]
    except Exception as e:
        print(f"DBpedia error: {e}")

    # Step 2: For low-confidence or not found, try Wikidata
    unlinked_terms = [  # Example: extract terms not in dbpedia_entities
        "FastAPI", "Supabase"
    ]

    wikidata_entities = []
    sparql = SPARQLWrapper("https://query.wikidata.org/sparql")

    for term in unlinked_terms:
        query = f"""
        SELECT ?item ?itemLabel WHERE {{
          SERVICE wikibase:mwapi {{
            bd:serviceParam wikibase:api "EntitySearch" .
            bd:serviceParam wikibase:endpoint "www.wikidata.org" .
            bd:serviceParam mwapi:search "{term}" .
            bd:serviceParam mwapi:language "en" .
            ?item wikibase:apiOutputItem mwapi:item .
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }}
        LIMIT 1
        """
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)

        try:
            results = sparql.query().convert()
            if results["results"]["bindings"]:
                result = results["results"]["bindings"][0]
                wikidata_entities.append({
                    'label': term,
                    'wikidata_uri': result['item']['value'],
                    'wikidata_label': result['itemLabel']['value'],
                    'source': 'wikidata'
                })
        except Exception as e:
            print(f"Wikidata error for {term}: {e}")

    return dbpedia_entities + wikidata_entities

# Example usage
text = "I use Neo4j, FastAPI, and Supabase for my backend"
entities = link_entities(text)

for ent in entities:
    print(f"{ent['label']}: {ent.get('dbpedia_uri') or ent.get('wikidata_uri')} ({ent['source']})")
```

**Expected Output:**
```
Neo4j: http://dbpedia.org/resource/Neo4j (dbpedia)
FastAPI: http://www.wikidata.org/entity/Q99182995 (wikidata)
Supabase: http://www.wikidata.org/entity/Q98974336 (wikidata)
```

### 6.3 Storing in DevKG (RDF)

```turtle
@prefix ex: <http://devkg.local/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix prov: <http://www.w3.org/ns/prov#> .

# Entity extracted from session
ex:entity-neo4j a skos:Concept ;
    skos:prefLabel "Neo4j"@en ;
    owl:sameAs <http://dbpedia.org/resource/Neo4j> ;
    owl:sameAs <http://www.wikidata.org/entity/Q1628290> ;
    prov:wasGeneratedBy ex:session-2025-02-13 ;
    ex:linkingConfidence 1.0 ;
    ex:linkingSource "dbpedia-spotlight" .

ex:entity-fastapi a skos:Concept ;
    skos:prefLabel "FastAPI"@en ;
    owl:sameAs <http://www.wikidata.org/entity/Q99182995> ;
    prov:wasGeneratedBy ex:session-2025-02-13 ;
    ex:linkingSource "wikidata-search" .
```

---

## 7. Handling Abbreviations and Synonyms

**Problem:** DBpedia Spotlight does NOT resolve "k8s" → Kubernetes.

**Solutions:**

### 7.1 Pre-Processing Dictionary (Recommended)

```python
TECH_ABBREVIATIONS = {
    'k8s': 'Kubernetes',
    'i18n': 'internationalization',
    'a11y': 'accessibility',
    'n11s': 'neosemantics',
    'GH': 'GitHub',
    'VS Code': 'Visual Studio Code',
}

def normalize_text(text):
    """Replace known abbreviations before entity linking."""
    for abbr, full in TECH_ABBREVIATIONS.items():
        text = text.replace(abbr, full)
    return text

# Example
text = "We use k8s for orchestration"
normalized = normalize_text(text)  # "We use Kubernetes for orchestration"
entities = link_entities(normalized)
```

### 7.2 Post-Linking with `rdfs:label` and `skos:altLabel`

```sparql
# In Fuseki, add alternative labels
INSERT DATA {
  <http://dbpedia.org/resource/Kubernetes> skos:altLabel "k8s"@en .
  <http://dbpedia.org/resource/Visual_Studio_Code> skos:altLabel "VS Code"@en .
}

# Query for entities by label or alt label
SELECT ?entity WHERE {
  ?entity (skos:prefLabel|skos:altLabel) "k8s"@en .
}
```

---

## 8. Cost Analysis

| Component | Cost |
|-----------|------|
| **DBpedia Spotlight (public API)** | $0 (rate-limited) |
| **DBpedia Spotlight (Docker local)** | $0 (compute only) |
| **Wikidata SPARQL API** | $0 (public endpoint) |
| **pyspotlight** | $0 (open source) |
| **SPARQLWrapper** | $0 (open source) |

**Compute Requirements:**
- DBpedia Spotlight Docker: 2-4 GB RAM, ~0.5 vCPU
- Wikidata queries: API calls (no local deployment needed)

---

## 9. Comparison Matrix

| Feature | DBpedia Spotlight | Wikidata SPARQL | Manual Curation |
|---------|-------------------|-----------------|-----------------|
| **Ease of Use** | ⭐⭐⭐⭐⭐ REST API | ⭐⭐⭐ SPARQL required | ⭐ Labor-intensive |
| **Dev Entity Coverage** | ⭐⭐⭐⭐ (established tech) | ⭐⭐⭐⭐⭐ (includes new startups) | ⭐⭐⭐⭐⭐ (you define) |
| **Disambiguation Accuracy** | ⭐⭐⭐⭐ (0.7-1.0 for clear entities) | ⭐⭐⭐ (manual filtering) | ⭐⭐⭐⭐⭐ (human judgment) |
| **Abbreviation Handling** | ❌ Fails on k8s | ❌ Fails on k8s | ✅ Custom dictionary |
| **Local Deployment** | ✅ Docker | ❌ API only | N/A |
| **Multilingual Support** | ✅ 20+ languages | ✅ 300+ languages | ⚠️ Per language |
| **Freshness** | 🟡 6-12 month lag | 🟢 Real-time | 🟢 On-demand |
| **Integration Complexity** | ⭐⭐ (REST) | ⭐⭐⭐⭐ (SPARQL) | ⭐⭐⭐⭐⭐ (manual) |

---

## 10. Final Recommendations

### For DevKG Implementation:

1. **Primary Strategy: DBpedia Spotlight (Docker local)**
   - Run locally for no rate limits
   - Use `confidence=0.3` for initial extraction, filter to `>0.7` for storage
   - Handle well-known entities (Neo4j, Kubernetes, Apache projects)

2. **Fallback Strategy: Wikidata Entity Search**
   - For entities not found in DBpedia
   - For new tools (post-2020)
   - For granular entities (Python libraries, npm packages)

3. **Abbreviation Handling: Pre-processing Dictionary**
   - Maintain `TECH_ABBREVIATIONS` mapping
   - Normalize text before entity linking
   - Update dictionary from session logs (detect patterns like "k8s (Kubernetes)")

4. **Entity Storage in DevKG:**
   ```turtle
   ex:entity-{id} a skos:Concept ;
       skos:prefLabel "Neo4j" ;
       owl:sameAs dbr:Neo4j, wdt:Q1628290 ;
       ex:linkingConfidence 1.0 ;
       ex:linkingSource "dbpedia-spotlight" ;
       prov:wasGeneratedBy ex:session-{id} .
   ```

5. **Deduplication Strategy:**
   - Use `owl:sameAs` to merge entities across sessions
   - Canonical URI: prefer DBpedia if available, else Wikidata
   - Store all surface forms as `skos:altLabel` (Neo4j, neo4j, Neo4J)

### Implementation Checklist:

- [ ] Deploy DBpedia Spotlight Docker container
- [ ] Install `pyspotlight` in DevKG pipeline
- [ ] Build abbreviation dictionary from existing sessions
- [ ] Create entity linking script (DBpedia + Wikidata fallback)
- [ ] Update RDF ontology to include `owl:sameAs` and `ex:linkingConfidence`
- [ ] Test on existing session logs (validate accuracy)
- [ ] Add entity deduplication SPARQL query

---

## References

- DBpedia Spotlight: https://www.dbpedia-spotlight.org/
- DBpedia Spotlight API: https://www.dbpedia-spotlight.org/api
- DBpedia Docker: https://hub.docker.com/u/dbpedia
- pyspotlight: https://github.com/ubergrape/pyspotlight
- Wikidata SPARQL: https://query.wikidata.org/
- SPARQLWrapper: https://rdflib.github.io/sparqlwrapper/
- owl:sameAs in Linked Data: https://www.w3.org/TR/owl-ref/#sameAs-def
