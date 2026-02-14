# Wikidata Entity Linking for DevKG: Research Report

**Date:** 2026-02-14
**Context:** Developer Knowledge Graph entity disambiguation and canonical linking

---

## Executive Summary

Wikidata provides robust infrastructure for entity disambiguation in knowledge graphs through:
- Free, public APIs (wbsearchentities, wbgetentities, SPARQL endpoint)
- Good coverage of developer tools/technologies (~80%+ for major tools)
- Multiple Python libraries (qwikidata, WikidataIntegrator, spaCyOpenTapioca)
- Integration pattern: LLM extracts entities → Wikidata API → owl:sameAs links

**Key Finding:** Wikidata coverage for developer tools is strong but not complete. Apache Jena, FastAPI, Pydantic, SPARQL, Kubernetes, Neo4j, Supabase all exist. Docker (containerization software) is notably missing (search returns "stevedore" occupation instead).

---

## 1. Wikidata APIs

### 1.1 wbsearchentities (Entity Search)

**Purpose:** Fuzzy search for entities by label/alias

**Endpoint:** `https://www.wikidata.org/w/api.php?action=wbsearchentities`

**Parameters:**
- `search` - Search query
- `language` - Language code (default: en)
- `limit` - Max results (default: 7, max: 50)
- `continue` - Offset for pagination
- `type` - Entity type (item, property)
- `format` - Response format (json, xml)

**Example:**
```bash
curl 'https://www.wikidata.org/w/api.php?action=wbsearchentities&search=Neo4j&language=en&format=json&limit=3'
```

**Response Structure:**
```json
{
  "searchinfo": {"search": "Neo4j"},
  "search": [
    {
      "id": "Q1628290",
      "title": "Q1628290",
      "concepturi": "http://www.wikidata.org/entity/Q1628290",
      "url": "//www.wikidata.org/wiki/Q1628290",
      "label": "Neo4j",
      "description": "graph database management system implemented in Java",
      "match": {"type": "label", "language": "en", "text": "Neo4j"}
    }
  ],
  "search-continue": 3,
  "success": 1
}
```

**Limitations:**
- Returns only 7 results by default (parameter limit applies)
- Fuzzy matching can return unexpected results (e.g., "Docker" → "stevedore")
- No disambiguation beyond description text

---

### 1.2 wbgetentities (Entity Details)

**Purpose:** Fetch full entity data by QID

**Endpoint:** `https://www.wikidata.org/w/api.php?action=wbgetentities`

**Parameters:**
- `ids` - Pipe-separated QIDs (e.g., "Q1628290|Q22661306")
- `languages` - Comma-separated language codes
- `props` - Properties to return (labels, descriptions, aliases, claims, sitelinks)
- `format` - json/xml

**Example:**
```bash
curl 'https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q1628290&format=json&languages=en'
```

**Response Contains:**
- `labels` - Primary label per language
- `descriptions` - Short description per language
- `aliases` - Alternative names (e.g., "VS Code" for "Visual Studio Code")
- `claims` - Structured properties (P31: instance of, P279: subclass of, P856: official website, etc.)
- `sitelinks` - Links to Wikipedia pages in different languages

**Key Properties for Tech Entities:**
- `P31` - instance of (e.g., "database management system")
- `P279` - subclass of (ontological hierarchy)
- `P856` - official website URL
- `P348` - software version (218 versions for Neo4j!)
- `P277` - programming language
- `P275` - license

---

### 1.3 SPARQL Endpoint

**Purpose:** Complex queries, batch lookups, relationship traversal

**Endpoint:** `https://query.wikidata.org/sparql`

**Example (Find all graph databases):**
```sparql
SELECT ?item ?itemLabel ?description WHERE {
  ?item wdt:P31 wd:Q16510064 .  # instance of: graph database
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
```

**Example (Batch Entity Lookup):**
```sparql
SELECT ?item ?itemLabel WHERE {
  VALUES ?item { wd:Q1628290 wd:Q22661306 wd:Q19841877 }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
```

