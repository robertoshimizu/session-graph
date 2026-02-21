#!/bin/bash
# Integration test for DevKG RabbitMQ pipeline
#
# Tests the full pipeline:
# 1. Hook publishes message to RabbitMQ
# 2. Consumer processes the message
# 3. Output .ttl file is created
# 4. Triples are uploaded to Fuseki

set -o pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
DEVKG_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RABBITMQ_HOST="${DEVKG_RABBITMQ_HOST:-localhost}"
RABBITMQ_PORT="${DEVKG_RABBITMQ_PORT:-15672}"
RABBITMQ_USER="${DEVKG_RABBITMQ_USER:-devkg}"
RABBITMQ_PASS="${DEVKG_RABBITMQ_PASS:-devkg}"
OUTPUT_DIR="${DEVKG_OUTPUT_DIR:-${DEVKG_ROOT}/output/claude}"
FUSEKI_URL="${FUSEKI_URL:-http://localhost:3030}"
FUSEKI_DATASET="${FUSEKI_DATASET:-devkg}"

RABBITMQ_URL="http://${RABBITMQ_HOST}:${RABBITMQ_PORT}"
QUEUE="devkg_jobs"

# Test session file — must be under ~/.claude/projects/ so the container can access it
# (the container mounts ~/.claude/projects:/claude-sessions:ro)
TEST_SESSION_DIR="$HOME/.claude/projects/_test-devkg"
mkdir -p "$TEST_SESSION_DIR"
TEST_SESSION_ID="test-integration-$(date +%s)"
TEST_SESSION_FILE="${TEST_SESSION_DIR}/${TEST_SESSION_ID}.jsonl"

