#!/usr/bin/env python3
"""Batch pipeline for knowledge triple extraction via Vertex AI Batch Prediction API.

Decoupled 3-step pipeline: submit → status → collect.
Uses Vertex AI Batch Prediction API for 50% cost reduction over real-time calls.

Usage:
    # Submit batch job (all unprocessed sessions)
    python -m pipeline.bulk_batch submit

    # Submit with limit
    python -m pipeline.bulk_batch submit --limit 2

    # Check job status
    python -m pipeline.bulk_batch status

    # Wait for completion
    python -m pipeline.bulk_batch status --wait --poll-interval 30

    # Collect results and build RDF
    python -m pipeline.bulk_batch collect

    # Collect with entity linking
    python -m pipeline.bulk_batch collect --link

    # Collect from specific manifest
    python -m pipeline.bulk_batch collect --job output/batch_jobs/20260215_120000.json
"""

import argparse
import json
import os
import sys
import time
import uuid as uuid_mod
from datetime import datetime
from pathlib import Path

from pipeline.bulk_process import (
    find_sessions,
    load_watermarks,
    save_watermarks,
    file_hash,
    session_needs_processing,
    session_output_path,
    OUTPUT_DIR,
    WATERMARK_FILE,
)
from pipeline.batch_extraction import upload_to_gcs, submit_batch_job, poll_job
from pipeline.triple_extraction import (
    build_extraction_prompt,
    _parse_triples_response,
)
from pipeline.jsonl_to_rdf import build_graph
from pipeline.common import add_triples_to_graph, DATA
from pipeline.vertex_ai import init_vertex


BATCH_JOBS_DIR = Path(__file__).resolve().parent.parent / "output" / "batch_jobs"
DEFAULT_BUCKET = os.environ.get("DEVKG_GCS_BUCKET", "devkg-batch-predictions")
DEFAULT_MODEL = "gemini-2.5-flash"


# =============================================================================
# Manifest helpers
# =============================================================================

def save_manifest(manifest: dict) -> Path:
    """Save job manifest to output/batch_jobs/<timestamp>.json."""
    BATCH_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    ts = manifest.get("submitted_at", datetime.now().strftime("%Y%m%d_%H%M%S"))
    # Replace colons/dashes for filename safety
    ts_safe = ts.replace(":", "").replace("-", "").replace("T", "_").split(".")[0]
    path = BATCH_JOBS_DIR / f"{ts_safe}.json"
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest saved: {path}", file=sys.stderr)
    return path


def load_manifest(job_path: str | None = None) -> tuple[dict, Path]:
    """Load a manifest. If job_path is None, load the most recent one."""
    if job_path:
        p = Path(job_path)
        with open(p) as f:
            return json.load(f), p

    # Find most recent manifest
    manifests = sorted(BATCH_JOBS_DIR.glob("*.json"))
    if not manifests:
        print("No batch job manifests found in output/batch_jobs/", file=sys.stderr)
        sys.exit(1)
    p = manifests[-1]
    print(f"Loading latest manifest: {p}", file=sys.stderr)
    with open(p) as f:
        return json.load(f), p


# =============================================================================
# Message extraction from raw JSONL
# =============================================================================

def extract_messages_from_jsonl(jsonl_path: Path) -> list[dict]:
    """Read raw JSONL and extract assistant messages with text >= 30 chars.

    Returns list of {session_id, message_uuid, message_index, source_file, text}.
    Mirrors the text extraction logic in jsonl_to_rdf.py lines 127-141.
    """
    messages = []
    session_id = None

    with open(jsonl_path, "r") as f:
        entries = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            if entry_type not in ("user", "assistant"):
                continue
            entries.append(entry)
            if session_id is None and entry.get("sessionId"):
                session_id = entry["sessionId"]

    if session_id is None:
        session_id = jsonl_path.stem

    for i, entry in enumerate(entries):
        if entry.get("type") != "assistant":
            continue

        content = entry.get("message", {}).get("content", "")
        text_parts = []

        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

        full_text = "\n".join(t for t in text_parts if t.strip())
        if len(full_text.strip()) < 30:
            continue

        msg_uuid = entry.get("uuid", f"unknown-{i}")
        messages.append({
            "session_id": session_id,
            "message_uuid": msg_uuid,
            "message_index": i,
            "source_file": str(jsonl_path),
            "text": full_text,
        })

    return messages


