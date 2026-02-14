#!/usr/bin/env python3
"""
Wikidata entity linking for DevKG.

This script links extracted entities from the knowledge graph to Wikidata
using the qwikidata library and direct API calls, creating owl:sameAs triples.

Usage:
    python link_entities.py entities.txt output.ttl

Dependencies:
    pip install qwikidata rdflib requests
"""

import sys
import time
import requests
from typing import Optional, List, Dict
from qwikidata.linked_data_interface import get_entity_dict_from_api
from rdflib import Graph, URIRef, Namespace, Literal
from rdflib.namespace import OWL, RDFS, SKOS, DCTERMS

# Namespaces
DEVKG = Namespace("http://devkg.local/")
WD = Namespace("http://www.wikidata.org/entity/")

# Tech-related keywords for disambiguation
TECH_KEYWORDS = [
    'software', 'database', 'framework', 'library', 'programming',
    'language', 'tool', 'platform', 'application', 'system',
    'service', 'API', 'protocol', 'standard', 'specification',
    'technology', 'infrastructure', 'container', 'orchestration'
]


def search_wikidata(entity_name: str, max_results: int = 5) -> List[Dict]:
    """
    Search Wikidata for entity by name using wbsearchentities API.

    Args:
        entity_name: Name to search for
        max_results: Maximum number of results to return

    Returns:
        List of search results (dicts with id, label, description)
    """
    try:
        url = "https://www.wikidata.org/w/api.php"
        params = {
            'action': 'wbsearchentities',
            'search': entity_name,
            'language': 'en',
            'format': 'json',
            'limit': max_results
        }
        headers = {
            'User-Agent': 'DevKG-EntityLinker/1.0 (https://github.com/devkg/research) Python/requests'
        }

        # Rate limiting: 1 request per second
        time.sleep(1)

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Convert API response to simpler format
        results = []
        for item in data.get('search', []):
            results.append({
                'id': item['id'],
                'label': item.get('label', ''),
                'description': item.get('description', ''),
                'aliases': item.get('aliases', [])
            })
        return results
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            print(f"Rate limit or blocked by Wikidata API. Waiting 5s...", file=sys.stderr)
            time.sleep(5)
        print(f"Error searching {entity_name}: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Error searching {entity_name}: {e}", file=sys.stderr)
        return []


def select_best_match(entity_name: str, results: List[Dict]) -> Optional[Dict]:
    """
    Heuristic to select best Wikidata match for a tech entity.

    Prioritizes:
    1. Exact label match
    2. Software/tech keywords in description
    3. First result (if no better match)

    Args:
        entity_name: Original entity name
        results: List of Wikidata search results

    Returns:
        Best matching result dict or None
    """
    if not results:
        return None

    # Exact match (case-insensitive)
    for r in results:
        if r['label'].lower() == entity_name.lower():
            return r

    # Check aliases for exact match
    for r in results:
        aliases = r.get('aliases', [])
        if any(alias.lower() == entity_name.lower() for alias in aliases):
            return r

    # Tech keywords in description
    for r in results:
        desc = r.get('description', '').lower()
        if any(kw in desc for kw in TECH_KEYWORDS):
            return r

    # Fallback to first result
    return results[0]


def get_entity_details(qid: str) -> Optional[Dict]:
    """
    Fetch detailed entity data from Wikidata using qwikidata.

    Args:
        qid: Wikidata QID (e.g., "Q1628290")

    Returns:
        Dict with entity details or None
    """
    try:
        entity_dict = get_entity_dict_from_api(qid)
        if not entity_dict:
            return None

        # Extract relevant fields
        labels = entity_dict.get('labels', {})
        descriptions = entity_dict.get('descriptions', {})
        aliases = entity_dict.get('aliases', {})

        return {
            'label': labels.get('en', {}).get('value', ''),
            'description': descriptions.get('en', {}).get('value', ''),
            'aliases': [a['value'] for a in aliases.get('en', [])],
            'claims': entity_dict.get('claims', {})
        }
    except Exception as e:
        print(f"Error fetching details for {qid}: {e}", file=sys.stderr)
        return None


