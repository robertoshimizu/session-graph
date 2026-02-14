#!/bin/bash
# Post-session hook for Claude Code
# Triggered after a Claude Code session ends
# Usage: hooks/post_session_hook.sh <session_jsonl_path>
#
# To register as a Claude Code hook, add to .claude/settings.json:
# {
#   "hooks": {
#     "post_session": ["./hooks/post_session_hook.sh"]
#   }
# }

set -euo pipefail

SESSION_FILE="${1:?Usage: $0 <session.jsonl>}"
BASENAME="$(basename "$SESSION_FILE" .jsonl)"
OUTPUT_DIR="$(dirname "$0")/../output"
VENV="$(dirname "$0")/../.venv/bin/python"

echo "[hook] Processing session: $BASENAME"

# Convert JSONL to RDF
"$VENV" -m pipeline.jsonl_to_rdf "$SESSION_FILE" "$OUTPUT_DIR/${BASENAME}.ttl"

# Entity linking
"$VENV" -m pipeline.link_entities --input "$OUTPUT_DIR/${BASENAME}.ttl" --output "$OUTPUT_DIR/${BASENAME}_wikidata.ttl"

# Load into Fuseki (if running)
if curl -s http://localhost:3030/$/ping > /dev/null 2>&1; then
    "$VENV" pipeline/load_fuseki.py "$OUTPUT_DIR/${BASENAME}.ttl" "$OUTPUT_DIR/${BASENAME}_wikidata.ttl"
    echo "[hook] Loaded into Fuseki"
else
    echo "[hook] Fuseki not running, skipping load"
fi

echo "[hook] Done: $BASENAME"
