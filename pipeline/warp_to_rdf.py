#!/usr/bin/env python3
"""Convert Warp terminal AI conversation data (SQLite) to RDF Turtle.

Warp stores AI conversations in a SQLite database at:
  ~/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/
    dev.warp.Warp-Stable/warp.sqlite

Tables used:
  - agent_conversations: session metadata (conversation_id, conversation_data JSON)
  - ai_queries: individual AI exchanges (exchange_id, input JSON, model_id, etc.)

Usage:
    # List available conversations
    python -m pipeline.warp_to_rdf output.ttl

    # Process a specific conversation (by index from the list)
    python -m pipeline.warp_to_rdf output.ttl --conversation 0

    # Custom database path
    python -m pipeline.warp_to_rdf output.ttl --conversation 0 --db-path /path/to/warp.sqlite

    # Skip triple extraction (structure only)
    python -m pipeline.warp_to_rdf output.ttl --conversation 0 --skip-extraction

    # Custom Gemini model
    python -m pipeline.warp_to_rdf output.ttl --conversation 0 --model gemini-2.5-pro
"""

import json
import sqlite3
import sys
import time
import argparse
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import RDF, DCTERMS, XSD

from pipeline.common import (
    PROV, SIOC, DEVKG, DATA,
    slug, create_graph, create_session_node, create_developer_node,
    create_model_node, create_message_node, add_triples_to_graph,
)
from pipeline.triple_extraction import extract_triples_gemini


DEFAULT_DB_PATH = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "2BBY89MBSN.dev.warp"
    / "Library"
    / "Application Support"
    / "dev.warp.Warp-Stable"
    / "warp.sqlite"
)


def get_conversations(db_path: str) -> list[dict]:
    """Return all conversations from agent_conversations, ordered by last_modified_at desc."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, conversation_id, last_modified_at "
            "FROM agent_conversations ORDER BY last_modified_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_exchanges(db_path: str, conversation_id: str) -> list[dict]:
    """Return all ai_queries for a conversation, ordered by start_ts."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT exchange_id, conversation_id, start_ts, input, "
            "working_directory, output_status, model_id "
            "FROM ai_queries WHERE conversation_id = ? ORDER BY start_ts",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def extract_query_text(input_json: str) -> str:
    """Extract user query text from the ai_queries.input JSON field.

    The input field is a JSON array containing objects like:
        {"Query": {"text": "user question", "context": [...]}}
        {"ActionResult": {...}}

    We extract all Query.text values and join them.
    """
    try:
        items = json.loads(input_json)
    except (json.JSONDecodeError, TypeError):
        return ""

    if not isinstance(items, list):
        return ""

    texts = []
    for item in items:
        if isinstance(item, dict) and "Query" in item:
            query = item["Query"]
            if isinstance(query, dict) and "text" in query:
                texts.append(query["text"])
    return "\n".join(texts)


def list_conversations(db_path: str) -> None:
    """Print available conversations with index, id, date, and exchange count."""
    conversations = get_conversations(db_path)
    if not conversations:
        print("No conversations found in database.", file=sys.stderr)
        return

    conn = sqlite3.connect(db_path)
    try:
        print(f"\nFound {len(conversations)} conversations in {db_path}\n")
        print(f"{'Idx':>4}  {'Last Modified':<22}  {'Exchanges':>9}  {'Conversation ID'}")
        print("-" * 90)

        for idx, conv in enumerate(conversations):
            cid = conv["conversation_id"]
            count = conn.execute(
                "SELECT COUNT(*) FROM ai_queries WHERE conversation_id = ?",
                (cid,),
            ).fetchone()[0]

            # Get first query text as preview
            preview = ""
            first = conn.execute(
                "SELECT input FROM ai_queries WHERE conversation_id = ? ORDER BY start_ts LIMIT 1",
                (cid,),
            ).fetchone()
            if first:
                text = extract_query_text(first[0])
                if text:
                    preview = text[:60].replace("\n", " ")
                    if len(text) > 60:
                        preview += "..."

            modified = conv["last_modified_at"] or "unknown"
            print(f"{idx:>4}  {modified:<22}  {count:>9}  {cid[:36]}")
            if preview:
                print(f"      -> {preview}")
    finally:
        conn.close()