def create_entity_uri(entity_name: str) -> URIRef:
    """
    Create a valid URI for an entity name.

    Args:
        entity_name: Human-readable entity name

    Returns:
        URIRef for the entity
    """
    # Replace spaces and special chars with underscores
    safe_name = entity_name.replace(' ', '_').replace('-', '_').replace('.', '_')
    return DEVKG[safe_name]


def link_entities(entity_file: str, output_file: str, verbose: bool = True):
    """
    Link entities to Wikidata and generate RDF.

    Args:
        entity_file: Path to file with entity names (one per line)
        output_file: Path to output Turtle file
        verbose: Print progress information
    """
    g = Graph()
    g.bind("devkg", DEVKG)
    g.bind("wd", WD)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)

    # Read entities
    with open(entity_file) as f:
        entities = [line.strip() for line in f if line.strip()]

    if verbose:
        print(f"Processing {len(entities)} entities...")

    linked = 0
    unlinked = 0
    ambiguous = []

    for entity_name in entities:
        if verbose:
            print(f"\nSearching: {entity_name}")

        results = search_wikidata(entity_name)
        match = select_best_match(entity_name, results)

        devkg_uri = create_entity_uri(entity_name)

        # Always add label
        g.add((devkg_uri, RDFS.label, Literal(entity_name, lang='en')))

        if match:
            qid = match['id']
            description = match.get('description', 'N/A')
            wd_uri = WD[qid]

            # Create owl:sameAs link
            g.add((devkg_uri, OWL.sameAs, wd_uri))
            g.add((devkg_uri, DCTERMS.description, Literal(description, lang='en')))

            # Add aliases if available
            aliases = match.get('aliases', [])
            for alias in aliases[:5]:  # Limit to 5 aliases
                g.add((devkg_uri, SKOS.altLabel, Literal(alias, lang='en')))

            if verbose:
                print(f"  ✓ Linked to {qid}: {description}")

            # Flag if multiple good matches (potential ambiguity)
            tech_matches = [r for r in results if any(
                kw in r.get('description', '').lower() for kw in TECH_KEYWORDS
            )]
            if len(tech_matches) > 1:
                ambiguous.append((entity_name, qid, [r['id'] for r in tech_matches]))

            linked += 1
        else:
            # Create local entity (no Wikidata link)
            g.add((devkg_uri, DCTERMS.description,
                   Literal("Entity not found in Wikidata", lang='en')))

            if verbose:
                print(f"  ✗ Not found in Wikidata")
            unlinked += 1

    # Save RDF
    with open(output_file, 'w') as f:
        f.write(g.serialize(format='turtle'))

    # Print summary
    if verbose:
        print(f"\n{'='*60}")
        print(f"Summary")
        print(f"{'='*60}")
        print(f"Total entities: {len(entities)}")
        print(f"Linked:         {linked} ({linked/len(entities)*100:.1f}%)")
        print(f"Unlinked:       {unlinked} ({unlinked/len(entities)*100:.1f}%)")
        print(f"Ambiguous:      {len(ambiguous)}")

        if ambiguous:
            print(f"\n{'='*60}")
            print(f"Ambiguous matches (manual review recommended):")
            print(f"{'='*60}")
            for entity, selected_qid, all_qids in ambiguous:
                print(f"{entity}: selected {selected_qid}")
                print(f"  Other candidates: {', '.join(all_qids[1:4])}")

        print(f"\nOutput: {output_file}")


def main():
    """CLI entry point."""
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <entities.txt> <output.ttl> [--quiet]")
        print("\nExample:")
        print(f"  {sys.argv[0]} entities.txt devkg_wikidata_links.ttl")
        sys.exit(1)

    entity_file = sys.argv[1]
    output_file = sys.argv[2]
    verbose = '--quiet' not in sys.argv

    try:
        link_entities(entity_file, output_file, verbose=verbose)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
