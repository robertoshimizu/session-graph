#!/usr/bin/env python3
"""Convert Claude Code JSONL session logs to RDF Turtle using the devkg ontology.

Usage:
    # Real-time extraction (default)
    python -m pipeline.jsonl_to_rdf <input.jsonl> <output.ttl>

    # Skip extraction (structure only)
    python -m pipeline.jsonl_to_rdf <input.jsonl> <output.ttl> --skip-extraction

    # Custom model
    python -m pipeline.jsonl_to_rdf <input.jsonl> <output.ttl> --model gemini-2.5-pro
"""

import json
import sys
import time
import argparse
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import RDF, RDFS, DCTERMS, XSD

from pipeline.common import (
    PROV, SIOC, DEVKG, DATA,
    slug, create_graph, create_session_node, create_developer_node,
    create_model_node, create_message_node, create_project_node,
    add_triples_to_graph,
)
from pipeline.triple_extraction import extract_triples_gemini


def detect_project(jsonl_path: str) -> str | None:
    """Detect project slug from Claude Code session path.

    Claude Code sessions live at:
      ~/.claude/projects/{project-slug}/{sessionId}.jsonl
    """
    p = Path(jsonl_path).resolve()
    parts = p.parts
    try:
        idx = parts.index("projects")
        if idx + 1 < len(parts) - 1:  # must have slug + filename after "projects"
            return parts[idx + 1]
    except ValueError:
        pass
    return None