# =============================================================================
# Batch JSONL builder
# =============================================================================

def build_batch_jsonl(all_messages: list[dict], output_path: str, model: str) -> int:
    """Build Vertex AI batch prediction JSONL file.

    Each line: {"request": {"contents": [...], "generation_config": {...}}, "metadata": {...}}
    """
    count = 0
    with open(output_path, "w") as f:
        for msg in all_messages:
            text = msg["text"][:1500]  # Same truncation as real-time pipeline
            prompt = build_extraction_prompt(text)

            # Vertex AI Batch Prediction requires metadata values to be scalar types.
            # Encode our structured metadata as a JSON string.
            metadata_obj = {
                "session_id": msg["session_id"],
                "message_uuid": msg["message_uuid"],
                "message_index": msg["message_index"],
                "source_file": msg["source_file"],
            }

            request = {
                "request": {
                    "contents": [
                        {"role": "user", "parts": [{"text": prompt}]}
                    ],
                    "generation_config": {
                        "response_mime_type": "application/json",
                        "temperature": 0.2,
                        "max_output_tokens": 8192,
                    },
                },
                "metadata": json.dumps(metadata_obj),
            }

            f.write(json.dumps(request) + "\n")
            count += 1

    return count


# =============================================================================
# Batch output download + parsing
# =============================================================================

def download_and_parse_batch_output(
    output_uri: str,
    bucket_name: str,
) -> list[dict]:
    """Download GCS output shards and parse responses.

    Returns list of {session_id, message_uuid, source_file, triples}.
    """
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # output_uri is like gs://bucket/path/to/output/
    # Batch API creates prediction output shards under this prefix
    prefix = output_uri.replace(f"gs://{bucket_name}/", "").rstrip("/")

    results = []
    shard_count = 0

    # List all blobs under the output prefix
    blobs = list(bucket.list_blobs(prefix=prefix))
    jsonl_blobs = [b for b in blobs if b.name.endswith(".jsonl")]

    if not jsonl_blobs:
        print(f"No JSONL output shards found under {output_uri}", file=sys.stderr)
        print(f"  Searched prefix: {prefix}", file=sys.stderr)
        print(f"  Found {len(blobs)} total blobs:", file=sys.stderr)
        for b in blobs[:10]:
            print(f"    {b.name}", file=sys.stderr)
        return []

    for blob in jsonl_blobs:
        shard_count += 1
        content = blob.download_as_text()

        for line in content.strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            raw_meta = record.get("metadata", "{}")
            # metadata may be a JSON string (we serialize it that way) or a dict
            if isinstance(raw_meta, str):
                try:
                    metadata = json.loads(raw_meta)
                except json.JSONDecodeError:
                    metadata = {}
            else:
                metadata = raw_meta
            response = record.get("response", {})

            # Extract text from response
            candidates = response.get("candidates", [])
            raw_text = ""
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    raw_text = parts[0].get("text", "")

            triples = _parse_triples_response(raw_text) if raw_text else None

            results.append({
                "session_id": metadata.get("session_id", "unknown"),
                "message_uuid": metadata.get("message_uuid", "unknown"),
                "source_file": metadata.get("source_file", "unknown"),
                "triples": triples or [],
            })

    print(f"Parsed {len(results)} responses from {shard_count} output shards", file=sys.stderr)
    return results


# =============================================================================
# Subcommands
# =============================================================================

