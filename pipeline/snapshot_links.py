#!/usr/bin/env python3
"""
Generate wikidata_links.ttl from the SQLite cache + .ttl input files.

Use this to inspect intermediate results while link_entities.py is still running.
Does NOT interfere with the running process (reads cache in read-only mode).

Usage:
    .venv/bin/python -m pipeline.snapshot_links --input output/claude/*.ttl --output output/claude/wikidata_links_snapshot.ttl
"""

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import RDF, OWL, RDFS, DCTERMS

from pipeline.common import DEVKG, WD, entity_uri, create_graph
from pipeline.link_entities import (
    extract_entities_from_ttl,
    load_aliases,
    normalize_label,
    CACHE_DB,
    CONFIDENCE_THRESHOLD,
)


def main():
    parser = argparse.ArgumentParser(description="Snapshot wikidata links from cache")
    parser.add_argument("--input", nargs="+", required=True, dest="ttl_inputs")
    parser.add_argument("--output", required=True, dest="output_path")
    args = parser.parse_args()

    aliases = load_aliases()

    # Read cache in read-only mode (won't block the running process)
    conn = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True)

    # Extract entities from .ttl files
    raw_labels = extract_entities_from_ttl(args.ttl_inputs)
    normalized = list(dict.fromkeys(
        normalize_label(lbl, aliases) for lbl in raw_labels
    ))

    g = create_graph()
    g.bind("wd", WD)

    linked = 0
    cached = 0
    uncached = 0
    linked_pairs = []

    for label in normalized:
        uri = entity_uri(label)
        g.add((uri, RDF.type, DEVKG.Entity))
        g.add((uri, RDFS.label, Literal(label, lang="en")))

        row = conn.execute(
            "SELECT qid, description, confidence FROM wikidata_cache WHERE label = ?",
            (label.lower(),),
        ).fetchone()

        if row is None:
            uncached += 1
            continue

        cached += 1
        qid, description, confidence = row
        if qid and confidence and confidence >= CONFIDENCE_THRESHOLD:
            wd_uri = WD[qid]
            g.add((uri, OWL.sameAs, wd_uri))
            if description:
                g.add((uri, DCTERMS.description, Literal(description, lang="en")))
            linked += 1
            linked_pairs.append((uri, qid))

    # Dedup
    qid_to_uris = defaultdict(list)
    for u, q in linked_pairs:
        qid_to_uris[q].append(u)
    dedup = 0
    for qid, uris in qid_to_uris.items():
        if len(uris) > 1:
            canonical = uris[0]
            for other in uris[1:]:
                g.add((other, OWL.sameAs, canonical))
                dedup += 1

    with open(args.output_path, "w") as f:
        f.write(g.serialize(format="turtle"))

    total = len(normalized)
    print(f"Entities: {total}")
    print(f"In cache: {cached} ({cached/total*100:.0f}%)")
    print(f"Not yet cached: {uncached} ({uncached/total*100:.0f}%)")
    print(f"Linked (≥{CONFIDENCE_THRESHOLD}): {linked}")
    print(f"Deduplicated: {dedup}")
    print(f"Output: {args.output_path}")

    conn.close()


if __name__ == "__main__":
    main()
