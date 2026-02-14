# Entity Linking Quick Start Guide

**Goal:** Link DevKG entities to DBpedia/Wikidata URIs in 3 steps.

---

## Step 1: Deploy DBpedia Spotlight (Local)

```bash
# Start DBpedia Spotlight English model
docker run -d \
  --name dbpedia-spotlight \
  -p 2222:80 \
  dbpedia/dbpedia-spotlight spotlight-english

# Wait ~60s for model to load, then test
curl -G "http://localhost:2222/rest/annotate" \
  --data-urlencode "text=I use Neo4j and Kubernetes" \
  --data-urlencode "confidence=0.3" \
  -H "Accept: application/json" | jq .
```

**Expected output:**
```json
{
  "Resources": [
    {
      "@URI": "http://dbpedia.org/resource/Neo4j",
      "@surfaceForm": "Neo4j",
      "@similarityScore": "1.0"
    },
    {
      "@URI": "http://dbpedia.org/resource/Kubernetes",
      "@surfaceForm": "Kubernetes",
      "@similarityScore": "1.0"
    }
  ]
}
```

---

## Step 2: Install Python Libraries

```bash
pip install pyspotlight SPARQLWrapper rdflib
```

---

## Step 3: Entity Linking Script

Save as `devkg_entity_linker.py`:

```python
#!/usr/bin/env python3
"""DevKG Entity Linker - Links entities to DBpedia/Wikidata URIs."""

import pyspotlight
from SPARQLWrapper import SPARQLWrapper, JSON
from typing import List, Dict

# Abbreviation normalization dictionary
TECH_ABBREVIATIONS = {
    'k8s': 'Kubernetes',
    'GH': 'GitHub',
    'VS Code': 'Visual Studio Code',
    'i18n': 'internationalization',
    'a11y': 'accessibility',
    'n11s': 'neosemantics',
}

def normalize_text(text: str) -> str:
    """Replace known abbreviations with full names."""
    for abbr, full in TECH_ABBREVIATIONS.items():
        text = text.replace(abbr, full)
    return text

def link_with_dbpedia(text: str, confidence: float = 0.7) -> List[Dict]:
    """Link entities using DBpedia Spotlight."""
    try:
        annotations = pyspotlight.annotate(
            'http://localhost:2222/rest/annotate',  # Local Docker
            text,
            confidence=0.3,  # Low threshold for extraction
            support=10
        )
        return [
            {
                'label': ann['surfaceForm'],
                'uri': ann['URI'],
                'confidence': ann['similarityScore'],
                'types': ann.get('types', '').split(','),
                'source': 'dbpedia'
            }
            for ann in (annotations or [])
            if ann['similarityScore'] >= confidence
        ]
    except Exception as e:
        print(f"DBpedia error: {e}")
        return []

def link_with_wikidata(term: str) -> Dict:
    """Search Wikidata for entity URI."""
    sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
    query = f"""
    SELECT ?item ?itemLabel ?description WHERE {{
      SERVICE wikibase:mwapi {{
        bd:serviceParam wikibase:api "EntitySearch" .
        bd:serviceParam wikibase:endpoint "www.wikidata.org" .
        bd:serviceParam mwapi:search "{term}" .
        bd:serviceParam mwapi:language "en" .
        ?item wikibase:apiOutputItem mwapi:item .
      }}
      OPTIONAL {{ ?item schema:description ?description. FILTER(LANG(?description) = "en") }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
    }}
    LIMIT 1
    """
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)

    try:
        results = sparql.query().convert()
        bindings = results["results"]["bindings"]
        if bindings:
            result = bindings[0]
            return {
                'label': term,
                'uri': result['item']['value'],
                'wikidata_label': result['itemLabel']['value'],
                'description': result.get('description', {}).get('value', ''),
                'source': 'wikidata'
            }
    except Exception as e:
        print(f"Wikidata error for '{term}': {e}")
    return None

def link_entities(text: str, fallback_to_wikidata: bool = True) -> List[Dict]:
    """
    Link entities using DBpedia Spotlight, fallback to Wikidata.

    Args:
        text: Input text with entity mentions
        fallback_to_wikidata: If True, search Wikidata for unlinked terms

    Returns:
        List of entity dictionaries with URIs
    """
    # Normalize abbreviations
    normalized_text = normalize_text(text)

    # Step 1: DBpedia Spotlight
    entities = link_with_dbpedia(normalized_text)

    # Step 2: Wikidata fallback (optional)
    if fallback_to_wikidata:
        # Extract potential entity mentions not covered by DBpedia
        # (This is simplified - use NER in production)
        linked_labels = {e['label'].lower() for e in entities}

        # Example: Hardcoded terms to check (replace with NER)
        candidate_terms = ['FastAPI', 'Supabase', 'Pydantic', 'LangChain']

        for term in candidate_terms:
            if term.lower() in text.lower() and term.lower() not in linked_labels:
                wikidata_entity = link_with_wikidata(term)
                if wikidata_entity:
                    entities.append(wikidata_entity)

    return entities

def generate_rdf_triples(entities: List[Dict], session_id: str) -> str:
    """Generate RDF Turtle for linked entities."""
    from rdflib import Graph, Namespace, Literal, URIRef
    from rdflib.namespace import RDF, RDFS, OWL, SKOS

    g = Graph()
    EX = Namespace("http://devkg.local/")
    PROV = Namespace("http://www.w3.org/ns/prov#")

    g.bind('ex', EX)
    g.bind('owl', OWL)
    g.bind('skos', SKOS)
    g.bind('prov', PROV)

    for i, ent in enumerate(entities):
        entity_uri = EX[f"entity-{ent['label'].lower().replace(' ', '-')}"]

        # Entity as SKOS Concept
        g.add((entity_uri, RDF.type, SKOS.Concept))
        g.add((entity_uri, SKOS.prefLabel, Literal(ent['label'], lang='en')))

        # Link to external KB
        g.add((entity_uri, OWL.sameAs, URIRef(ent['uri'])))

        # Provenance
        g.add((entity_uri, PROV.wasGeneratedBy, EX[f"session-{session_id}"]))
        g.add((entity_uri, EX.linkingSource, Literal(ent['source'])))

        if 'confidence' in ent:
            g.add((entity_uri, EX.linkingConfidence, Literal(ent['confidence'])))

    return g.serialize(format='turtle')

# Example usage
if __name__ == '__main__':
    # Test cases
    test_texts = [
        "I use Neo4j for graph databases and Kubernetes for container orchestration",
        "FastAPI is a modern Python web framework, and Supabase is a Firebase alternative",
        "We deploy with k8s and use VS Code as our IDE"
    ]

    for text in test_texts:
        print(f"\n{'='*80}")
        print(f"Input: {text}")
        print(f"{'='*80}")

        entities = link_entities(text)

        if entities:
            print("\nLinked Entities:")
            for ent in entities:
                source = ent['source'].upper()
                confidence = f" (confidence: {ent.get('confidence', 'N/A')})" if 'confidence' in ent else ""
                print(f"  [{source}] {ent['label']}: {ent['uri']}{confidence}")

            # Generate RDF
            print("\nRDF Turtle:")
            print(generate_rdf_triples(entities, session_id="test-2025-02-14"))
        else:
            print("  No entities found.")
```