def cmd_submit(args):
    """Submit a batch prediction job."""
    init_vertex()

    # Find sessions to process
    all_sessions = find_sessions()
    if not all_sessions:
        print("No JSONL sessions found.", file=sys.stderr)
        sys.exit(1)

    watermarks = load_watermarks()
    if args.force:
        to_process = all_sessions
    else:
        to_process = [s for s in all_sessions if session_needs_processing(s, watermarks)]

    if args.limit is not None:
        to_process = to_process[:args.limit]

    print(f"Found {len(all_sessions)} total sessions, {len(to_process)} to process", file=sys.stderr)

    if not to_process:
        print("All sessions already processed. Use --force to reprocess.", file=sys.stderr)
        return

    # Extract all assistant messages
    all_messages = []
    session_map = {}  # session_id -> source_file for manifest

    for i, session_path in enumerate(to_process):
        msgs = extract_messages_from_jsonl(session_path)
        if msgs:
            sid = msgs[0]["session_id"]
            session_map[sid] = str(session_path)
            all_messages.extend(msgs)
            print(f"  [{i+1}/{len(to_process)}] {session_path.name}: {len(msgs)} assistant messages", file=sys.stderr)

    if not all_messages:
        print("No extractable messages found.", file=sys.stderr)
        return

    print(f"\nTotal: {len(all_messages)} messages from {len(session_map)} sessions", file=sys.stderr)

    # Build batch JSONL
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_jsonl = f"/tmp/batch_input_{timestamp}.jsonl"
    model = args.model or DEFAULT_MODEL
    count = build_batch_jsonl(all_messages, local_jsonl, model)
    print(f"Prepared {count} requests in {local_jsonl}", file=sys.stderr)

    # Upload to GCS
    bucket = args.bucket or DEFAULT_BUCKET
    blob_name = f"devkg/input_{timestamp}.jsonl"
    input_uri = upload_to_gcs(local_jsonl, bucket, blob_name)
    output_uri = f"gs://{bucket}/devkg/output_{timestamp}/"

    # Submit batch job
    job_name = submit_batch_job(input_uri, output_uri, model_name=model)

    # Save manifest
    manifest = {
        "submitted_at": datetime.now().isoformat(),
        "job_name": job_name,
        "input_uri": input_uri,
        "output_uri": output_uri,
        "bucket": bucket,
        "model": model,
        "session_count": len(session_map),
        "message_count": count,
        "sessions": session_map,
        "status": "SUBMITTED",
    }
    manifest_path = save_manifest(manifest)

    # Cleanup temp file
    try:
        os.unlink(local_jsonl)
    except OSError:
        pass

    print(f"\nBatch job submitted successfully!", file=sys.stderr)
    print(f"  Job: {job_name}", file=sys.stderr)
    print(f"  Messages: {count}", file=sys.stderr)
    print(f"  Sessions: {len(session_map)}", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)
    print(f"\nNext: python -m pipeline.bulk_batch status --wait", file=sys.stderr)


def cmd_status(args):
    """Check batch job status."""
    init_vertex()

    manifest, manifest_path = load_manifest(args.job)
    job_name = manifest["job_name"]

    print(f"Job: {job_name}", file=sys.stderr)
    print(f"Submitted: {manifest['submitted_at']}", file=sys.stderr)
    print(f"Sessions: {manifest['session_count']}, Messages: {manifest['message_count']}", file=sys.stderr)

    if args.wait:
        success = poll_job(job_name, poll_interval=args.poll_interval)
        manifest["status"] = "SUCCEEDED" if success else "FAILED"
    else:
        from vertexai.batch_prediction import BatchPredictionJob
        job = BatchPredictionJob(job_name)
        state = str(job.state)
        manifest["status"] = state
        print(f"Status: {state}", file=sys.stderr)

    # Update manifest
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    if manifest["status"] == "SUCCEEDED":
        print(f"\nJob completed! Next: python -m pipeline.bulk_batch collect", file=sys.stderr)