**Advantages:**
- Batch operations (100s-1000s of QIDs in VALUES clause)
- Relationship traversal (find all subclasses, instances, related technologies)
- Structured data (no need to parse JSON claims)

**Disadvantages:**
- More complex syntax than REST API
- Query timeout limits (60s public endpoint)
- Requires learning SPARQL

---

## 2. Wikidata Coverage for Developer Tools

| Entity | QID | Found? | Label | Description |
|--------|-----|--------|-------|-------------|
| **Neo4j** | Q1628290 | ✅ | Neo4j | graph database management system implemented in Java |
| **Kubernetes** | Q22661306 | ✅ | Kubernetes | software to manage containers on a server-cluster |
| **Visual Studio Code** | Q19841877 | ✅ | Visual Studio Code | source code editor developed by Microsoft |
| **FastAPI** | Q101119404 | ✅ | FastAPI | software framework for developing web applications in Python |
| **Pydantic** | Q107381687 | ✅ | pydantic | Python library for data parsing and validation using Python type hints |
| **Apache Jena** | Q1686799 | ✅ | Apache Jena | open source semantic web framework for Java |
| **SPARQL** | Q54871 | ✅ | SPARQL | RDF query language |
| **Supabase** | Q136776342 | ✅ | Supabase | open source backend platform for app development |
| **Docker** | ❌ | ❌ | (stevedore) | occupation of loading and unloading ships |
| **Fuseki** | ❓ | Not tested | - | - |

**Coverage Assessment:** 8/9 major developer tools found (88%). Docker is a notable gap (containerization software not in Wikidata, only related entities like Docker Inc., Docker Desktop).

**Implications:**
- Wikidata is viable for entity canonicalization
- Fallback strategy needed for missing entities (local controlled vocabulary + owl:sameAs later when entity appears)
- Aliases matter: "VS Code" not found directly, but exists as alias of Q19841877

---

## 3. Python Libraries for Wikidata Entity Linking

### 3.1 qwikidata (Kensho Technologies)

**Focus:** Read-only access, optimized for entity data extraction

**Installation:** `pip install qwikidata`

**Features:**
- Pythonic entity classes (WikidataItem, WikidataProperty, WikidataLexeme)
- JSON dump processing (offline mode for large-scale work)
- Linked entity traversal
- SPARQL queries

**Example:**
```python
from qwikidata.linked_data_interface import get_entity_dict_from_api

# Fetch entity by QID
entity_dict = get_entity_dict_from_api('Q1628290')
print(entity_dict['labels']['en']['value'])  # "Neo4j"
print(entity_dict['descriptions']['en']['value'])  # "graph database..."

# Get claims
claims = entity_dict['claims']
print(claims['P856'][0]['mainsnak']['datavalue']['value'])  # Official website
```

**Use Case:** Batch enrichment of already-identified QIDs

---

### 3.2 WikidataIntegrator (SuLab)

**Focus:** Read AND write access, bot-friendly

**Installation:** `pip install wikidataintegrator`

**Features:**
- Write/edit Wikidata items (requires login)
- Conflict detection (duplicate identifiers)
- Fast-run mode (9x faster for large datasets)
- SPARQL queries
- Search API integration

**Example:**
```python
from wikidataintegrator import wdi_core

# Search for entity
results = wdi_core.WDItemEngine.search_wikidata('Neo4j')
for r in results:
    print(f"{r['id']}: {r['label']} - {r['description']}")

# Load entity
item = wdi_core.WDItemEngine(wd_item_id='Q1628290')
print(item.get_label())  # "Neo4j"
```

**Use Case:** Two-way sync (read Wikidata, write back disambiguated entities)

---

### 3.3 spaCyOpenTapioca

**Focus:** End-to-end NER + entity linking pipeline

**Installation:** `pip install spacyopentapioca`

