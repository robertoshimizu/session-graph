#!/bin/bash
# Stop hook for Claude Code — real-time KG ingestion.
#
# Extracts knowledge triples from each assistant response as it happens.
# One Gemini API call per response (~3-5s), backgrounded so user sees zero delay.
#
# Input (stdin JSON from Claude Code):
#   { "session_id": "...", "transcript_path": "...", "stop_hook_active": false, ... }
#
# Register in ~/.claude/settings.json:
# {
#   "hooks": {
#     "Stop": [{
#       "hooks": [{
#         "type": "command",
#         "command": ".../hooks/stop_hook.sh",
#         "timeout": 5
#       }]
#     }]
#   }
# }

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"

# Read stdin JSON from Claude Code hook API
INPUT=$(cat)

# Guard: venv exists
if [ ! -x "$VENV" ]; then
    exit 0
fi

# Parse key fields using Python (fast, no jq dependency)
PARSED=$("$VENV" -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('stop_hook_active', False))
    print(d.get('transcript_path', ''))
    print(d.get('session_id', ''))
except Exception:
    print('True')  # stop_hook_active=True forces skip
    print('')
    print('')
" "$INPUT" 2>/dev/null) || exit 0

STOP_HOOK_ACTIVE=$(echo "$PARSED" | sed -n '1p')
TRANSCRIPT_PATH=$(echo "$PARSED" | sed -n '2p')
SESSION_ID=$(echo "$PARSED" | sed -n '3p')

# Guard: prevent infinite loops
if [ "$STOP_HOOK_ACTIVE" = "True" ]; then
    exit 0
fi

# Guard: need transcript path
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    exit 0
fi

# Guard: need session ID
if [ -z "$SESSION_ID" ]; then
    exit 0
fi

# Background the extraction — exit immediately
mkdir -p "$LOG_DIR"
(
    "$VENV" "$PROJECT_DIR/pipeline/realtime_extract.py" \
        --session-id "$SESSION_ID" \
        --transcript "$TRANSCRIPT_PATH" \
        >> "$LOG_DIR/realtime_hook.log" 2>&1
) &>/dev/null &

exit 0
