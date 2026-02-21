#!/usr/bin/env python3
"""RabbitMQ consumer for DevKG pipeline jobs.

Listens on the `devkg_jobs` queue, processes Claude Code session transcripts
into RDF Turtle, and uploads them to Fuseki.
"""

import base64
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import pika


def _init_vertex_credentials():
    """Decode GOOGLE_APPLICATION_CREDENTIALS_BASE64 to a temp file if present."""
    b64 = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_BASE64")
    if not b64 or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return
    decoded = base64.b64decode(b64).decode("utf-8")
    fd, path = tempfile.mkstemp(suffix=".json", prefix="gcp-creds-")
    os.write(fd, decoded.encode())
    os.close(fd)
    os.chmod(path, 0o600)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path


_init_vertex_credentials()


RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://devkg:devkg@localhost:5672/")
FUSEKI_URL = os.environ.get("FUSEKI_URL", "http://localhost:3030")
FUSEKI_DATASET = os.environ.get("FUSEKI_DATASET", "devkg")
FUSEKI_USER = os.environ.get("FUSEKI_USER", "admin")
FUSEKI_PASS = os.environ.get("FUSEKI_PASS", "admin")
FUSEKI_AUTH = (FUSEKI_USER, FUSEKI_PASS)
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/app/output/claude"))

QUEUE = "devkg_jobs"
DLX = "devkg_jobs_dlx"
DLQ = "devkg_jobs_failed"


def log(level: str, msg: str):
    print(f"[{level}] {msg}", file=sys.stderr, flush=True)


def connect_with_retry(url: str, max_retries: int = 10) -> pika.BlockingConnection:
    """Connect to RabbitMQ with exponential backoff."""
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            params = pika.URLParameters(url)
            params.heartbeat = 600
            params.blocked_connection_timeout = 300
            conn = pika.BlockingConnection(params)
            log("INFO", f"Connected to RabbitMQ (attempt {attempt})")
            return conn
        except pika.exceptions.AMQPConnectionError as e:
            if attempt == max_retries:
                raise
            log("WARN", f"Connection failed (attempt {attempt}/{max_retries}): {e}")
            time.sleep(delay)
            delay = min(delay * 2, 30.0)


def setup_queues(channel):
    """Declare the main queue with dead-letter exchange."""
    # Dead-letter exchange + queue
    channel.exchange_declare(exchange=DLX, exchange_type="fanout", durable=True)
    channel.queue_declare(queue=DLQ, durable=True)
    channel.queue_bind(queue=DLQ, exchange=DLX)

    # Main queue with DLX
    channel.queue_declare(
        queue=QUEUE,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX},
    )
    channel.basic_qos(prefetch_count=1)


def translate_path(host_path: str) -> str:
    """Translate host path to container path.

    Host: ~/.claude/projects/{slug}/{session}.jsonl
    Container: /claude-sessions/{slug}/{session}.jsonl
    """
    # Find /projects/ in the path and replace everything before it
    marker = "/projects/"
    idx = host_path.find(marker)
    if idx == -1:
        return host_path  # can't translate, return as-is
    return "/claude-sessions" + host_path[idx + len("/projects") :]


def process_message(body: bytes) -> None:
    """Process a single pipeline job."""
    msg = json.loads(body)
    transcript_path = msg.get("transcript_path", "")
    session_id = msg.get("session_id", "")

    if not transcript_path:
        log("WARN", "Message missing transcript_path, skipping")
        return

    # Skip subagent sessions
    if "/subagents/" in transcript_path:
        log("INFO", f"Skipping subagent session: {session_id}")
        return

    # Translate host path to container path
    container_path = translate_path(transcript_path)

    if not os.path.exists(container_path):
        raise FileNotFoundError(f"Transcript not found: {container_path} (host: {transcript_path})")

    # Derive output filename
    basename = session_id or Path(container_path).stem
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"{basename}.ttl"

    log("INFO", f"Processing: {basename}")

    # Import pipeline modules (deferred to avoid import errors during setup)
    from pipeline.jsonl_to_rdf import build_graph
    from pipeline.llm_providers import get_provider
    from pipeline.load_fuseki import ensure_dataset, upload_turtle

    # Build RDF graph
    model = get_provider()
    graph = build_graph(container_path, skip_extraction=False, model=model)

    # Serialize to Turtle
    graph.serialize(destination=str(output_file), format="turtle")
    triple_count = len(graph)

    # Upload to Fuseki
    ensure_dataset(FUSEKI_URL, FUSEKI_DATASET, auth=FUSEKI_AUTH)
    upload_turtle(FUSEKI_URL, FUSEKI_DATASET, str(output_file), auth=FUSEKI_AUTH)

    log("DONE", f"{basename} -> {output_file} ({triple_count} triples)")


def on_message(channel, method, properties, body):
    """RabbitMQ message callback."""
    try:
        process_message(body)
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        msg = json.loads(body) if body else {}
        session_id = msg.get("session_id", "unknown")
        log("ERROR", f"{session_id}: {e}")
        traceback.print_exc(file=sys.stderr)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
    connection = connect_with_retry(RABBITMQ_URL)
    channel = connection.channel()
    setup_queues(channel)

    channel.basic_consume(queue=QUEUE, on_message_callback=on_message)

    log("READY", f"Waiting for jobs on {QUEUE}")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        log("INFO", "Shutting down")
        channel.stop_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