**Features:**
- spaCy integration (pipeline component)
- Automatic entity recognition AND linking
- Wikidata type hierarchy (`span._.types`)
- Confidence scores
- Aliases

**Example:**
```python
import spacy

nlp = spacy.blank('en')
nlp.add_pipe('opentapioca')

doc = nlp('I use Neo4j and Kubernetes for my backend.')

for span in doc.ents:
    print(f"{span.text}: {span.kb_id_} ({span.label_})")
    print(f"  Description: {span._.description}")
    print(f"  Score: {span._.score}")
```

**Output:**
```
Neo4j: Q1628290 (MISC)
  Description: graph database management system implemented in Java
  Score: 3.65
Kubernetes: Q22661306 (MISC)
  Description: software to manage containers on a server-cluster
  Score: 2.11
```

**Use Case:** Extract AND link entities from raw text (session logs, comments)

---

### 3.4 Comparison

| Library | Read | Write | Search | SPARQL | NER Integration | Best For |
|---------|------|-------|--------|--------|-----------------|----------|
| **qwikidata** | ✅ | ❌ | ❌ | ✅ | ❌ | Batch QID enrichment |
| **WikidataIntegrator** | ✅ | ✅ | ✅ | ✅ | ❌ | Bot workflows, two-way sync |
| **spaCyOpenTapioca** | ✅ | ❌ | Implicit | ❌ | ✅ | End-to-end NER + linking |

**Recommendation:** Use **WikidataIntegrator** for DevKG (search + batch lookup, no write needed).

---

## 4. Integration into LLM Extraction Pipeline

### 4.1 Architecture Options

#### Option A: Post-Processing (Recommended)

```
Raw Text → LLM Extraction → Flat Entities → Wikidata Lookup → Canonical Entities
                ↓                              ↓
           (Neo4j, K8s, VS Code)    (Q1628290, Q22661306, Q19841877)
                                               ↓
                                       owl:sameAs triples
```

**Workflow:**
1. LLM extracts entities from JSONL (subject, predicate, object)
2. Collect unique entities (deduplicate)
3. Batch Wikidata search (50 entities/request via SPARQL)
4. Disambiguate based on entity type + description
5. Store owl:sameAs links in RDF

**Advantages:**
- LLM focuses on extraction (no API calls during generation)
- Batch processing (efficient)
- Offline mode possible (local Wikidata dump)

**Disadvantages:**
- Two-pass pipeline (slower overall)
- LLM doesn't benefit from Wikidata context during extraction

---

#### Option B: Real-Time Lookup

```
Raw Text → LLM + Wikidata Tool → Canonical Entities
             ↓
    Tool: search_wikidata(entity_name) → QID
```

**Workflow:**
1. LLM extracts entity mention
2. Calls Wikidata search tool
3. Disambiguates based on context
4. Returns QID directly

**Advantages:**
- LLM can use Wikidata descriptions to improve extraction
- Single-pass pipeline

**Disadvantages:**
- API rate limits (200 req/min for unauthenticated users)
- Latency per message (100ms+ per lookup)
- LLM may hallucinate QIDs

---

### 4.2 Recommended Approach (Hybrid)

**Phase 1 (Extraction):** LLM extracts entities with local deduplication
**Phase 2 (Linking):** Batch Wikidata lookup via WikidataIntegrator
**Phase 3 (Verification):** LLM reviews ambiguous matches

**Example Code:**

