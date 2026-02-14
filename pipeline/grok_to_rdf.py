#!/usr/bin/env python3
"""Convert Grok (X.ai) conversation exports to RDF Turtle using the devkg ontology.

Usage:
    # List conversations
    python -m pipeline.grok_to_rdf <zip_path> <output.ttl>

    # Process a specific conversation
    python -m pipeline.grok_to_rdf <zip_path> <output.ttl> --conversation 5

    # Skip triple extraction (structure only)
    python -m pipeline.grok_to_rdf <zip_path> <output.ttl> --conversation 5 --skip-extraction

    # Custom model
    python -m pipeline.grok_to_rdf <zip_path> <output.ttl> --conversation 5 --model gemini-2.5-pro
"""

import json
import sys
import time
import argparse
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import RDF, RDFS, DCTERMS, XSD

from pipeline.common import (
    PROV, SIOC, DEVKG, DATA,
    slug, create_graph, create_session_node, create_developer_node,
    create_model_node, create_message_node, add_triples_to_graph,
)
from pipeline.triple_extraction import extract_triples_gemini


# Path inside the zip to the main conversations file
CONVERSATIONS_PATH_PATTERN = "ttl/30d/export_data/"
CONVERSATIONS_FILENAME = "prod-grok-backend.json"


def find_conversations_file(zf: zipfile.ZipFile) -> str | None:
    """Find the prod-grok-backend.json file inside the zip."""
    for name in zf.namelist():
        if name.endswith(CONVERSATIONS_FILENAME):
            return name
    return None


def parse_mongo_timestamp(ts_obj: dict | str | None) -> str | None:
    """Convert MongoDB-style timestamp to ISO 8601 UTC string.

    Handles:
        {"$date": {"$numberLong": "1769019149377"}}  -> milliseconds since epoch
        {"$date": "2026-01-21T18:12:29.327Z"}        -> ISO string
        "2026-01-21T18:12:29.327294Z"                 -> already ISO
    """
    if ts_obj is None:
        return None

    if isinstance(ts_obj, str):
        # Already an ISO string
        return ts_obj

    if isinstance(ts_obj, dict):
        date_val = ts_obj.get("$date")
        if date_val is None:
            return None

        if isinstance(date_val, str):
            return date_val

        if isinstance(date_val, dict):
            number_long = date_val.get("$numberLong")
            if number_long is not None:
                ms = int(number_long)
                dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
                return dt.isoformat()

    return None


