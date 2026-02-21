#!/usr/bin/env python3
"""
Real-time knowledge extraction from a single Claude Code assistant response.

Called by hooks/stop_hook.sh after each agent turn. Reads the transcript JSONL
to extract the last assistant message, runs triple extraction via Gemini,
performs entity linking (cache-first), and optionally uploads to Fuseki.

Reuses all existing pipeline modules — no duplicated logic.

Usage:
    python pipeline/realtime_extract.py --session-id <id> --transcript <path>
"""

import argparse
import json
import os
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path (script is called directly by the hook)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def extract_last_assistant_text(transcript_path: str) -> tuple[str | None, str | None]:
    """Extract the last assistant message text and its timestamp from a JSONL transcript.

    Claude Code transcripts are JSONL where each line is a JSON object.
    Assistant messages have type "assistant" with content blocks.

    Returns (text, timestamp) or (None, None) if no assistant message found.
    """
    last_text = None
    last_ts = None

    with open(transcript_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Claude Code JSONL format: {"type": "assistant", "message": {...}}
            if entry.get("type") == "assistant":
                msg = entry.get("message", {})
                content_blocks = msg.get("content", [])
                texts = []
                for block in content_blocks:
                    if isinstance(block, str):
                        texts.append(block)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                if texts:
                    last_text = "\n".join(texts)
                    last_ts = msg.get("timestamp") or entry.get("timestamp")

    return last_text, last_ts


# ---------------------------------------------------------------------------
# Watermark: track which messages we've already processed
# ---------------------------------------------------------------------------

WATERMARK_DIR = Path(__file__).parent.parent / "output" / "realtime"


def _watermark_path(session_id: str) -> Path:
    return WATERMARK_DIR / f".watermark-{session_id}"


def _message_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def is_already_processed(session_id: str, text: str) -> bool:
    """Check if this exact message was already processed."""
    wm = _watermark_path(session_id)
    if not wm.exists():
        return False
    current_hash = _message_hash(text)
    return wm.read_text().strip() == current_hash


def mark_processed(session_id: str, text: str) -> None:
    """Record that this message has been processed."""
    wm = _watermark_path(session_id)
    wm.parent.mkdir(parents=True, exist_ok=True)
    wm.write_text(_message_hash(text))


# ---------------------------------------------------------------------------
# Entity linking (inline, reuses cache + agentic linker)
# ---------------------------------------------------------------------------

def link_entities_inline(
    entity_labels: list[str],
    graph,
    cache_conn,
    aliases: dict,
) -> None:
    """Link extracted entities to Wikidata using cache (+ parallel agentic linker for misses).

    Phase 1: sequential cache lookups (fast, ~50ms each).
    Phase 2: parallel agentic linking for cache misses (ThreadPoolExecutor).
    Adds owl:sameAs triples directly to the graph.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from rdflib.namespace import OWL, RDFS
    from rdflib import Literal
    from pipeline.common import DEVKG, WD, entity_uri
    from pipeline.link_entities import (
        normalize_label, is_linkable_entity, cache_get, cache_put,
        CONFIDENCE_THRESHOLD, _agentic_link_one, _ensure_agentic_init,
    )

    _ensure_agentic_init()

    # Phase 1: cache lookups + collect misses
    cache_misses = []  # (label, uri)
    for raw_label in entity_labels:
        label = normalize_label(raw_label, aliases)

        if not is_linkable_entity(label):
            continue

        uri = entity_uri(label)

        cached = cache_get(cache_conn, label)
        if cached is not None:
            if cached["qid"] and cached.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
                wd_uri = WD[cached["qid"]]
                graph.add((uri, OWL.sameAs, wd_uri))
                log(f"  [cache] {label} -> {cached['qid']}")
            continue

        cache_misses.append((label, uri))

    if not cache_misses:
        return

    # Phase 2: parallel agentic linking for all cache misses
    log(f"  Resolving {len(cache_misses)} cache misses in parallel...")
    with ThreadPoolExecutor(max_workers=len(cache_misses)) as executor:
        future_to_info = {
            executor.submit(
                _agentic_link_one, label, "developer knowledge graph entity"
            ): (label, uri)
            for label, uri in cache_misses
        }

        for future in as_completed(future_to_info):
            label, uri = future_to_info[future]
            try:
                result_label, qid, confidence, description, reasoning, elapsed = future.result()

                if qid and qid.lower() not in ("none", "error", ""):
                    cache_put(cache_conn, label, qid, description, confidence)
                    if confidence >= CONFIDENCE_THRESHOLD:
                        wd_uri = WD[qid]
                        graph.add((uri, OWL.sameAs, wd_uri))
                        log(f"  [linked] {label} -> {qid} (conf={confidence:.2f}, {elapsed:.1f}s)")
                    else:
                        log(f"  [low-conf] {label} -> {qid} (conf={confidence:.2f})")
                else:
                    cache_put(cache_conn, label, None, None, 0.0)
                    log(f"  [no-match] {label}")
            except Exception as e:
                log(f"  [error] {label}: {e}")
                cache_put(cache_conn, label, None, None, 0.0)


# ---------------------------------------------------------------------------
# Fuseki upload
# ---------------------------------------------------------------------------

def try_upload_fuseki(ttl_path: str) -> bool:
    """Upload .ttl to Fuseki if it's running. Returns True on success."""
    try:
        import requests
        resp = requests.get("http://localhost:3030/$/ping", timeout=2)
        if resp.status_code != 200:
            return False
    except Exception:
        return False

    from pipeline.load_fuseki import upload_turtle, ensure_dataset
    if not ensure_dataset("http://localhost:3030", "devkg"):
        return False
    return upload_turtle("http://localhost:3030", "devkg", ttl_path)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Real-time KG extraction from a single response")
    parser.add_argument("--session-id", required=True, help="Claude Code session ID")
    parser.add_argument("--transcript", required=True, help="Path to transcript JSONL file")
    args = parser.parse_args()

    session_id = args.session_id
    transcript_path = args.transcript

    log(f"START session={session_id}")

    # Step 1: Extract last assistant message from transcript
    text, timestamp = extract_last_assistant_text(transcript_path)

    if not text:
        log("No assistant message found in transcript")
        return

    if len(text) < 100:
        log(f"Message too short ({len(text)} chars), skipping")
        return

    # Step 2: Dedup — skip if we already processed this exact message
    if is_already_processed(session_id, text):
        log("Message already processed (same hash), skipping")
        return

    # Step 3: Init Vertex AI + extract triples
    from pipeline.vertex_ai import init_vertex, get_gemini_model
    from pipeline.triple_extraction import extract_triples_gemini

    init_vertex()
    model = get_gemini_model()

    triples = extract_triples_gemini(model, text)
    log(f"Extracted {len(triples)} triples from {len(text)} chars")

    if not triples:
        mark_processed(session_id, text)
        log("No triples extracted, done")
        return

    # Step 4: Build RDF graph
    from pipeline.common import (
        create_graph, create_session_node, create_message_node,
        add_triples_to_graph, slug,
    )

    g = create_graph()

    # Create session node
    session_uri = create_session_node(
        g, session_id, "claude-code",
        title=f"Real-time extraction",
        source_file=transcript_path,
    )

    # Create message node with deterministic ID
    msg_hash = hashlib.md5(text[:500].encode()).hexdigest()[:12]
    msg_id = f"rt-{slug(session_id)[:20]}-{msg_hash}"
    msg_uri = create_message_node(
        g, msg_id, "assistant", session_uri,
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        content=text,
    )

    # Add knowledge triples
    add_triples_to_graph(g, msg_uri, triples, session_uri)

    # Step 5: Entity linking
    entity_labels = set()
    for t in triples:
        entity_labels.add(t["subject"])
        entity_labels.add(t["object"])

    from pipeline.link_entities import init_cache, load_aliases
    cache_conn = init_cache()
    aliases = load_aliases()

    log(f"Linking {len(entity_labels)} entities...")
    link_entities_inline(list(entity_labels), g, cache_conn, aliases)
    cache_conn.close()

    # Step 6: Serialize to .ttl (append-safe: one file per session)
    output_dir = WATERMARK_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    ttl_path = output_dir / f"{slug(session_id)}.ttl"

    # Append mode: if file exists, merge graphs
    if ttl_path.exists():
        from rdflib import Graph as RdfGraph
        existing = RdfGraph()
        existing.parse(str(ttl_path), format="turtle")
        for triple in g:
            existing.add(triple)
        g = existing
        from pipeline.common import bind_namespaces
        bind_namespaces(g)

    ttl_path.write_text(g.serialize(format="turtle"))
    log(f"Written {len(g)} triples to {ttl_path}")

    # Step 7: Upload to Fuseki if running
    if try_upload_fuseki(str(ttl_path)):
        log("Uploaded to Fuseki")
    else:
        log("Fuseki not available, skipped upload")

    # Step 8: Mark as processed
    mark_processed(session_id, text)

    # Summary
    for t in triples:
        log(f"  ({t['subject']}) --{t['predicate']}--> ({t['object']})")

    log(f"DONE: {len(triples)} triples, {len(entity_labels)} entities")


if __name__ == "__main__":
    main()