def build_graph(
    db_path: str,
    conversation_id: str,
    skip_extraction: bool = False,
    model=None,
):
    """Parse a Warp conversation and build an RDF graph."""
    g = create_graph()
    developer_uri = create_developer_node(g, "Roberto")

    exchanges = get_exchanges(db_path, conversation_id)
    if not exchanges:
        print(f"No exchanges found for conversation {conversation_id}", file=sys.stderr)
        return g

    # Timestamps
    timestamps = [e["start_ts"] for e in exchanges if e.get("start_ts")]

    # Create session node
    session_uri = create_session_node(
        g, conversation_id, "warp",
        created=timestamps[0] if timestamps else None,
        modified=timestamps[-1] if len(timestamps) > 1 else None,
        source_file=str(db_path),
    )
    g.add((session_uri, PROV.wasAssociatedWith, developer_uri))

    # Track models
    models_seen = set()
    triple_count = 0
    msg_count = 0

    for i, exchange in enumerate(exchanges):
        exchange_id = exchange["exchange_id"]
        timestamp = exchange.get("start_ts")
        model_id = exchange.get("model_id", "")
        working_dir = exchange.get("working_directory", "")

        # Extract user query text
        query_text = extract_query_text(exchange["input"])
        if not query_text.strip():
            continue

        msg_count += 1

        # Create user message node
        msg_uri = create_message_node(
            g, exchange_id, "user", session_uri,
            creator_uri=developer_uri,
            timestamp=timestamp,
            content=query_text,
        )

        # Add working directory as provenance
        if working_dir:
            g.add((msg_uri, DEVKG.hasWorkingDirectory, Literal(working_dir)))

        # Track AI model
        if model_id and model_id not in models_seen:
            models_seen.add(model_id)
            model_node_uri = create_model_node(g, model_id)
            g.add((session_uri, PROV.wasAssociatedWith, model_node_uri))

        # Triple extraction
        if not skip_extraction and model is not None and query_text.strip():
            triples = extract_triples_gemini(model, query_text)
            add_triples_to_graph(g, msg_uri, triples, session_uri)
            triple_count += len(triples)

            if triples:
                print(
                    f"  [{i+1}/{len(exchanges)}] {len(triples)} triples extracted",
                    file=sys.stderr,
                )

            time.sleep(0.5)

    print(
        f"  Processed: {msg_count} exchanges, {len(models_seen)} models, "
        f"{triple_count} knowledge triples",
        file=sys.stderr,
    )

    return g


def main():
    parser = argparse.ArgumentParser(
        description="Convert Warp terminal AI conversations to RDF Turtle"
    )
    parser.add_argument("output", help="Path to output Turtle file")
    parser.add_argument(
        "--conversation", type=int, default=None,
        help="Conversation index (from listing). Omit to list available conversations.",
    )
    parser.add_argument(
        "--db-path", type=str, default=None,
        help=f"Path to warp.sqlite (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--skip-extraction", action="store_true",
        help="Skip Gemini triple extraction (structure only)",
    )
    parser.add_argument("--model", help="Gemini model name override")
    parser.add_argument(
        "--min-exchanges", type=int, default=5,
        help="Skip conversations with fewer than N substantive exchanges (len > 30 chars). Default: 5",
    )
    parser.add_argument(
        "--min-triples", type=int, default=1,
        help="Warn and optionally skip if fewer than N triples extracted. Default: 1",
    )
    args = parser.parse_args()

    db_path = args.db_path or str(DEFAULT_DB_PATH)

    if not Path(db_path).exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    # List mode: no --conversation specified
    if args.conversation is None:
        list_conversations(db_path)
        sys.exit(0)

    # Get conversation by index
    conversations = get_conversations(db_path)
    if args.conversation < 0 or args.conversation >= len(conversations):
        print(
            f"Error: Invalid conversation index {args.conversation}. "
            f"Valid range: 0-{len(conversations) - 1}",
            file=sys.stderr,
        )
        sys.exit(1)

    conv = conversations[args.conversation]
    conversation_id = conv["conversation_id"]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize Vertex AI if extraction is enabled
    gemini_model = None
    if not args.skip_extraction:
        from pipeline.vertex_ai import init_vertex, get_gemini_model
        init_vertex()
        gemini_model = get_gemini_model(model_name=args.model)
        print(f"  Model: {gemini_model._model_name}", file=sys.stderr)

    # Quality filter: check minimum substantive exchanges
    exchanges = get_exchanges(db_path, conversation_id)
    substantive = [e for e in exchanges if len(extract_query_text(e["input"]).strip()) > 30]
    if len(substantive) < args.min_exchanges:
        print(
            f"Skipping conversation {conversation_id}: "
            f"only {len(substantive)} substantive exchanges (minimum: {args.min_exchanges})",
            file=sys.stderr,
        )
        sys.exit(0)

    print(f"Processing conversation: {conversation_id}", file=sys.stderr)
    print(f"  Last modified: {conv['last_modified_at']}", file=sys.stderr)
    print(f"  Substantive exchanges: {len(substantive)}", file=sys.stderr)

    g = build_graph(
        db_path, conversation_id,
        skip_extraction=args.skip_extraction,
        model=gemini_model,
    )

    print(f"  Total RDF triples: {len(g)}", file=sys.stderr)

    # Check minimum knowledge triples extracted
    from rdflib.namespace import RDF as _RDF
    from pipeline.common import DEVKG as _DEVKG
    kt_count = sum(1 for _ in g.subjects(_RDF.type, _DEVKG.KnowledgeTriple))
    if kt_count < args.min_triples and not args.skip_extraction:
        print(
            f"  Warning: only {kt_count} knowledge triples extracted "
            f"(minimum: {args.min_triples}). Skipping output.",
            file=sys.stderr,
        )
        sys.exit(0)

    print(f"  Writing to: {output_path}", file=sys.stderr)

    g.serialize(destination=str(output_path), format="turtle")
    print("  Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
