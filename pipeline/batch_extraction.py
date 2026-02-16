#!/usr/bin/env python3
"""Gemini Batch Prediction for knowledge triple extraction.

Tests batch mode on a sample of messages collected from parser outputs.
Uses Vertex AI Batch Prediction API with Gemini 2.5 Flash.

Usage:
    # Collect messages from .ttl files and run batch extraction
    python -m pipeline.batch_extraction --input output/*_sample.ttl --bucket devkg-batch-predictions

    # Just prepare the input JSONL (no submission)
    python -m pipeline.batch_extraction --input output/*_sample.ttl --prepare-only

Prerequisites:
    pip install google-cloud-storage google-cloud-aiplatform
    gcloud storage buckets create gs://devkg-batch-predictions --location=us-central1
"""

import json
import sys
import time
import argparse
import uuid
from pathlib import Path
from datetime import datetime

from rdflib import Graph
from rdflib.namespace import RDF, RDFS

from pipeline.common import DEVKG, SIOC
from pipeline.triple_extraction import build_extraction_prompt, normalize_triple, _parse_triples_response


def collect_messages_from_ttl(ttl_paths: list[str]) -> list[dict]:
    """Extract message texts from .ttl files for batch processing.

    Returns list of {id, text, platform, session_id} dicts.
    """
    messages = []
    for path in ttl_paths:
        g = Graph()
        g.parse(path, format="turtle")

        # Find all messages with content
        for msg_uri in g.subjects(RDF.type, DEVKG.UserMessage):
            for content in g.objects(msg_uri, SIOC.content):
                text = str(content)
                if len(text.strip()) >= 30:
                    messages.append({
                        "id": str(msg_uri).split("/")[-1],
                        "text": text,
                        "source_file": path,
                    })

        for msg_uri in g.subjects(RDF.type, DEVKG.AssistantMessage):
            for content in g.objects(msg_uri, SIOC.content):
                text = str(content)
                if len(text.strip()) >= 30:
                    messages.append({
                        "id": str(msg_uri).split("/")[-1],
                        "text": text,
                        "source_file": path,
                    })

    return messages


def build_batch_jsonl(messages: list[dict], output_path: str) -> int:
    """Build JSONL input file for Gemini batch prediction.

    Each line is a JSON object with the request format required by
    Vertex AI batch prediction.
    """
    count = 0
    with open(output_path, "w") as f:
        for msg in messages:
            text = msg["text"][:1500]  # Same truncation as real-time
            prompt = build_extraction_prompt(text)

            request = {
                "request": {
                    "contents": [
                        {"role": "user", "parts": [{"text": prompt}]}
                    ],
                    "generation_config": {
                        "response_mime_type": "application/json",
                        "temperature": 0.2,
                        "max_output_tokens": 4096,
                    },
                },
                "metadata": {
                    "message_id": msg["id"],
                    "source_file": msg["source_file"],
                },
            }

            f.write(json.dumps(request) + "\n")
            count += 1

    return count


def upload_to_gcs(local_path: str, bucket_name: str, blob_name: str) -> str:
    """Upload a file to Google Cloud Storage. Returns gs:// URI."""
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path)

    gs_uri = f"gs://{bucket_name}/{blob_name}"
    print(f"  Uploaded to {gs_uri}", file=sys.stderr)
    return gs_uri


def submit_batch_job(
    input_uri: str,
    output_uri: str,
    model_name: str = "gemini-2.5-flash",
) -> str:
    """Submit a Vertex AI batch prediction job.

    Returns the job resource name.
    """
    import vertexai
    from vertexai.batch_prediction import BatchPredictionJob

    job = BatchPredictionJob.submit(
        source_model=model_name,
        input_dataset=input_uri,
        output_uri_prefix=output_uri,
    )

    print(f"  Batch job submitted: {job.resource_name}", file=sys.stderr)
    print(f"  State: {job.state}", file=sys.stderr)
    return job.resource_name