def cmd_collect(args):
    """Collect batch results and build RDF."""
    manifest, manifest_path = load_manifest(args.job)

    if manifest.get("status") not in ("SUCCEEDED", "JOB_STATE_SUCCEEDED",
                                       "JobState.JOB_STATE_SUCCEEDED"):
        print(f"Job status is '{manifest.get('status')}', not SUCCEEDED.", file=sys.stderr)
        print("Run 'status --wait' first, or use --force-collect.", file=sys.stderr)
        if not args.force_collect:
            sys.exit(1)

    output_uri = manifest["output_uri"]
    bucket = manifest["bucket"]
    sessions = manifest["sessions"]  # session_id -> source_file

    print(f"Collecting results from {output_uri}", file=sys.stderr)

    # Download and parse batch output
    results = download_and_parse_batch_output(output_uri, bucket)
    if not results:
        print("No results found.", file=sys.stderr)
        sys.exit(1)

    # Group results by source_file
    by_source: dict[str, list[dict]] = {}
    for r in results:
        sf = r["source_file"]
        by_source.setdefault(sf, []).append(r)

    print(f"\nResults grouped into {len(by_source)} sessions", file=sys.stderr)

    # Ensure output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    watermarks = load_watermarks()
    output_files = []
    total_triples = 0

    for source_file, session_results in by_source.items():
        source_path = Path(source_file)
        if not source_path.exists():
            print(f"  SKIP (file not found): {source_file}", file=sys.stderr)
            continue

        output_path = session_output_path(source_path)

        # Build RDF structure (no extraction — we already have triples)
        try:
            g = build_graph(source_file, skip_extraction=True)
        except Exception as e:
            print(f"  ERROR building graph for {source_path.name}: {e}", file=sys.stderr)
            continue

        # Inject batch-extracted triples per message
        session_triple_count = 0
        # Find session URI from the graph
        from rdflib.namespace import RDF
        from pipeline.common import DEVKG as _DEVKG
        session_uris = list(g.subjects(RDF.type, _DEVKG.Session))
        session_uri = session_uris[0] if session_uris else None

        if session_uri is None:
            print(f"  WARN: No session URI found in graph for {source_path.name}", file=sys.stderr)
            continue

        for r in session_results:
            if not r["triples"]:
                continue
            msg_uuid = r["message_uuid"]
            msg_uri = DATA[f"message/{msg_uuid}"]
            add_triples_to_graph(g, msg_uri, r["triples"], session_uri)
            session_triple_count += len(r["triples"])

        total_triples += session_triple_count

        g.serialize(destination=str(output_path), format="turtle")
        output_files.append(str(output_path))

        # Update watermark
        watermarks[source_file] = file_hash(source_path)
        save_watermarks(watermarks)

        print(f"  {source_path.name}: {len(g)} RDF triples, {session_triple_count} knowledge triples -> {output_path.name}", file=sys.stderr)

    # Optional entity linking
    if args.link and output_files:
        print(f"\n{'='*60}", file=sys.stderr)
        print("Running entity linking...", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        from pipeline.link_entities import (
            load_aliases, init_cache, extract_entities_from_ttl,
            normalize_label, link_entity_list, _ensure_agentic_init,
        )

        _ensure_agentic_init()
        aliases = load_aliases()
        cache_conn = init_cache()

        labels = extract_entities_from_ttl(output_files)
        if labels:
            normalized = list(dict.fromkeys(
                normalize_label(lbl, aliases) for lbl in labels
            ))
            print(f"Found {len(labels)} entities, {len(normalized)} after normalization", file=sys.stderr)

            links_output = str(OUTPUT_DIR / "wikidata_links.ttl")
            link_entity_list(
                normalized, links_output, aliases, cache_conn,
                verbose=True, agentic=True,
            )

        cache_conn.close()

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print("Batch Collect Summary", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Sessions processed: {len(output_files)}/{len(by_source)}", file=sys.stderr)
    print(f"Knowledge triples:  {total_triples}", file=sys.stderr)
    print(f"Output directory:   {OUTPUT_DIR}", file=sys.stderr)

    # Update manifest
    manifest["status"] = "COLLECTED"
    manifest["collected_at"] = datetime.now().isoformat()
    manifest["output_files"] = output_files
    manifest["total_knowledge_triples"] = total_triples
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Batch pipeline for DevKG triple extraction via Vertex AI Batch Prediction",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # submit
    sub = subparsers.add_parser("submit", help="Submit a batch prediction job")
    sub.add_argument("--limit", type=int, default=None, help="Process at most N sessions")
    sub.add_argument("--force", action="store_true", help="Reprocess all sessions regardless of watermarks")
    sub.add_argument("--model", default=None, help=f"Model name (default: {DEFAULT_MODEL})")
    sub.add_argument("--bucket", default=None, help=f"GCS bucket (default: {DEFAULT_BUCKET})")

    # status
    sub = subparsers.add_parser("status", help="Check batch job status")
    sub.add_argument("--wait", action="store_true", help="Block until job completes")
    sub.add_argument("--poll-interval", type=int, default=60, help="Poll interval in seconds")
    sub.add_argument("--job", default=None, help="Path to specific manifest file")

    # collect
    sub = subparsers.add_parser("collect", help="Collect batch results and build RDF")
    sub.add_argument("--link", action="store_true", help="Run entity linking after collection")
    sub.add_argument("--job", default=None, help="Path to specific manifest file")
    sub.add_argument("--force-collect", action="store_true", help="Collect even if job status is not SUCCEEDED")

    args = parser.parse_args()

    if args.command == "submit":
        cmd_submit(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "collect":
        cmd_collect(args)


if __name__ == "__main__":
    main()
