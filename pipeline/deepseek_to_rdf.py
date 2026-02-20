#!/usr/bin/env python3
"""Convert DeepSeek conversation exports (ZIP) to RDF Turtle using the devkg ontology.

Usage:
    # List available conversations
    python -m pipeline.deepseek_to_rdf <zip_path> <output.ttl>

    # Process a specific conversation
    python -m pipeline.deepseek_to_rdf <zip_path> <output.ttl> --conversation 8

    # Skip triple extraction (structure only)
    python -m pipeline.deepseek_to_rdf <zip_path> <output.ttl> --conversation 8 --skip-extraction

    # Custom model
    python -m pipeline.deepseek_to_rdf <zip_path> <output.ttl> --conversation 8 --model gemini-2.5-pro
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


# =============================================================================
# Data Loading
# =============================================================================

def load_zip(zip_path: str) -> tuple[dict | None, list[dict]]:
    """Load user.json and conversations.json from a DeepSeek export ZIP.

    Returns (user_info, conversations).
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

        user_info = None
        for name in names:
            if name.endswith("user.json"):
                with zf.open(name) as f:
                    user_info = json.load(f)
                break

        conversations = []
        for name in names:
            if name.endswith("conversations.json"):
                with zf.open(name) as f:
                    conversations = json.load(f)
                break

    return user_info, conversations


# =============================================================================
# Timestamp Normalization
# =============================================================================

