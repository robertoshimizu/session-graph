#!/usr/bin/env python3
"""Convert DeepSeek Harness (DSH) session exports (JSONL or ZIP) to RDF Turtle.

DeepSeek Harness writes an event-log JSONL for each session. Each line is one
event, e.g.:

    {"type": "session", "id": "session-...", "createdAt": 1786824423814, ...}
    {"type": "user/message", "seq": 8, "time": ..., "data": {"content": [{"type": "text", "text": "..."}], "id": "..."}}
    {"type": "assistant/message", "seq": 317, "time": ..., "data": {"message": {"role": "assistant", "content": [{"type": "reasoning"|"text"|"tool-call", ...}], "source": {"model": "deepseek-v4-flash"}, "id": "..."}}}

This parser mirrors pipeline/deepseek_to_rdf.py:
  - session metadata -> devkg:Session (platform "deepseek-harness")
  - user/message + assistant/message events -> devkg:UserMessage / devkg:AssistantMessage
  - assistant text blocks -> LLM triple extraction (with SQLite cache)
  - entities + reified devkg:KnowledgeTriple nodes with provenance

Usage:
    # Convert a JSONL session export
    python -m pipeline.dsh_to_rdf <input.jsonl> <output.ttl>

    # Convert a ZIP export (contains session.jsonl)
    python -m pipeline.dsh_to_rdf <input.zip> <output.ttl>

    # Skip triple extraction (structure only)
    python -m pipeline.dsh_to_rdf <input.jsonl> <output.ttl> --skip-extraction

    # Custom model / provider
    python -m pipeline.dsh_to_rdf <input.jsonl> <output.ttl> --model deepseek-chat
"""

import argparse
import json
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import RDF, DCTERMS, XSD

from pipeline.common import (
    PROV, DEVKG,
    slug, create_graph, create_session_node, create_developer_node,
    create_model_node, create_message_node, add_triples_to_graph,
)
from pipeline.triple_extraction import (
    extract_triples_gemini, get_cached_triples, cache_triples,
    get_truncation_count,
)

PLATFORM = "deepseek-harness"


# =============================================================================
# Data Loading
# =============================================================================

def load_jsonl_events(path: str) -> list[dict]:
    """Read a DSH event-log JSONL file into a list of event dicts."""
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  [warn] Skipping malformed JSON at line {line_num}", file=sys.stderr)
    return events


def load_events(input_path: str) -> list[dict]:
    """Load events from a .jsonl file or a .zip containing session.jsonl."""
    p = Path(input_path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p, "r") as zf:
            member = None
            for name in zf.namelist():
                if name.endswith(".jsonl"):
                    member = name
                    break
            if member is None:
                print("Error: No .jsonl found in ZIP.", file=sys.stderr)
                sys.exit(1)
            with zf.open(member) as f:
                events = []
                for line_num, line in enumerate(f, 1):
                    line = line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        print(f"  [warn] Skipping malformed JSON at line {line_num}", file=sys.stderr)
                return events
    return load_jsonl_events(input_path)


# =============================================================================
# Timestamp Normalization (epoch milliseconds -> ISO 8601 UTC)
# =============================================================================

def normalize_timestamp(ms) -> str | None:
    """Normalize a DSH epoch-milliseconds timestamp to ISO 8601 UTC."""
    if ms is None:
        return None
    try:
        ms = int(ms)
    except (ValueError, TypeError):
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# =============================================================================
# Message Extraction
# =============================================================================

def extract_text_blocks(content_blocks: list) -> str:
    """Join text blocks from a DSH content array.

    Only blocks of type "text" contribute content; "reasoning" and "tool-call"
    blocks are not knowledge-graph material (mirrors jsonl_to_rdf.py).
    """
    parts = []
    for block in content_blocks or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "")
            if text.strip():
                parts.append(text)
    return "\n".join(parts)


def extract_messages(events: list[dict]) -> tuple[dict | None, list[dict], str | None]:
    """Extract session metadata, ordered messages, and title from events.

    Returns (session_event, messages, title) where each message dict has:
    id, parent_id, role, content, model, timestamp.
    """
    session_event = None
    title = None
    messages = []

    for ev in events:
        etype = ev.get("type")
        if etype == "session" and session_event is None:
            session_event = ev
        elif etype == "session/title":
            data = ev.get("data") or {}
            if data.get("title"):
                title = data["title"]
        elif etype == "user/message":
            data = ev.get("data") or {}
            msg_id = data.get("id")
            if not msg_id:
                msg_id = f"user-{ev.get('seq', 0)}"
            messages.append({
                "id": msg_id,
                "role": "user",
                "content": extract_text_blocks(data.get("content")),
                "model": None,
                "timestamp": normalize_timestamp(ev.get("time")),
            })
        elif etype == "assistant/message":
            data = ev.get("data") or {}
            message = data.get("message") or {}
            msg_id = message.get("id")
            if not msg_id:
                msg_id = f"assistant-{ev.get('seq', 0)}"
            source = message.get("source") or {}
            messages.append({
                "id": msg_id,
                "role": "assistant",
                "content": extract_text_blocks(message.get("content")),
                "model": source.get("model"),
                "timestamp": normalize_timestamp(ev.get("time")),
            })

    # Order by event sequence and chain parent links linearly
    messages.sort(key=lambda m: m["timestamp"] or "")
    for i in range(1, len(messages)):
        messages[i]["parent_id"] = messages[i - 1]["id"]

    return session_event, messages, title