---

## Usage Examples

### Basic Linking

```bash
python devkg_entity_linker.py
```

**Output:**
```
================================================================================
Input: I use Neo4j for graph databases and Kubernetes for container orchestration
================================================================================

Linked Entities:
  [DBPEDIA] Neo4j: http://dbpedia.org/resource/Neo4j (confidence: 1.0)
  [DBPEDIA] graph databases: http://dbpedia.org/resource/Graph_database (confidence: 1.0)
  [DBPEDIA] Kubernetes: http://dbpedia.org/resource/Kubernetes (confidence: 1.0)

RDF Turtle:
@prefix ex: <http://devkg.local/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:entity-neo4j a skos:Concept ;
    owl:sameAs <http://dbpedia.org/resource/Neo4j> ;
    skos:prefLabel "Neo4j"@en ;
    prov:wasGeneratedBy ex:session-test-2025-02-14 ;
    ex:linkingConfidence 1.0 ;
    ex:linkingSource "dbpedia" .
```

### Integrate into DevKG Pipeline

```python
# In jsonl_to_rdf.py
from devkg_entity_linker import link_entities, normalize_text

def extract_entities_from_message(message_content: str) -> List[Dict]:
    """Extract and link entities from Claude Code message."""

    # Normalize abbreviations
    normalized = normalize_text(message_content)

    # Link entities
    entities = link_entities(normalized, fallback_to_wikidata=True)

    return entities

# Usage in session processing
for message in session_messages:
    entities = extract_entities_from_message(message['content'])

    for entity in entities:
        # Add to RDF graph
        entity_uri = EX[f"entity-{entity['label'].lower().replace(' ', '-')}"]
        g.add((entity_uri, RDF.type, SKOS.Concept))
        g.add((entity_uri, SKOS.prefLabel, Literal(entity['label'], lang='en')))
        g.add((entity_uri, OWL.sameAs, URIRef(entity['uri'])))

        # Link message to entity
        message_uri = EX[f"message-{message['id']}"]
        g.add((message_uri, EX.mentionsEntity, entity_uri))
```

---

## Troubleshooting

### Issue: DBpedia Spotlight not responding

```bash
# Check Docker container status
docker ps | grep dbpedia-spotlight

# Check logs
docker logs dbpedia-spotlight

# Restart if needed
docker restart dbpedia-spotlight
```

### Issue: Low linking accuracy

**Adjust confidence threshold:**

```python
# Lower threshold for more entities (may include false positives)
entities = link_with_dbpedia(text, confidence=0.5)

# Higher threshold for precision (may miss some entities)
entities = link_with_dbpedia(text, confidence=0.9)
```

### Issue: Abbreviations not recognized

**Add to dictionary:**

```python
TECH_ABBREVIATIONS = {
    'k8s': 'Kubernetes',
    'GH': 'GitHub',
    'TS': 'TypeScript',  # Add custom mappings
    'py': 'Python',
}
```

---

## Next Steps

1. **Deploy in DevKG pipeline:**
   - Integrate `link_entities()` into `jsonl_to_rdf.py`
   - Run on existing session logs
   - Store `owl:sameAs` links in Fuseki

2. **Improve abbreviation dictionary:**
   - Extract patterns from session logs (regex: `\b\w{2,5}\b` followed by full form in parentheses)
   - Crowdsource from community (GitHub Gist)

3. **Add entity deduplication:**
   - SPARQL query to merge entities with same `owl:sameAs` URI
   - Update `skos:altLabel` with all surface forms

4. **Evaluate linking accuracy:**
   - Sample 100 entities from session logs
   - Manually verify URIs
   - Calculate precision/recall

---

## Resources

- DBpedia Spotlight Demo: https://www.dbpedia-spotlight.org/demo/
- Wikidata Query Service: https://query.wikidata.org/
- pyspotlight Docs: https://github.com/ubergrape/pyspotlight
- RDFLib Tutorial: https://rdflib.readthedocs.io/