def normalize_timestamp(ts: str | None) -> str | None:
    """Normalize a DeepSeek timestamp to ISO 8601 UTC.

    DeepSeek uses format like '2025-04-20T10:34:03.158000+08:00'.
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return ts


# =============================================================================
# Tree Walking
# =============================================================================

def walk_conversation_tree(mapping: dict) -> list[dict]:
    """Walk the conversation tree depth-first from root, returning ordered messages.

    Each returned dict has: id, parent_id, role, content, model, timestamp.
    """
    messages = []

    def walk(node_id: str, parent_id: str | None):
        node = mapping.get(node_id)
        if node is None:
            return

        msg_data = node.get("message")
        if msg_data and msg_data.get("fragments"):
            fragments = msg_data["fragments"]
            model = msg_data.get("model")
            timestamp = msg_data.get("inserted_at")

            # Group fragments by role
            user_parts = []
            assistant_parts = []

            for frag in fragments:
                frag_type = frag.get("type", "")
                frag_content = frag.get("content", "")
                if not frag_content:
                    continue

                if frag_type == "REQUEST":
                    user_parts.append(frag_content)
                elif frag_type in ("RESPONSE", "THINK"):
                    assistant_parts.append(frag_content)

            # Emit user message if present
            if user_parts:
                messages.append({
                    "id": f"{node_id}-user",
                    "parent_id": parent_id,
                    "role": "user",
                    "content": "\n".join(user_parts),
                    "model": model,
                    "timestamp": timestamp,
                })
                # If both user and assistant in same node, chain them
                last_parent = f"{node_id}-user"
            else:
                last_parent = parent_id

            if assistant_parts:
                messages.append({
                    "id": f"{node_id}-assistant",
                    "parent_id": last_parent,
                    "role": "assistant",
                    "content": "\n".join(assistant_parts),
                    "model": model,
                    "timestamp": timestamp,
                })

        # Recurse into children
        children = node.get("children", [])
        for child_id in children:
            walk(child_id, node_id)

    # Start from root
    if "root" in mapping:
        walk("root", None)
    else:
        # Fallback: find a node with no parent
        for nid, node in mapping.items():
            if node.get("parent") is None:
                walk(nid, None)
                break

    return messages


# =============================================================================
# Graph Building
# =============================================================================

def build_graph(
    conversation: dict,
    user_info: dict | None,
    zip_path: str,
    skip_extraction: bool = False,
    model=None,
    developer: str = "developer",
):
    """Build an RDF graph from a single DeepSeek conversation."""
    g = create_graph()

    # Developer node: prefer user_info from export, then CLI arg
    dev_name = developer
    if user_info and user_info.get("name"):
        dev_name = user_info["name"]
    developer_uri = create_developer_node(g, dev_name)

    # Session node
    conv_id = conversation.get("id", "unknown")
    title = conversation.get("title")
    created = normalize_timestamp(conversation.get("inserted_at"))
    modified = normalize_timestamp(conversation.get("updated_at"))

    session_uri = create_session_node(
        g, conv_id, "deepseek",
        created=created,
        modified=modified,
        title=title,
        source_file=str(Path(zip_path).resolve()),
    )
    g.add((session_uri, PROV.wasAssociatedWith, developer_uri))

    # Walk conversation tree
    mapping = conversation.get("mapping", {})
    messages = walk_conversation_tree(mapping)

    if not messages:
        print("  No messages found in conversation.", file=sys.stderr)
        return g

    # Track models and build URI lookup for parent references
    models_seen = set()
    id_to_uri = {}

    user_count = 0
    assistant_count = 0
    triple_count = 0

    for i, msg in enumerate(messages):
        msg_id = msg["id"]
        role = msg["role"]
        content = msg["content"]
        timestamp = normalize_timestamp(msg["timestamp"])
        msg_model = msg.get("model")

        # Resolve parent URI
        parent_uri = None
        if msg["parent_id"]:
            # Try direct match, then with role suffixes
            parent_uri = id_to_uri.get(msg["parent_id"])
            if parent_uri is None:
                parent_uri = id_to_uri.get(f"{msg['parent_id']}-assistant")
            if parent_uri is None:
                parent_uri = id_to_uri.get(f"{msg['parent_id']}-user")

        # Create message node
        # Use conversation id as prefix for globally unique message IDs
        global_msg_id = f"ds-{slug(conv_id[:12])}-{msg_id}"
        msg_uri = create_message_node(
            g, global_msg_id, role, session_uri,
            creator_uri=developer_uri if role == "user" else None,
            timestamp=timestamp,
            content=content if content.strip() else None,
            parent_uri=parent_uri,
        )
        id_to_uri[msg_id] = msg_uri

        if role == "user":
            user_count += 1
        else:
            assistant_count += 1
            if msg_model and msg_model not in models_seen:
                models_seen.add(msg_model)
                model_uri = create_model_node(g, msg_model)
                g.add((session_uri, PROV.wasAssociatedWith, model_uri))

        # Triple extraction
        if not skip_extraction and model is not None and content.strip():
            triples = extract_triples_gemini(model, content)
            add_triples_to_graph(g, msg_uri, triples, session_uri)
            triple_count += len(triples)

            if triples:
                print(f"  [{i+1}/{len(messages)}] {len(triples)} triples extracted", file=sys.stderr)

            time.sleep(0.5)

    print(
        f"  Processed: {user_count} user messages, {assistant_count} assistant messages, "
        f"{triple_count} knowledge triples",
        file=sys.stderr,
    )

    return g


# =============================================================================
# CLI
# =============================================================================

def list_conversations(conversations: list[dict]) -> None:
    """Print a table of available conversations."""
    print(f"\n{'Idx':>4}  {'Messages':>5}  {'Date':>10}  Title", file=sys.stderr)
    print(f"{'---':>4}  {'---':>5}  {'---':>10}  -----", file=sys.stderr)

    for idx, conv in enumerate(conversations):
        title = conv.get("title", "(untitled)")
        created = conv.get("inserted_at", "")[:10]

        # Count messages by walking tree
        mapping = conv.get("mapping", {})
        msg_count = sum(
            1 for node in mapping.values()
            if node.get("message") and node["message"].get("fragments")
        )

        print(f"{idx:>4}  {msg_count:>5}  {created:>10}  {title}", file=sys.stderr)

    print(f"\nTotal: {len(conversations)} conversations", file=sys.stderr)
    print("Use --conversation N to process a specific conversation.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Convert DeepSeek export ZIP to RDF Turtle")
    parser.add_argument("input", help="Path to DeepSeek ZIP export")
    parser.add_argument("output", help="Path to output Turtle file")
    parser.add_argument("--conversation", type=int, default=None,
                        help="Conversation index to process (omit to list all)")
    parser.add_argument("--skip-extraction", action="store_true",
                        help="Skip LLM triple extraction")
    parser.add_argument("--provider", help="LLM provider: gemini, openai, anthropic, ollama (auto-detect if omitted)")
    parser.add_argument("--model", help="Model name override")
    parser.add_argument("--developer", default="developer", help="Developer name for provenance (default: developer)")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load ZIP
    print(f"Loading: {input_path}", file=sys.stderr)
    user_info, conversations = load_zip(str(input_path))

    if not conversations:
        print("Error: No conversations found in ZIP.", file=sys.stderr)
        sys.exit(1)

    print(f"  Found {len(conversations)} conversations", file=sys.stderr)

    # List mode
    if args.conversation is None:
        list_conversations(conversations)
        sys.exit(0)

    # Validate conversation index
    if args.conversation < 0 or args.conversation >= len(conversations):
        print(
            f"Error: Conversation index {args.conversation} out of range "
            f"(0-{len(conversations) - 1}).",
            file=sys.stderr,
        )
        sys.exit(1)

    conv = conversations[args.conversation]
    print(f"  Selected: [{args.conversation}] {conv.get('title', '(untitled)')}", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize LLM provider
    gemini_model = None
    if not args.skip_extraction:
        from pipeline.llm_providers import get_provider
        gemini_model = get_provider(provider_name=args.provider, model_name=args.model)

    # Build graph
    g = build_graph(
        conv, user_info, str(input_path),
        skip_extraction=args.skip_extraction,
        model=gemini_model,
        developer=args.developer,
    )

    print(f"  Total RDF triples: {len(g)}", file=sys.stderr)
    print(f"  Writing to: {output_path}", file=sys.stderr)

    g.serialize(destination=str(output_path), format="turtle")
    print("  Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