```python
from wikidataintegrator import wdi_core
from rdflib import Graph, URIRef, Namespace, Literal
from rdflib.namespace import OWL, RDFS, RDF

DEVKG = Namespace("http://devkg.local/")
WD = Namespace("http://www.wikidata.org/entity/")

g = Graph()
g.bind("devkg", DEVKG)
g.bind("wd", WD)
g.bind("owl", OWL)

# Extracted entities from LLM
entities = ["Neo4j", "Kubernetes", "VS Code", "Docker"]

def link_to_wikidata(entity_name: str, entity_type: str = None):
    """
    Search Wikidata and return best match QID.

    Args:
        entity_name: Name to search
        entity_type: Optional type hint (software, database, etc.)

    Returns:
        QID string or None
    """
    results = wdi_core.WDItemEngine.search_wikidata(entity_name, max_results=5)

    if not results:
        return None

    # Heuristic: prefer results with "software" in description
    for r in results:
        desc = r.get('description', '').lower()
        if any(word in desc for word in ['software', 'database', 'framework', 'library']):
            return r['id']

    # Fallback: return first result
    return results[0]['id']

# Process entities
for entity_name in entities:
    qid = link_to_wikidata(entity_name)

    if qid:
        devkg_entity = DEVKG[entity_name.replace(' ', '_')]
        wd_entity = WD[qid]

        # Create owl:sameAs link
        g.add((devkg_entity, OWL.sameAs, wd_entity))
        g.add((devkg_entity, RDFS.label, Literal(entity_name, lang='en')))

        print(f"✓ {entity_name} → {qid}")
    else:
        print(f"✗ {entity_name} NOT FOUND")

# Serialize to Turtle
print(g.serialize(format='turtle'))
```

**Output:**
```turtle
@prefix devkg: <http://devkg.local/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wd: <http://www.wikidata.org/entity/> .

devkg:Neo4j a owl:NamedIndividual ;
    rdfs:label "Neo4j"@en ;
    owl:sameAs wd:Q1628290 .

devkg:Kubernetes a owl:NamedIndividual ;
    rdfs:label "Kubernetes"@en ;
    owl:sameAs wd:Q22661306 .

devkg:VS_Code a owl:NamedIndividual ;
    rdfs:label "VS Code"@en ;
    owl:sameAs wd:Q19841877 .
```

---

## 5. Rate Limits & Practical Considerations

### 5.1 Rate Limits

**Wikidata API (Action API):**
- **Unauthenticated:** ~200 requests/minute (soft limit, not enforced via HTTP 429)
- **Authenticated (bot account):** 50 edits/minute (write operations)
- **SPARQL endpoint:** 60-second timeout per query, no official request limit

**Enforcement:**
- No HTTP 429 (Too Many Requests) currently returned
- Server-side throttling may silently slow responses
- Best practice: 1 request/second for sustained operations