def load_grok_data(zip_path: str) -> dict:
    """Load and parse the Grok export JSON from a zip file."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        json_path = find_conversations_file(zf)
        if json_path is None:
            print(f"Error: Could not find {CONVERSATIONS_FILENAME} in zip", file=sys.stderr)
            sys.exit(1)

        print(f"  Found: {json_path}", file=sys.stderr)
        with zf.open(json_path) as f:
            return json.load(f)


def list_conversations(data: dict) -> None:
    """Print a numbered list of conversations with titles and dates."""
    conversations = data.get("conversations", [])
    print(f"\n{len(conversations)} conversations found:\n")
    print(f"{'#':>4}  {'Date':>10}  {'Msgs':>4}  Title")
    print(f"{'─'*4}  {'─'*10}  {'─'*4}  {'─'*50}")

    for i, conv_wrapper in enumerate(conversations):
        conv = conv_wrapper.get("conversation", {})
        title = conv.get("title", "(untitled)")
        created = conv.get("create_time", "")[:10]
        num_responses = len(conv_wrapper.get("responses", []))
        print(f"{i:>4}  {created:>10}  {num_responses:>4}  {title}")

    print(f"\nUse --conversation N to process a specific conversation.")


def build_graph(
    data: dict,
    conversation_idx: int,
    zip_path: str,
    skip_extraction: bool = False,
    model=None,
):
    """Parse a single Grok conversation and build an RDF graph."""
    g = create_graph()

    conversations = data.get("conversations", [])
    if conversation_idx < 0 or conversation_idx >= len(conversations):
        print(f"Error: Conversation index {conversation_idx} out of range "
              f"(0-{len(conversations) - 1})", file=sys.stderr)
        sys.exit(1)

    conv_wrapper = conversations[conversation_idx]
    conv = conv_wrapper.get("conversation", {})
    responses = conv_wrapper.get("responses", [])

    # Conversation metadata
    conv_id = conv.get("id", f"grok-{conversation_idx}")
    title = conv.get("title")
    created = conv.get("create_time")
    modified = conv.get("modify_time")

    print(f"  Conversation: {title or '(untitled)'}", file=sys.stderr)
    print(f"  ID: {conv_id}", file=sys.stderr)
    print(f"  Messages: {len(responses)}", file=sys.stderr)

    # Create nodes
    developer_uri = create_developer_node(g, "Roberto")

    session_uri = create_session_node(
        g, conv_id, "grok",
        created=created,
        modified=modified,
        title=title,
        source_file=str(Path(zip_path).resolve()),
    )
    g.add((session_uri, PROV.wasAssociatedWith, developer_uri))

    # Track models seen
    models_seen = set()
    prev_msg_uri = None
    triple_count = 0
    user_count = 0
    assistant_count = 0

    for i, resp_wrapper in enumerate(responses):
        resp = resp_wrapper.get("response", {})

        msg_id = resp.get("_id", f"grok-msg-{conv_id}-{i}")
        sender = resp.get("sender", "")
        message_text = resp.get("message", "")
        raw_ts = resp.get("create_time")
        timestamp = parse_mongo_timestamp(raw_ts)

        # Role mapping
        if sender == "human":
            role = "user"
            user_count += 1
            creator_uri = developer_uri
        else:
            role = "assistant"
            assistant_count += 1
            creator_uri = None

            # Extract model info
            metadata = resp.get("metadata", {})
            model_details = metadata.get("requestModelDetails", {})
            model_id = model_details.get("modelId")
            if model_id and model_id not in models_seen:
                models_seen.add(model_id)
                model_node_uri = create_model_node(g, model_id)
                g.add((session_uri, PROV.wasAssociatedWith, model_node_uri))

        msg_uri = create_message_node(
            g, msg_id, role, session_uri,
            creator_uri=creator_uri,
            timestamp=timestamp,
            content=message_text if message_text.strip() else None,
            parent_uri=prev_msg_uri,
        )
        prev_msg_uri = msg_uri

        # Triple extraction on non-empty messages
        if not skip_extraction and model is not None and message_text.strip():
            triples = extract_triples_gemini(model, message_text)
            add_triples_to_graph(g, msg_uri, triples, session_uri)
            triple_count += len(triples)

            if triples:
                print(f"  [{i+1}/{len(responses)}] {len(triples)} triples extracted",
                      file=sys.stderr)

            time.sleep(0.5)

    print(f"  Processed: {user_count} user messages, {assistant_count} assistant messages, "
          f"{triple_count} knowledge triples", file=sys.stderr)

    return g


def main():
    parser = argparse.ArgumentParser(description="Convert Grok conversation exports to RDF Turtle")
    parser.add_argument("input", help="Path to Grok export zip file")
    parser.add_argument("output", help="Path to output Turtle file")
    parser.add_argument("--conversation", type=int, default=None,
                        help="Conversation index to process (omit to list all)")
    parser.add_argument("--skip-extraction", action="store_true",
                        help="Skip Gemini triple extraction")
    parser.add_argument("--model", help="Gemini model name override")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading: {input_path}", file=sys.stderr)
    data = load_grok_data(str(input_path))

    # If no conversation specified, list them and exit
    if args.conversation is None:
        list_conversations(data)
        sys.exit(0)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize Vertex AI if doing extraction
    gemini_model = None
    if not args.skip_extraction:
        from pipeline.vertex_ai import init_vertex, get_gemini_model
        init_vertex()
        gemini_model = get_gemini_model(model_name=args.model)
        print(f"  Model: {gemini_model._model_name}", file=sys.stderr)

    g = build_graph(
        data, args.conversation, str(input_path),
        skip_extraction=args.skip_extraction,
        model=gemini_model,
    )

    print(f"  Total RDF triples: {len(g)}", file=sys.stderr)
    print(f"  Writing to: {output_path}", file=sys.stderr)

    g.serialize(destination=str(output_path), format="turtle")
    print("  Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