def poll_job(job_name: str, poll_interval: int = 30, max_wait: int = 1800) -> bool:
    """Poll a batch job until completion or timeout."""
    from vertexai.batch_prediction import BatchPredictionJob

    # Map numeric state values to names (google.cloud.aiplatform_v1.types.JobState)
    _STATE_NAMES = {
        0: "UNSPECIFIED", 1: "QUEUED", 2: "PENDING", 3: "RUNNING",
        4: "SUCCEEDED", 5: "FAILED", 6: "CANCELLING", 7: "CANCELLED",
        8: "PAUSED", 9: "EXPIRED", 10: "UPDATING", 11: "PARTIALLY_SUCCEEDED",
    }

    elapsed = 0
    while elapsed < max_wait:
        job = BatchPredictionJob(job_name)
        raw_state = job.state
        # Handle both enum objects and raw ints
        try:
            state_val = raw_state.value if hasattr(raw_state, "value") else int(raw_state)
        except (TypeError, ValueError):
            state_val = -1
        state_name = _STATE_NAMES.get(state_val, str(raw_state))

        print(f"  [{elapsed}s] Job state: {state_name} ({state_val})", file=sys.stderr)

        if state_val == 4 or "SUCCEEDED" in state_name:
            print(f"  Job completed successfully!", file=sys.stderr)
            return True
        elif state_val in (5, 7) or "FAILED" in state_name or "CANCELLED" in state_name:
            print(f"  Job failed: {state_name}", file=sys.stderr)
            return False

        time.sleep(poll_interval)
        elapsed += poll_interval

    print(f"  Timeout after {max_wait}s", file=sys.stderr)
    return False


def parse_batch_output(output_dir: str) -> list[dict]:
    """Parse batch prediction output shards.

    Returns list of {message_id, triples} dicts.
    """
    results = []
    output_path = Path(output_dir)

    for shard in sorted(output_path.glob("*.jsonl")):
        with open(shard) as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_id = record.get("metadata", {}).get("message_id", "unknown")
                response = record.get("response", {})

                # Extract text from response
                candidates = response.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        raw_text = parts[0].get("text", "")
                        triples = _parse_triples_response(raw_text)
                        if triples:
                            results.append({
                                "message_id": msg_id,
                                "triples": triples,
                            })

    return results


def main():
    parser = argparse.ArgumentParser(description="Gemini Batch Prediction for triple extraction")
    parser.add_argument("--input", nargs="+", required=True, help="Input .ttl files to extract messages from")
    parser.add_argument("--bucket", default="devkg-batch-predictions", help="GCS bucket name")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Gemini model name")
    parser.add_argument("--prepare-only", action="store_true", help="Only prepare JSONL, don't submit")
    parser.add_argument("--poll", action="store_true", help="Poll for job completion")
    parser.add_argument("--poll-interval", type=int, default=30, help="Poll interval in seconds")
    args = parser.parse_args()

    # Initialize Vertex AI
    from pipeline.vertex_ai import init_vertex
    init_vertex()

    # Collect messages
    print(f"Collecting messages from {len(args.input)} files...", file=sys.stderr)
    messages = collect_messages_from_ttl(args.input)
    print(f"  Found {len(messages)} messages with extractable content", file=sys.stderr)

    if not messages:
        print("No messages found. Nothing to do.", file=sys.stderr)
        sys.exit(0)

    # Build batch JSONL
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_jsonl = f"/tmp/batch_input_{timestamp}.jsonl"
    count = build_batch_jsonl(messages, local_jsonl)
    print(f"  Prepared {count} requests in {local_jsonl}", file=sys.stderr)

    if args.prepare_only:
        print(f"Batch input ready at: {local_jsonl}", file=sys.stderr)
        return

    # Upload to GCS
    blob_name = f"sprint3/input_{timestamp}.jsonl"
    input_uri = upload_to_gcs(local_jsonl, args.bucket, blob_name)
    output_uri = f"gs://{args.bucket}/sprint3/output_{timestamp}/"

    # Submit batch job
    job_name = submit_batch_job(input_uri, output_uri, model_name=args.model)

    if args.poll:
        success = poll_job(job_name, poll_interval=args.poll_interval)
        if success:
            print(f"  Output available at: {output_uri}", file=sys.stderr)
        else:
            sys.exit(1)
    else:
        print(f"  Job submitted. Poll with:", file=sys.stderr)
        print(f"  python -m pipeline.batch_extraction --poll --job {job_name}", file=sys.stderr)


if __name__ == "__main__":
    main()