def build_graph(jsonl_path: str, skip_extraction: bool = False, model=None):
    """Parse a JSONL file and build an RDF graph."""
    g = create_graph()

    session_id = None
    developer_uri = create_developer_node(g, "Roberto")
    entries = []

    # First pass: read all entries
    with open(jsonl_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                print(f"  [warn] Skipping malformed JSON at line {line_num}", file=sys.stderr)
                continue

            entry_type = entry.get("type")
            if entry_type not in ("user", "assistant"):
                continue

            entries.append(entry)

            if session_id is None and entry.get("sessionId"):
                session_id = entry["sessionId"]

    if not entries:
        print("No user/assistant entries found.", file=sys.stderr)
        return g

    # Timestamps
    timestamps = [e.get("timestamp") for e in entries if e.get("timestamp")]

    # Create session node
    session_uri = create_session_node(
        g, session_id, "claude-code",
        created=timestamps[0] if timestamps else None,
        modified=timestamps[-1] if len(timestamps) > 1 else None,
        source_file=str(Path(jsonl_path).resolve()),
    )
    g.add((session_uri, PROV.wasAssociatedWith, developer_uri))

    # Project detection
    project_slug = detect_project(jsonl_path)
    if project_slug:
        proj_uri = create_project_node(g, project_slug)
        g.add((session_uri, DEVKG.belongsToProject, proj_uri))

    # Track AI models seen
    models_seen = set()
    uuid_to_uri = {}

    # Process entries
    user_count = 0
    assistant_count = 0
    tool_call_count = 0
    triple_count = 0

    for i, entry in enumerate(entries):
        entry_type = entry["type"]
        uuid = entry.get("uuid", f"unknown-{i}")
        parent_uuid = entry.get("parentUuid")
        timestamp = entry.get("timestamp")
        message = entry.get("message", {})
        content = message.get("content", "")
        model_id = message.get("model")

        # Determine parent URI
        parent_uri = uuid_to_uri.get(parent_uuid) if parent_uuid else None

        # Extract text content and tool calls
        text_parts = []
        tool_calls_data = []

        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                block_type = block.get("type")
                if block_type == "text":
                    text_parts.append(block.get("text", ""))
                elif block_type == "tool_use" and entry_type == "assistant":
                    tool_calls_data.append(block)
                elif block_type == "tool_result":
                    tool_calls_data.append(block)
                elif block_type == "thinking":
                    pass

        full_text = "\n".join(t for t in text_parts if t.strip())

        # Create message node
        msg_uri = create_message_node(
            g, uuid, entry_type, session_uri,
            creator_uri=developer_uri if entry_type == "user" else None,
            timestamp=timestamp,
            content=full_text if full_text.strip() else None,
            parent_uri=parent_uri,
        )
        uuid_to_uri[uuid] = msg_uri

        if entry_type == "user":
            user_count += 1
        else:
            assistant_count += 1
            # Track model
            if model_id and model_id not in models_seen:
                models_seen.add(model_id)
                model_uri = create_model_node(g, model_id)
                g.add((session_uri, PROV.wasAssociatedWith, model_uri))

        # Process tool calls and results
        for block in tool_calls_data:
            block_type = block.get("type")

            if block_type == "tool_use":
                tool_call_count += 1
                tool_id = block.get("id", f"tool-{tool_call_count}")
                tool_name = block.get("name", "unknown")
                tool_uri = DATA[f"toolcall/{tool_id}"]

                g.add((tool_uri, RDF.type, DEVKG.ToolCall))
                g.add((tool_uri, DEVKG.hasToolName, Literal(tool_name)))
                g.add((tool_uri, DEVKG.usedInSession, session_uri))
                g.add((msg_uri, DEVKG.invokedTool, tool_uri))

                if timestamp:
                    g.add((tool_uri, DCTERMS.created, Literal(timestamp, datatype=XSD.dateTime)))

                tool_input = block.get("input", {})
                if isinstance(tool_input, dict):
                    input_summary = json.dumps(tool_input, ensure_ascii=False)
                    if len(input_summary) > 500:
                        input_summary = input_summary[:500] + "..."
                    g.add((tool_uri, DCTERMS.description, Literal(input_summary)))

            elif block_type == "tool_result":
                tool_use_id = block.get("tool_use_id")
                if tool_use_id:
                    result_uri = DATA[f"toolresult/{tool_use_id}"]
                    tool_call_uri = DATA[f"toolcall/{tool_use_id}"]
                    g.add((result_uri, RDF.type, DEVKG.ToolResult))
                    g.add((tool_call_uri, DEVKG.hasToolResult, result_uri))

                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        result_text = " ".join(
                            b.get("text", "") for b in result_content if b.get("type") == "text"
                        )
                    else:
                        result_text = str(result_content)

                    if result_text:
                        if len(result_text) > 500:
                            result_text = result_text[:500] + "..."
                        g.add((result_uri, SIOC.content, Literal(result_text)))

        # Gemini triple extraction (assistant messages only — that's where the knowledge is)
        if not skip_extraction and model is not None and full_text.strip() and entry_type == "assistant":
            triples = extract_triples_gemini(model, full_text)
            add_triples_to_graph(g, msg_uri, triples, session_uri)
            triple_count += len(triples)

            if triples:
                print(f"  [{i+1}/{len(entries)}] {len(triples)} triples extracted", file=sys.stderr)

            time.sleep(0.5)

    print(f"  Processed: {user_count} user messages, {assistant_count} assistant messages, "
          f"{tool_call_count} tool calls, {triple_count} knowledge triples", file=sys.stderr)

    return g


def main():
    parser = argparse.ArgumentParser(description="Convert Claude Code JSONL to RDF Turtle")
    parser.add_argument("input", help="Path to JSONL file")
    parser.add_argument("output", help="Path to output Turtle file")
    parser.add_argument("--skip-extraction", action="store_true", help="Skip Gemini triple extraction")
    parser.add_argument("--model", help="Gemini model name override")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize Vertex AI and get model
    model = None
    if not args.skip_extraction:
        from pipeline.vertex_ai import init_vertex, get_gemini_model, get_claude_model
        init_vertex()
        if args.model and args.model.startswith("claude"):
            model = get_claude_model(model_name=args.model)
        else:
            model = get_gemini_model(model_name=args.model)
            print(f"  Model: {model._model_name}", file=sys.stderr)

    print(f"Processing: {input_path}", file=sys.stderr)
    g = build_graph(str(input_path), skip_extraction=args.skip_extraction, model=model)

    print(f"  Total RDF triples: {len(g)}", file=sys.stderr)

    # Report truncation events if any occurred
    from pipeline.triple_extraction import get_truncation_count
    tc = get_truncation_count()
    if tc > 0:
        print(f"  Truncated responses: {tc} (salvaged where possible)", file=sys.stderr)

    print(f"  Writing to: {output_path}", file=sys.stderr)

    g.serialize(destination=str(output_path), format="turtle")
    print("  Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