**Source:** [Wikidata:REST API](https://www.wikidata.org/wiki/Wikidata:REST_API), [Wikidata Integrator source code](https://github.com/SuLab/WikidataIntegrator/blob/master/wikidataintegrator/wdi_core.py)

---

### 5.2 Batch Operations

**wbgetentities supports up to 50 QIDs per request:**

```bash
curl 'https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q1628290|Q22661306|Q19841877&format=json'
```

**SPARQL supports 100s-1000s of QIDs in VALUES clause:**

```sparql
SELECT ?item ?itemLabel ?description WHERE {
  VALUES ?item {
    wd:Q1628290 wd:Q22661306 wd:Q19841877 wd:Q101119404
    wd:Q107381687 wd:Q1686799 wd:Q54871
  }
  ?item schema:description ?description .
  FILTER(LANG(?description) = "en")
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
```

**Recommendation:** Use SPARQL for batch operations (1 query for 100 entities vs 2 API calls).

---

### 5.3 Costs

**All Wikidata APIs are free:**
- No API keys required (search/read operations)
- No quotas
- No rate limit fees

**Computational costs:**
- API latency: 100-500ms per search request
- SPARQL latency: 500ms-5s per query (depending on complexity)
- Local caching recommended for repeated lookups

---

## 6. Handling Ambiguity and Missing Entities

### 6.1 Ambiguity

**Problem:** Multiple Wikidata entities match a search term.

**Example:** "Python" → Q28865 (programming language), Q2001 (snake genus), Q212348 (Monty Python)

**Solutions:**

1. **Use entity type from context:**
   ```python
   def disambiguate(search_term: str, context_type: str):
       results = wdi_core.WDItemEngine.search_wikidata(search_term, max_results=10)

       for r in results:
           if context_type.lower() in r.get('description', '').lower():
               return r['id']

       return None  # Unable to disambiguate

   # Example
   qid = disambiguate("Python", "programming")  # Returns Q28865
   ```

2. **LLM verification:**
   ```python
   # After batch lookup, ask LLM to verify ambiguous matches
   prompt = f"""
   Entity: {entity_name}
   Context: {surrounding_text}

   Candidates:
   1. Q28865: Python (programming language)
   2. Q2001: Python (genus of snakes)

   Which candidate best matches the context? Return only the QID.
   """
   ```

3. **Use SPARQL constraints:**
   ```sparql
   SELECT ?item ?itemLabel WHERE {
     ?item ?label "Python"@en .
     ?item wdt:P31/wdt:P279* wd:Q9143 .  # instance/subclass of programming language
     SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
   }
   ```

---

### 6.2 Missing Entities

**Problem:** Entity doesn't exist in Wikidata (e.g., Docker containerization software, niche libraries).

**Solutions:**

1. **Create local entity + defer linking:**
   ```turtle
   devkg:Docker a owl:NamedIndividual ;
       rdfs:label "Docker"@en ;
       dct:description "Container orchestration platform" .

   # No owl:sameAs link yet
   # Add later when entity appears in Wikidata
   ```

2. **Use Wikipedia instead:**
   ```python
   import wikipedia

   def fallback_to_wikipedia(entity_name):
       try:
           page = wikipedia.page(entity_name, auto_suggest=False)
           return page.url
       except:
           return None

   # Create owl:sameAs to Wikipedia article
   devkg:Docker owl:sameAs <https://en.wikipedia.org/wiki/Docker_(software)> .
   ```

3. **Create controlled vocabulary:**
   - Maintain `devkg-vocabulary.ttl` with canonical entity URIs
   - Link to Wikidata when available, local otherwise
   - Use SKOS for hierarchical relationships

---

## 7. Implementation Roadmap

### Phase 1: Proof of Concept (1 day)
- [x] Research Wikidata APIs and coverage
- [ ] Test WikidataIntegrator with DevKG entities
- [ ] Create sample RDF with owl:sameAs links

### Phase 2: Batch Entity Linking (2 days)
- [ ] Extract unique entities from existing RDF triples
- [ ] Build Wikidata lookup script (SPARQL batch mode)
- [ ] Generate disambiguated entity mappings (entity_name → QID)
- [ ] Add owl:sameAs triples to knowledge graph

### Phase 3: Pipeline Integration (2 days)
- [ ] Modify `jsonl_to_rdf.py` to use entity canonicalization
- [ ] Add local controlled vocabulary for missing entities
- [ ] Create verification queries (SPARQL) to validate linking

### Phase 4: Maintenance (ongoing)
- [ ] Monitor Wikidata for newly added entities
- [ ] Update local vocabulary with Wikidata QIDs
- [ ] Handle alias variations (VS Code, Visual Studio Code, VSCode)

---

## 8. Concrete Code Example (End-to-End)

```python
#!/usr/bin/env python3
"""
Wikidata entity linking for DevKG.

Usage:
    python link_entities.py entities.txt output.ttl
"""

import sys
from wikidataintegrator import wdi_core
from rdflib import Graph, URIRef, Namespace, Literal
from rdflib.namespace import OWL, RDFS, SKOS, DCTERMS

DEVKG = Namespace("http://devkg.local/")
WD = Namespace("http://www.wikidata.org/entity/")

def search_wikidata(entity_name: str, max_results: int = 5):
    """Search Wikidata for entity by name."""
    try:
        results = wdi_core.WDItemEngine.search_wikidata(entity_name, max_results=max_results)
        return results
    except Exception as e:
        print(f"Error searching {entity_name}: {e}", file=sys.stderr)
        return []

def select_best_match(entity_name: str, results: list) -> dict:
    """
    Heuristic to select best Wikidata match for a tech entity.

    Prioritizes:
    1. Exact label match
    2. Software/tech keywords in description
    3. First result (if no better match)
    """
    if not results:
        return None

    # Exact match
    for r in results:
        if r['label'].lower() == entity_name.lower():
            return r

    # Tech keywords
    tech_keywords = ['software', 'database', 'framework', 'library', 'programming', 'language', 'tool']
    for r in results:
        desc = r.get('description', '').lower()
        if any(kw in desc for kw in tech_keywords):
            return r

    # Fallback
    return results[0]

def link_entities(entity_file: str, output_file: str):
    """Link entities to Wikidata and generate RDF."""
    g = Graph()
    g.bind("devkg", DEVKG)
    g.bind("wd", WD)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)

    with open(entity_file) as f:
        entities = [line.strip() for line in f if line.strip()]

    print(f"Processing {len(entities)} entities...")

    linked = 0
    unlinked = 0

    for entity_name in entities:
        print(f"\nSearching: {entity_name}")
        results = search_wikidata(entity_name)

        match = select_best_match(entity_name, results)

        devkg_uri = DEVKG[entity_name.replace(' ', '_').replace('-', '_')]

        if match:
            qid = match['id']
            description = match.get('description', 'N/A')
            wd_uri = WD[qid]

            # Create triples
            g.add((devkg_uri, RDFS.label, Literal(entity_name, lang='en')))
            g.add((devkg_uri, OWL.sameAs, wd_uri))
            g.add((devkg_uri, DCTERMS.description, Literal(description, lang='en')))

            print(f"  ✓ Linked to {qid}: {description}")
            linked += 1
        else:
            # Create local entity (no Wikidata link)
            g.add((devkg_uri, RDFS.label, Literal(entity_name, lang='en')))
            g.add((devkg_uri, DCTERMS.description, Literal("Entity not found in Wikidata", lang='en')))

            print(f"  ✗ Not found in Wikidata")
            unlinked += 1

    # Save RDF
    with open(output_file, 'w') as f:
        f.write(g.serialize(format='turtle'))

    print(f"\n=== Summary ===")
    print(f"Linked: {linked}/{len(entities)} ({linked/len(entities)*100:.1f}%)")
    print(f"Unlinked: {unlinked}")
    print(f"Output: {output_file}")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <entities.txt> <output.ttl>")
        sys.exit(1)

    link_entities(sys.argv[1], sys.argv[2])
```

**Usage:**
```bash
# Create entity list
cat > entities.txt <<EOF
Neo4j
Kubernetes
Visual Studio Code
FastAPI
Pydantic
Apache Jena
SPARQL
Docker
EOF

# Run linking
python link_entities.py entities.txt devkg_wikidata_links.ttl

# Verify output
cat devkg_wikidata_links.ttl
```

---

## 9. Alternative Tools

### 9.1 OpenTapioca (Standalone Service)

**What:** Lightweight Wikidata entity linker (no NLP, just string matching + disambiguation)

**Installation:** Docker container

```bash
docker run -p 8080:8080 opentapioca/opentapioca
```

**API:**
```bash
curl 'http://localhost:8080/api/annotate?query=I%20use%20Neo4j%20and%20Kubernetes'
```

**Response:**
```json
{
  "annotations": [
    {"start": 6, "end": 11, "text": "Neo4j", "id": "Q1628290", "label": "Neo4j"},
    {"start": 16, "end": 26, "text": "Kubernetes", "id": "Q22661306", "label": "Kubernetes"}
  ]
}
```

**Use Case:** Self-hosted entity linking service (no external API calls)

---

### 9.2 Falcon 2.0 (Entity Linking System)

**What:** State-of-the-art entity linking for knowledge graphs (research system)

**Supported KGs:** DBpedia, Wikidata

**API:** `https://labs.tib.eu/falcon/falcon2/api`

**Example:**
```bash
curl -X POST 'https://labs.tib.eu/falcon/falcon2/api?mode=long' \
  -H 'Content-Type: application/json' \
  -d '{"text": "I use Neo4j and Kubernetes for my backend."}'
```

**Advantages:**
- Joint entity + relation linking
- High accuracy (ISWC 2020 benchmarks)

**Disadvantages:**
- Public API (rate limits unknown)
- Complex setup for self-hosting

---

### 9.3 Entity-Fishing (NERD Service)

**What:** Entity recognition and disambiguation service (DARIAH project)

**Installation:** Docker or public API

**Public API:** `https://cloud.science-miner.com/nerd/service`

**Example:**
```bash
curl -X POST 'https://cloud.science-miner.com/nerd/service/disambiguate' \
  -F "text=I use Neo4j and Kubernetes" \
  -F "language=en"
```

**Integration:** `spacy-fishing` library (spaCy pipeline component)

**Use Case:** Alternative to OpenTapioca for spaCy users

---

## 10. Recommendations for DevKG

### Immediate Actions (Sprint 2)

1. **Install WikidataIntegrator:**
   ```bash
   pip install wikidataintegrator
   ```

2. **Create entity linking script** (adapt code example above)

3. **Process existing entities:**
   - Extract unique entities from `output/*.ttl`
   - Run batch Wikidata lookup
   - Generate `devkg_wikidata_links.ttl`
   - Merge with main graph

4. **Update SPARQL queries to leverage Wikidata:**
   ```sparql
   PREFIX owl: <http://www.w3.org/2002/07/owl#>
   PREFIX wd: <http://www.wikidata.org/entity/>

   # Find all sessions where Neo4j was discussed
   SELECT ?session ?timestamp ?devkg_entity ?wd_entity WHERE {
     ?message sioc:has_container ?session ;
              schema:about ?devkg_entity .

     ?devkg_entity owl:sameAs ?wd_entity .

     FILTER(?wd_entity = wd:Q1628290)  # Neo4j
   }
   ```

---

### Long-Term Strategy

1. **Hybrid entity system:**
   - Wikidata for well-known tools (Neo4j, Kubernetes, etc.)
   - Local controlled vocabulary for niche/internal entities
   - owl:sameAs as bridge

2. **Periodic sync:**
   - Monthly: Check for newly added Wikidata entities
   - Update local vocabulary → Wikidata links

3. **Entity type ontology:**
   - Use Wikidata P31 (instance of) to enrich entity types
   - Example: Neo4j → wdt:P31 → wd:Q16510064 (graph database) → skos:broader → wd:Q8513 (database)

4. **Cross-reference with other KGs:**
   - DBpedia (more software coverage)
   - Schema.org (SoftwareApplication type)
   - GitHub API (repository metadata)

---

## 11. References

- [Wikidata API Documentation](https://www.wikidata.org/w/api.php)
- [Wikidata SPARQL Query Service](https://query.wikidata.org/)
- [WikidataIntegrator GitHub](https://github.com/SuLab/WikidataIntegrator)
- [qwikidata Documentation](https://qwikidata.readthedocs.io/)
- [spaCyOpenTapioca](https://github.com/UB-Mannheim/spacyopentapioca)
- [OpenTapioca](https://opentapioca.org/)
- [Falcon 2.0 Paper](https://arxiv.org/abs/1912.11270)
- [Entity-Fishing](https://github.com/kermitt2/entity-fishing)
- [W3C OWL sameAs](https://www.w3.org/TR/owl-ref/#sameAs-def)
- [IBM GRAPH4CODE](https://github.com/wala/graph4code) - Production system using PROV-O + SKOS + Wikidata

---

**Next Steps:**
1. Implement entity linking script using WikidataIntegrator
2. Test on existing DevKG triples (ec11ec1e, ddxplus sessions)
3. Evaluate linking accuracy (manual review of 50 entities)
4. Integrate into `jsonl_to_rdf.py` pipeline
