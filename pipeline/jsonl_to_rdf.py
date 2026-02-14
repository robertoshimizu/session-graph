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
import re
import sys
import time
import hashlib
import argparse
from pathlib import Path

from rdflib import Graph, Namespace, Literal, URIRef, BNode
from rdflib.namespace import RDF, RDFS, XSD, OWL, SKOS, DCTERMS

from pipeline.triple_extraction import extract_triples_gemini

# Namespaces
PROV = Namespace("http://www.w3.org/ns/prov#")
SIOC = Namespace("http://rdfs.org/sioc/ns#")
SCHEMA = Namespace("http://schema.org/")
DEVKG = Namespace("http://devkg.local/ontology#")
DATA = Namespace("http://devkg.local/data/")


def slug(text: str) -> str:
    """Create a URI-safe slug from text."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def entity_uri(name: str) -> URIRef:
    """Create a deterministic URI for an extracted entity."""
    return DATA[f"entity/{slug(name)}"]


def add_triples_to_graph(g: Graph, msg_uri: URIRef, triples: list[dict], session_uri: URIRef) -> None:
    """Add extracted knowledge triples to the RDF graph.

    For each triple, creates:
    - Entity nodes (subject and object) with type and label
    - A direct edge using the devkg predicate (for fast traversal)
    - A reified KnowledgeTriple node (for provenance tracking)
    - mentionsTopic links from the message to both entities
    """
    for t in triples:
        subj_name = t["subject"]
        pred_name = t["predicate"]
        obj_name = t["object"]

        subj_uri = entity_uri(subj_name)
        obj_uri = entity_uri(obj_name)

        # Create Entity nodes if not already present
        if (subj_uri, RDF.type, DEVKG.Entity) not in g:
            g.add((subj_uri, RDF.type, DEVKG.Entity))
            g.add((subj_uri, RDFS.label, Literal(subj_name)))

        if (obj_uri, RDF.type, DEVKG.Entity) not in g:
            g.add((obj_uri, RDF.type, DEVKG.Entity))
            g.add((obj_uri, RDFS.label, Literal(obj_name)))

        # Direct edge: subject --predicate--> object
        pred_uri = DEVKG[pred_name]
        g.add((subj_uri, pred_uri, obj_uri))

        # Reified KnowledgeTriple for provenance
        triple_id = hashlib.md5(f"{subj_name}|{pred_name}|{obj_name}|{msg_uri}".encode()).hexdigest()[:12]
        triple_uri = DATA[f"triple/{triple_id}"]
        g.add((triple_uri, RDF.type, DEVKG.KnowledgeTriple))
        g.add((triple_uri, DEVKG.tripleSubject, subj_uri))
        g.add((triple_uri, DEVKG.tripleObject, obj_uri))
        g.add((triple_uri, DEVKG.triplePredicateLabel, Literal(pred_name)))
        g.add((triple_uri, DEVKG.extractedFrom, msg_uri))
        g.add((triple_uri, DEVKG.extractedInSession, session_uri))

        # Backward-compatible topic links from message to entities
        g.add((msg_uri, DEVKG.mentionsTopic, subj_uri))
        g.add((msg_uri, DEVKG.mentionsTopic, obj_uri))


def build_graph(jsonl_path: str, skip_extraction: bool = False, model=None) -> Graph:
    """Parse a JSONL file and build an RDF graph."""
    g = Graph()

    # Bind prefixes
    g.bind("prov", PROV)
    g.bind("sioc", SIOC)
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)
    g.bind("schema", SCHEMA)
    g.bind("devkg", DEVKG)
    g.bind("data", DATA)

    session_id = None
    session_uri = None
    developer_uri = DATA["developer/roberto"]
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

            # Capture session ID from first entry that has it
            if session_id is None and entry.get("sessionId"):
                session_id = entry["sessionId"]

    if not entries:
        print("No user/assistant entries found.", file=sys.stderr)
        return g

    # Create session node
    session_uri = DATA[f"session/{session_id}"]
    g.add((session_uri, RDF.type, DEVKG.Session))
    g.add((session_uri, DEVKG.hasSourcePlatform, Literal("claude-code")))

    # Add timestamps from first and last entries
    timestamps = [e.get("timestamp") for e in entries if e.get("timestamp")]
    if timestamps:
        g.add((session_uri, DCTERMS.created, Literal(timestamps[0], datatype=XSD.dateTime)))
        if len(timestamps) > 1:
            g.add((session_uri, DCTERMS.modified, Literal(timestamps[-1], datatype=XSD.dateTime)))

    # Create developer node
    g.add((developer_uri, RDF.type, DEVKG.Developer))
    g.add((developer_uri, RDFS.label, Literal("Roberto")))
    g.add((session_uri, PROV.wasAssociatedWith, developer_uri))

    # Track AI models seen
    models_seen = set()

    # UUID to URI mapping for threading
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

        msg_uri = DATA[f"message/{uuid}"]
        uuid_to_uri[uuid] = msg_uri

        # Determine message type
        if entry_type == "user":
            g.add((msg_uri, RDF.type, DEVKG.UserMessage))
            g.add((msg_uri, SIOC.has_creator, developer_uri))
            user_count += 1
        else:
            g.add((msg_uri, RDF.type, DEVKG.AssistantMessage))
            assistant_count += 1

            # Track model
            if model_id and model_id not in models_seen:
                models_seen.add(model_id)
                model_uri = DATA[f"model/{slug(model_id)}"]
                g.add((model_uri, RDF.type, DEVKG.AIModel))
                g.add((model_uri, DEVKG.hasModel, Literal(model_id)))
                g.add((model_uri, RDFS.label, Literal(model_id)))
                g.add((session_uri, PROV.wasAssociatedWith, model_uri))

        # Common properties
        g.add((msg_uri, DEVKG.hasMessageId, Literal(uuid)))
        g.add((msg_uri, DEVKG.usedInSession, session_uri))
        g.add((msg_uri, SIOC.has_container, session_uri))

        if timestamp:
            g.add((msg_uri, DCTERMS.created, Literal(timestamp, datatype=XSD.dateTime)))

        # Thread: parentUuid
        if parent_uuid and parent_uuid in uuid_to_uri:
            g.add((msg_uri, DEVKG.hasParentMessage, uuid_to_uri[parent_uuid]))

        # Extract text content and tool calls
        text_parts = []

        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                block_type = block.get("type")

                if block_type == "text":
                    text_parts.append(block.get("text", ""))

                elif block_type == "tool_use" and entry_type == "assistant":
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

                    # Store tool input as a brief description
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

                        # Link result to tool call
                        g.add((tool_call_uri, DEVKG.hasToolResult, result_uri))

                        # Extract result content (truncated)
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

                elif block_type == "thinking":
                    # Skip thinking blocks
                    pass

        # Store combined text content
        full_text = "\n".join(t for t in text_parts if t.strip())
        if full_text.strip():
            # Truncate very long content for the graph
            stored_text = full_text if len(full_text) <= 2000 else full_text[:2000] + "..."
            g.add((msg_uri, SIOC.content, Literal(stored_text)))

        # Gemini triple extraction
        if not skip_extraction and model is not None and full_text.strip():
            triples = extract_triples_gemini(model, full_text)
            add_triples_to_graph(g, msg_uri, triples, session_uri)
            triple_count += len(triples)

            if triples:
                print(f"  [{i+1}/{len(entries)}] {len(triples)} triples extracted", file=sys.stderr)

            # Rate limit API calls
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
        from pipeline.vertex_ai import init_vertex, get_gemini_model
        init_vertex()
        model = get_gemini_model(model_name=args.model)
        print(f"  Model: {model._model_name}", file=sys.stderr)

    print(f"Processing: {input_path}", file=sys.stderr)
    g = build_graph(str(input_path), skip_extraction=args.skip_extraction, model=model)

    print(f"  Total RDF triples: {len(g)}", file=sys.stderr)
    print(f"  Writing to: {output_path}", file=sys.stderr)

    g.serialize(destination=str(output_path), format="turtle")
    print("  Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