# =============================================================================
# Graph Building
# =============================================================================

def build_graph(
    input_path: str,
    skip_extraction: bool = False,
    model=None,
    developer: str = "developer",
):
    """Build an RDF graph from a DSH session export (JSONL or ZIP)."""
    g = create_graph()

    events = load_events(input_path)
    session_event, messages, title = extract_messages(events)

    # Session node
    session_id = (session_event or {}).get("id", "unknown")
    created = normalize_timestamp((session_event or {}).get("createdAt"))
    modified = messages[-1]["timestamp"] if messages else None

    session_uri = create_session_node(
        g, session_id, PLATFORM,
        created=created,
        modified=modified,
        title=title,
        source_file=str(Path(input_path).resolve()),
    )

    # Developer node
    developer_uri = create_developer_node(g, developer)
    g.add((session_uri, PROV.wasAssociatedWith, developer_uri))

    if not messages:
        print("  No user/assistant messages found.", file=sys.stderr)
        return g

    # Track models seen and build URI lookup for parent references
    models_seen = set()
    id_to_uri = {}

    user_count = 0
    assistant_count = 0
    triple_count = 0
    cache_hits = 0

    for i, msg in enumerate(messages):
        msg_id = msg["id"]
        role = msg["role"]
        content = msg["content"]
        msg_model = msg.get("model")
        timestamp = msg.get("timestamp")

        # Resolve parent URI (linear chain)
        parent_uri = id_to_uri.get(msg.get("parent_id")) if msg.get("parent_id") else None

        # Create message node (prefix with dsh- for globally unique message IDs)
        global_msg_id = f"dsh-{msg_id}"
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

        # Triple extraction (assistant messages only — that's where the knowledge is)
        if not skip_extraction and model is not None and content.strip() and role == "assistant":
            cached = get_cached_triples(global_msg_id)
            if cached is not None:
                triples = cached
                cache_hits += 1
            else:
                triples = extract_triples_gemini(model, content)
                cache_triples(global_msg_id, triples, content)
                time.sleep(0.5)

            add_triples_to_graph(g, msg_uri, triples, session_uri)
            triple_count += len(triples)

            if triples:
                label = "cached" if cached is not None else "extracted"
                print(f"  [{i + 1}/{len(messages)}] {len(triples)} triples {label}",
                      file=sys.stderr)

    cache_msg = f", {cache_hits} cache hits" if cache_hits else ""
    print(
        f"  Processed: {user_count} user messages, {assistant_count} assistant messages, "
        f"{triple_count} knowledge triples{cache_msg}",
        file=sys.stderr,
    )

    return g


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert DeepSeek Harness session export (JSONL or ZIP) to RDF Turtle"
    )
    parser.add_argument("input", help="Path to DSH session export (.jsonl or .zip)")
    parser.add_argument("output", help="Path to output Turtle file")
    parser.add_argument("--skip-extraction", action="store_true",
                        help="Skip LLM triple extraction")
    parser.add_argument("--provider", help="LLM provider: gemini, openai, anthropic, fireworks, ollama (auto-detect if omitted)")
    parser.add_argument("--model", help="Model name override")
    parser.add_argument("--developer", default="developer",
                        help="Developer name for provenance (default: developer)")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading: {input_path}", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize LLM provider
    llm_model = None
    if not args.skip_extraction:
        from pipeline.llm_providers import get_extraction_model
        llm_model = get_extraction_model(provider_name=args.provider, model_name=args.model)

    # Build graph
    g = build_graph(
        str(input_path),
        skip_extraction=args.skip_extraction,
        model=llm_model,
        developer=args.developer,
    )

    print(f"  Total RDF triples: {len(g)}", file=sys.stderr)

    # Report truncation events if any occurred
    tc = get_truncation_count()
    if tc > 0:
        print(f"  Truncated responses: {tc} (salvaged where possible)", file=sys.stderr)

    print(f"  Writing to: {output_path}", file=sys.stderr)

    g.serialize(destination=str(output_path), format="turtle")
    print("  Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
