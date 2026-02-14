#!/usr/bin/env python3
"""
Wikidata entity linking for DevKG.

Links extracted entities from the knowledge graph to Wikidata,
creating owl:sameAs triples. Supports SQLite caching, alias
normalization, and batch mode from .ttl files.

Usage:
    # Text file mode (original)
    python -m pipeline.link_entities entities.txt output.ttl

    # Batch mode from .ttl files
    python -m pipeline.link_entities --input output/*.ttl --output output/wikidata_links.ttl

Dependencies:
    pip install qwikidata rdflib requests
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

import requests
from qwikidata.linked_data_interface import get_entity_dict_from_api
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, OWL, RDFS, SKOS, DCTERMS

from pipeline.common import DEVKG, DATA, WD, entity_uri, create_graph

# ---------------------------------------------------------------------------
# Agentic linker (lazy import)
# ---------------------------------------------------------------------------

_agentic_initialized = False


def _ensure_agentic_init():
    """Initialize Vertex AI credentials once for agentic linking."""
    global _agentic_initialized
    if not _agentic_initialized:
        from pipeline.agentic_linker_langgraph import _init_vertex_credentials
        _init_vertex_credentials()
        _agentic_initialized = True


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.7

ALIASES_FILE = Path(__file__).parent / "entity_aliases.json"
CACHE_DB = Path(__file__).parent / ".entity_cache.db"

TECH_KEYWORDS = [
    'software', 'database', 'framework', 'library', 'programming',
    'language', 'tool', 'platform', 'application', 'system',
    'service', 'api', 'protocol', 'standard', 'specification',
    'technology', 'infrastructure', 'container', 'orchestration',
]

HEADERS = {
    'User-Agent': 'DevKG-EntityLinker/1.0 (https://github.com/devkg/research) Python/requests'
}

# ---------------------------------------------------------------------------
# Alias normalization
# ---------------------------------------------------------------------------

def load_aliases() -> Dict[str, str]:
    """Load alias mappings from entity_aliases.json."""
    if not ALIASES_FILE.exists():
        return {}
    with open(ALIASES_FILE) as f:
        return json.load(f)


def normalize_label(label: str, aliases: Dict[str, str]) -> str:
    """Normalize an entity label through alias mapping.

    Returns the canonical form if found, otherwise the original label
    (lowercased and stripped).
    """
    key = label.strip().lower()
    return aliases.get(key, label.strip())

# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

def init_cache(db_path: Path = CACHE_DB) -> sqlite3.Connection:
    """Create / open the entity cache database."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wikidata_cache (
            label TEXT PRIMARY KEY,
            qid TEXT,
            description TEXT,
            confidence REAL,
            last_queried TEXT
        )
    """)
    conn.commit()
    return conn


def cache_get(conn: sqlite3.Connection, label: str) -> Optional[Dict]:
    """Look up a cached Wikidata result. Returns None on miss."""
    row = conn.execute(
        "SELECT qid, description, confidence FROM wikidata_cache WHERE label = ?",
        (label.lower(),),
    ).fetchone()
    if row is None:
        return None
    qid, description, confidence = row
    if qid is None:
        # Previously searched but not found
        return {"qid": None, "description": None, "confidence": 0.0}
    return {"qid": qid, "description": description, "confidence": confidence}


def cache_put(
    conn: sqlite3.Connection,
    label: str,
    qid: Optional[str],
    description: Optional[str],
    confidence: float,
) -> None:
    """Insert or replace a cache entry."""
    conn.execute(
        """INSERT OR REPLACE INTO wikidata_cache
           (label, qid, description, confidence, last_queried)
           VALUES (?, ?, ?, ?, ?)""",
        (label.lower(), qid, description, confidence,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

# ---------------------------------------------------------------------------
# Wikidata API
# ---------------------------------------------------------------------------

def search_wikidata(entity_name: str, max_results: int = 5) -> List[Dict]:
    """Search Wikidata for entity by name using wbsearchentities API."""
    try:
        url = "https://www.wikidata.org/w/api.php"
        params = {
            'action': 'wbsearchentities',
            'search': entity_name,
            'language': 'en',
            'format': 'json',
            'limit': max_results,
        }

        # Rate limiting: 1 request per second
        time.sleep(1)

        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('search', []):
            results.append({
                'id': item['id'],
                'label': item.get('label', ''),
                'description': item.get('description', ''),
                'aliases': item.get('aliases', []),
            })
        return results
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print("Rate limit or blocked by Wikidata API. Waiting 5s...", file=sys.stderr)
            time.sleep(5)
        print(f"Error searching {entity_name}: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Error searching {entity_name}: {e}", file=sys.stderr)
        return []


def select_best_match(entity_name: str, results: List[Dict]) -> Optional[Dict]:
    """Heuristic to select best Wikidata match for a tech entity.

    Priority: exact label match > alias match > tech keyword in description > first result.
    """
    if not results:
        return None

    name_lower = entity_name.lower()

    # Exact label match
    for r in results:
        if r['label'].lower() == name_lower:
            return r

    # Alias match
    for r in results:
        if any(alias.lower() == name_lower for alias in r.get('aliases', [])):
            return r

    # Tech keywords in description
    for r in results:
        desc = r.get('description', '').lower()
        if any(kw in desc for kw in TECH_KEYWORDS):
            return r

    return results[0]

# ---------------------------------------------------------------------------
# Entity extraction from .ttl files
# ---------------------------------------------------------------------------

def extract_entities_from_ttl(ttl_paths: List[str]) -> List[str]:
    """Extract unique entity labels from .ttl files.

    Finds all resources with rdf:type devkg:Entity and rdfs:label,
    deduplicates, and returns sorted labels.
    """
    labels = set()
    for path in ttl_paths:
        g = Graph()
        try:
            g.parse(path, format='turtle')
        except Exception as e:
            print(f"Warning: could not parse {path}: {e}", file=sys.stderr)
            continue

        for entity_node in g.subjects(RDF.type, DEVKG.Entity):
            for label_lit in g.objects(entity_node, RDFS.label):
                labels.add(str(label_lit).strip())

    return sorted(labels)

# ---------------------------------------------------------------------------
# Core linking logic
# ---------------------------------------------------------------------------

def link_entity_list(
    entity_labels: List[str],
    output_file: str,
    aliases: Dict[str, str],
    cache_conn: sqlite3.Connection,
    verbose: bool = True,
    agentic: bool = True,
) -> None:
    """Link a list of entity labels to Wikidata and write RDF output.

    When agentic=True (default), uses the LangGraph ReAct agent for
    disambiguation. When False, falls back to heuristic matching.
    """
    g = create_graph()
    g.bind("wd", WD)
    g.bind("skos", SKOS)

    linked = 0
    unlinked = 0
    low_confidence = 0
    cached_hits = 0
    ambiguous = []
    linked_pairs = []  # (uri, qid) for deduplication

    if verbose:
        mode = "agentic (LangGraph)" if agentic else "heuristic"
        print(f"Processing {len(entity_labels)} entities (mode: {mode})...")

    for raw_label in entity_labels:
        # Alias normalization
        label = normalize_label(raw_label, aliases)
        if label != raw_label and verbose:
            print(f"\n  alias: '{raw_label}' -> '{label}'")

        if verbose:
            print(f"\nSearching: {label}")

        uri = entity_uri(label)
        g.add((uri, RDF.type, DEVKG.Entity))
        g.add((uri, RDFS.label, Literal(label, lang='en')))

        # Check cache first
        cached = cache_get(cache_conn, label)
        if cached is not None:
            cached_hits += 1
            if cached["qid"]:
                confidence = cached.get("confidence", 0.5)
                if confidence >= CONFIDENCE_THRESHOLD:
                    wd_uri = WD[cached["qid"]]
                    g.add((uri, OWL.sameAs, wd_uri))
                    g.add((uri, DCTERMS.description, Literal(cached["description"], lang='en')))
                    linked += 1
                    linked_pairs.append((uri, cached["qid"]))
                    if verbose:
                        print(f"  [cache] {cached['qid']}: {cached['description']} (conf={confidence:.2f})")
                else:
                    low_confidence += 1
                    if verbose:
                        print(f"  [cache] {cached['qid']} below threshold (conf={confidence:.2f})", file=sys.stderr)
            else:
                unlinked += 1
                if verbose:
                    print(f"  [cache] not found")
            continue

        if agentic:
            # --- Agentic linking via LangGraph ReAct agent ---
            from pipeline.agentic_linker_langgraph import link_entity as agentic_link_entity
            try:
                match_result, elapsed = agentic_link_entity(label, context="developer knowledge graph entity")
                qid = match_result.qid
                confidence = match_result.confidence
                description = match_result.description

                if verbose:
                    print(f"  agent: {qid} conf={confidence:.2f} ({elapsed:.1f}s) — {match_result.reasoning[:80]}")

                if qid and qid.lower() not in ("none", "error", ""):
                    if confidence >= CONFIDENCE_THRESHOLD:
                        wd_uri = WD[qid]
                        g.add((uri, OWL.sameAs, wd_uri))
                        g.add((uri, DCTERMS.description, Literal(description, lang='en')))
                        linked += 1
                        linked_pairs.append((uri, qid))
                    else:
                        low_confidence += 1
                        print(f"  [low-conf] {label} -> {qid} conf={confidence:.2f}, skipped", file=sys.stderr)

                    cache_put(cache_conn, label, qid, description, confidence)
                else:
                    cache_put(cache_conn, label, None, None, 0.0)
                    unlinked += 1
            except Exception as e:
                print(f"  [error] agentic linking failed for '{label}': {e}", file=sys.stderr)
                cache_put(cache_conn, label, None, None, 0.0)
                unlinked += 1
        else:
            # --- Heuristic linking (original behavior) ---
            results = search_wikidata(label)
            match = select_best_match(label, results)

            if match:
                qid = match['id']
                description = match.get('description', 'N/A')

                # Confidence: 1.0 for exact match, 0.8 for tech keyword, 0.5 fallback
                if match['label'].lower() == label.lower():
                    confidence = 1.0
                elif any(kw in match.get('description', '').lower() for kw in TECH_KEYWORDS):
                    confidence = 0.8
                else:
                    confidence = 0.5

                if confidence >= CONFIDENCE_THRESHOLD:
                    wd_uri = WD[qid]
                    g.add((uri, OWL.sameAs, wd_uri))
                    g.add((uri, DCTERMS.description, Literal(description, lang='en')))
                    linked += 1
                    linked_pairs.append((uri, qid))

                    for alias in match.get('aliases', [])[:5]:
                        g.add((uri, SKOS.altLabel, Literal(alias, lang='en')))
                else:
                    low_confidence += 1
                    print(f"  [low-conf] {label} -> {qid} conf={confidence:.2f}, skipped", file=sys.stderr)

                cache_put(cache_conn, label, qid, description, confidence)

                if verbose:
                    print(f"  -> {qid}: {description} (conf={confidence:.2f})")

                # Ambiguity detection
                tech_matches = [r for r in results if any(
                    kw in r.get('description', '').lower() for kw in TECH_KEYWORDS
                )]
                if len(tech_matches) > 1:
                    ambiguous.append((label, qid, [r['id'] for r in tech_matches]))
            else:
                cache_put(cache_conn, label, None, None, 0.0)
                unlinked += 1
                if verbose:
                    print(f"  x not found")

    # --- Entity deduplication: entities sharing the same QID ---
    from collections import defaultdict
    qid_to_uris = defaultdict(list)
    for entity_uri_val, qid in linked_pairs:
        qid_to_uris[qid].append(entity_uri_val)

    dedup_count = 0
    for qid, uris in qid_to_uris.items():
        if len(uris) > 1:
            canonical = uris[0]
            for other in uris[1:]:
                g.add((other, OWL.sameAs, canonical))
                dedup_count += 1
                if verbose:
                    print(f"\n  [dedup] {other} == {canonical} (both {qid})")

    # Write output
    with open(output_file, 'w') as f:
        f.write(g.serialize(format='turtle'))

    if verbose:
        total = len(entity_labels)
        print(f"\n{'='*60}")
        print(f"Summary")
        print(f"{'='*60}")
        print(f"Total entities:    {total}")
        print(f"Linked:            {linked} ({linked/total*100:.1f}%)" if total else "")
        print(f"Unlinked:          {unlinked} ({unlinked/total*100:.1f}%)" if total else "")
        print(f"Low confidence:    {low_confidence}")
        print(f"Cache hits:        {cached_hits}")
        print(f"Deduplicated:      {dedup_count}")

        if not agentic and ambiguous:
            print(f"Ambiguous:         {len(ambiguous)}")
            print(f"\n{'='*60}")
            print("Ambiguous matches (manual review recommended):")
            print(f"{'='*60}")
            for entity, selected_qid, all_qids in ambiguous:
                print(f"  {entity}: selected {selected_qid}")
                other = [q for q in all_qids if q != selected_qid]
                if other:
                    print(f"    Other candidates: {', '.join(other[:3])}")

        print(f"\nOutput: {output_file}")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Link DevKG entities to Wikidata (owl:sameAs triples).",
    )
    parser.add_argument(
        "entity_file", nargs="?", default=None,
        help="Text file with entity names, one per line (legacy mode)",
    )
    parser.add_argument(
        "output_file_pos", nargs="?", default=None,
        help="Output .ttl file path (legacy mode)",
    )
    parser.add_argument(
        "--input", nargs="+", dest="ttl_inputs",
        help="One or more .ttl files to extract entities from (batch mode)",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help="Output .ttl file path (batch mode)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress progress output",
    )
    parser.add_argument(
        "--heuristic", action="store_true",
        help="Use heuristic linking instead of agentic (LangGraph) linking",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    verbose = not args.quiet
    agentic = not args.heuristic
    aliases = load_aliases()
    cache_conn = init_cache()

    # Initialize Vertex AI credentials for agentic mode
    if agentic:
        _ensure_agentic_init()

    # Batch mode: --input *.ttl --output out.ttl
    if args.ttl_inputs:
        if not args.output_path:
            parser.error("--output is required when using --input")

        if verbose:
            print(f"Batch mode: reading {len(args.ttl_inputs)} .ttl file(s)...")

        labels = extract_entities_from_ttl(args.ttl_inputs)
        if not labels:
            print("No entities with rdf:type devkg:Entity found.", file=sys.stderr)
            sys.exit(1)

        # Normalize through aliases and deduplicate
        normalized = list(dict.fromkeys(
            normalize_label(lbl, aliases) for lbl in labels
        ))
        if verbose:
            print(f"Found {len(labels)} raw entities, {len(normalized)} after alias normalization")

        link_entity_list(normalized, args.output_path, aliases, cache_conn, verbose, agentic=agentic)

    # Legacy mode: positional args entity_file output_file
    elif args.entity_file and args.output_file_pos:
        with open(args.entity_file) as f:
            labels = [line.strip() for line in f if line.strip()]

        link_entity_list(labels, args.output_file_pos, aliases, cache_conn, verbose, agentic=agentic)

    else:
        parser.print_help()
        sys.exit(1)

    cache_conn.close()


if __name__ == '__main__':
    main()