# Counters
TESTS_RUN=0
TESTS_PASSED=0

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_test() {
    local result=$?
    TESTS_RUN=$((TESTS_RUN + 1))
    if [ $result -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $1"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${RED}✗${NC} $1"
        return 1
    fi
}

cleanup() {
    log_info "Cleaning up test files..."
    rm -f "$TEST_SESSION_FILE"
    rmdir "$TEST_SESSION_DIR" 2>/dev/null || true
    rm -f "${OUTPUT_DIR}/${TEST_SESSION_ID}.ttl"
}

trap cleanup EXIT

# =============================================================================
# PREREQUISITES
# =============================================================================

log_info "Checking prerequisites..."

command -v docker >/dev/null 2>&1
check_test "docker installed"

command -v jq >/dev/null 2>&1
check_test "jq installed"

command -v curl >/dev/null 2>&1
check_test "curl installed"

# =============================================================================
# DOCKER SERVICES
# =============================================================================

log_info "Checking Docker services..."

# Check if all 3 services are running (docker compose ps outputs one JSON object per line, not an array)
FUSEKI_RUNNING=$(docker compose -f "$DEVKG_ROOT/docker-compose.yml" ps fuseki --format json 2>/dev/null | jq -r '.State // "stopped"' | head -1)
RABBITMQ_RUNNING=$(docker compose -f "$DEVKG_ROOT/docker-compose.yml" ps rabbitmq --format json 2>/dev/null | jq -r '.State // "stopped"' | head -1)
CONSUMER_RUNNING=$(docker compose -f "$DEVKG_ROOT/docker-compose.yml" ps pipeline-runner --format json 2>/dev/null | jq -r '.State // "stopped"' | head -1)

[ "$FUSEKI_RUNNING" = "running" ]
check_test "Fuseki service running"

[ "$RABBITMQ_RUNNING" = "running" ]
check_test "RabbitMQ service running"

[ "$CONSUMER_RUNNING" = "running" ]
check_test "Consumer service running"

# =============================================================================
# RABBITMQ HEALTH
# =============================================================================

log_info "Checking RabbitMQ health..."

RABBIT_OVERVIEW=$(curl -s -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
    "${RABBITMQ_URL}/api/overview" 2>/dev/null)

echo "$RABBIT_OVERVIEW" | jq -e '.rabbitmq_version' >/dev/null 2>&1
check_test "RabbitMQ HTTP API responding"

QUEUE_EXISTS=$(curl -s -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
    "${RABBITMQ_URL}/api/queues/%2f/${QUEUE}" 2>/dev/null | jq -e '.name' >/dev/null 2>&1 && echo "yes" || echo "no")

[ "$QUEUE_EXISTS" = "yes" ]
check_test "Queue '${QUEUE}' exists"

# =============================================================================
# CREATE TEST SESSION FILE
# =============================================================================

log_info "Creating test session file..."

cat > "$TEST_SESSION_FILE" << 'EOF'
{"type":"session_start","timestamp":"2026-02-21T10:00:00.000Z","session_id":"test-integration"}
{"type":"message","role":"user","content":[{"type":"text","text":"Test message about using Docker and RabbitMQ for pipeline processing"}],"timestamp":"2026-02-21T10:00:01.000Z"}
{"type":"message","role":"assistant","content":[{"type":"text","text":"Docker and RabbitMQ are great tools for building distributed pipelines. Docker provides containerization while RabbitMQ handles message queuing."}],"timestamp":"2026-02-21T10:00:02.000Z"}
{"type":"session_end","timestamp":"2026-02-21T10:00:03.000Z"}
EOF

[ -f "$TEST_SESSION_FILE" ]
check_test "Test session file created"

# =============================================================================
# PUBLISH TEST MESSAGE
# =============================================================================

log_info "Publishing test message to RabbitMQ..."

PAYLOAD=$(jq -n \
    --arg tp "$TEST_SESSION_FILE" \
    --arg sid "$TEST_SESSION_ID" \
    '{transcript_path: $tp, session_id: $sid}')

RABBIT_BODY=$(jq -n \
    --arg payload "$PAYLOAD" \
    '{
        properties: {delivery_mode: 2},
        routing_key: "'"$QUEUE"'",
        payload: $payload,
        payload_encoding: "string"
    }')

PUBLISH_URL="${RABBITMQ_URL}/api/exchanges/%2f/amq.default/publish"

curl -s -f -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
    -H "Content-Type: application/json" \
    -d "$RABBIT_BODY" \
    "$PUBLISH_URL" >/dev/null 2>&1

check_test "Message published to queue"

# =============================================================================
# WAIT FOR CONSUMER PROCESSING
# =============================================================================

log_info "Waiting for consumer to process message..."

TIMEOUT=120
INTERVAL=2
ELAPSED=0
OUTPUT_FILE="${OUTPUT_DIR}/${TEST_SESSION_ID}.ttl"

while [ $ELAPSED -lt $TIMEOUT ]; do
    if [ -f "$OUTPUT_FILE" ]; then
        log_info "Output file created after ${ELAPSED}s"
        break
    fi
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

[ -f "$OUTPUT_FILE" ]
check_test "Output .ttl file created"

# =============================================================================
# CHECK CONSUMER LOGS
# =============================================================================

log_info "Checking consumer logs..."

CONSUMER_LOGS=$(docker compose -f "$DEVKG_ROOT/docker-compose.yml" logs pipeline-runner --tail=50 2>/dev/null || echo "")

echo "$CONSUMER_LOGS" | grep -q "Processing: ${TEST_SESSION_ID}"
check_test "Consumer log shows processing started"

echo "$CONSUMER_LOGS" | grep -q "DONE.*${TEST_SESSION_ID}"
check_test "Consumer log shows processing completed"

# =============================================================================
# VERIFY OUTPUT FILE CONTENT
# =============================================================================

log_info "Verifying output file content..."

if [ -f "$OUTPUT_FILE" ]; then
    # Check that file is non-empty valid Turtle
    FILE_SIZE=$(wc -c < "$OUTPUT_FILE" | tr -d ' ')
    [ "$FILE_SIZE" -gt 0 ]
    check_test "Output file is non-empty (${FILE_SIZE} bytes)"
else
    log_warn "Output file not found, skipping content verification"
fi

# =============================================================================
# VERIFY FUSEKI UPLOAD
# =============================================================================

log_info "Verifying Fuseki upload..."

# Check if dataset exists (Fuseki admin API requires auth)
FUSEKI_ADMIN_USER="${FUSEKI_ADMIN_USER:-admin}"
FUSEKI_ADMIN_PASS="${FUSEKI_ADMIN_PASS:-admin}"
DATASET_EXISTS=$(curl -s -u "${FUSEKI_ADMIN_USER}:${FUSEKI_ADMIN_PASS}" "${FUSEKI_URL}/$/datasets" 2>/dev/null | jq -e ".datasets[] | select(.\"ds.name\" == \"/${FUSEKI_DATASET}\")" >/dev/null 2>&1 && echo "yes" || echo "no")

[ "$DATASET_EXISTS" = "yes" ]
check_test "Fuseki dataset '${FUSEKI_DATASET}' exists"

# Query for total triples in dataset
if [ "$DATASET_EXISTS" = "yes" ]; then
    SPARQL_RESULT=$(curl -s -G \
        -H "Accept: application/sparql-results+json" \
        --data-urlencode "query=SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }" \
        "${FUSEKI_URL}/${FUSEKI_DATASET}/sparql" 2>/dev/null)

    RESULT_COUNT=$(echo "$SPARQL_RESULT" | jq -r '.results.bindings[0].count.value // "0"')
    [ "$RESULT_COUNT" -gt 0 ]
    check_test "Fuseki contains triples (${RESULT_COUNT} total)"
fi

# =============================================================================
# SUMMARY
# =============================================================================

echo ""
log_info "============================================"
log_info "Integration Test Summary"
log_info "============================================"
log_info "Tests run: ${TESTS_RUN}"
log_info "Tests passed: ${TESTS_PASSED}"
log_info "Tests failed: $((TESTS_RUN - TESTS_PASSED))"

if [ $TESTS_PASSED -eq $TESTS_RUN ]; then
    echo -e "${GREEN}ALL TESTS PASSED ✓${NC}"
    exit 0
else
    echo -e "${RED}SOME TESTS FAILED ✗${NC}"
    exit 1
fi
