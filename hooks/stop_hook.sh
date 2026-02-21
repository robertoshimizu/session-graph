#!/bin/bash
# DevKG Stop Hook — publishes pipeline job to RabbitMQ after each Claude Code session.
#
# Instead of running Python directly (which gets killed when Claude exits),
# we POST a message to RabbitMQ via its HTTP API (<100ms).
# A separate container consumes the queue and runs the pipeline.

set -euo pipefail

# Configuration (override via environment)
DEVKG_RABBITMQ_HOST="${DEVKG_RABBITMQ_HOST:-localhost}"
DEVKG_RABBITMQ_PORT="${DEVKG_RABBITMQ_PORT:-15672}"
DEVKG_RABBITMQ_USER="${DEVKG_RABBITMQ_USER:-devkg}"
DEVKG_RABBITMQ_PASS="${DEVKG_RABBITMQ_PASS:-devkg}"
DEVKG_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEVKG_OUTPUT_DIR="${DEVKG_OUTPUT_DIR:-${DEVKG_ROOT}/output/claude}"
DEVKG_LOG_DIR="${DEVKG_LOG_DIR:-${DEVKG_ROOT}/logs}"

mkdir -p "$DEVKG_OUTPUT_DIR" "$DEVKG_LOG_DIR"

LOG_FILE="$DEVKG_LOG_DIR/stop_hook.log"

# Read JSON from stdin
INPUT=$(cat)

TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

# Bail if no transcript
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    exit 0
fi

# Skip subagent sessions (duplicate content)
if echo "$TRANSCRIPT_PATH" | grep -q "/subagents/"; then
    exit 0
fi

# Derive output filename for watermark check
BASENAME="${SESSION_ID:-$(basename "$TRANSCRIPT_PATH" .jsonl)}"
OUTPUT_FILE="$DEVKG_OUTPUT_DIR/${BASENAME}.ttl"

# Skip if already processed (watermark: output file exists and is newer than transcript)
if [ -f "$OUTPUT_FILE" ] && [ "$OUTPUT_FILE" -nt "$TRANSCRIPT_PATH" ]; then
    exit 0
fi

# Build the RabbitMQ publish payload
PAYLOAD=$(jq -n \
    --arg tp "$TRANSCRIPT_PATH" \
    --arg sid "$SESSION_ID" \
    '{transcript_path: $tp, session_id: $sid}')

RABBIT_BODY=$(jq -n \
    --arg payload "$PAYLOAD" \
    '{
        properties: {delivery_mode: 2},
        routing_key: "devkg_jobs",
        payload: $payload,
        payload_encoding: "string"
    }')

# Publish to RabbitMQ HTTP API
RABBIT_URL="http://${DEVKG_RABBITMQ_HOST}:${DEVKG_RABBITMQ_PORT}/api/exchanges/%2f/amq.default/publish"

if curl -s -f -u "${DEVKG_RABBITMQ_USER}:${DEVKG_RABBITMQ_PASS}" \
    -H "Content-Type: application/json" \
    -d "$RABBIT_BODY" \
    "$RABBIT_URL" > /dev/null 2>&1; then
    echo "[$(date)] Queued: $TRANSCRIPT_PATH (session: $SESSION_ID)" >> "$LOG_FILE"
else
    echo "[$(date)] ERROR: Failed to publish to RabbitMQ at $RABBIT_URL" >> "$LOG_FILE"
    echo "[$(date)]   Transcript: $TRANSCRIPT_PATH" >> "$LOG_FILE"
fi

exit 0
