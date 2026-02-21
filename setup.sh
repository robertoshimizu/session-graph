#!/bin/bash
# session-graph setup script
# Idempotent — safe to re-run. Skips completed steps.

set -euo pipefail

DEVKG_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$DEVKG_ROOT"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

step() { echo -e "\n${BOLD}[$1/7]${NC} $2"; }
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
skip() { echo -e "  ${YELLOW}→${NC} $1 (already done)"; }
err()  { echo -e "  ${RED}✗${NC} $1" >&2; }

# ── Step 1: Check prerequisites ──────────────────────────────────────────────

step 1 "Checking prerequisites"

MISSING=()
command -v python3 >/dev/null 2>&1 || MISSING+=("python3 (3.11+)")
command -v docker  >/dev/null 2>&1 || MISSING+=("docker")
command -v jq      >/dev/null 2>&1 || MISSING+=("jq")

if command -v python3 >/dev/null 2>&1; then
    PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
        MISSING+=("python3 >= 3.11 (found $PY_VERSION)")
    fi
fi

# Check for docker compose (v2 plugin or standalone)
if command -v docker >/dev/null 2>&1; then
    if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
        MISSING+=("docker compose (v2 plugin or standalone)")
    fi
fi

if [ ${#MISSING[@]} -gt 0 ]; then
    err "Missing prerequisites:"
    for m in "${MISSING[@]}"; do
        echo "     - $m"
    done
    exit 1
fi

ok "python3 ($PY_VERSION), docker, docker compose, jq"

# ── Step 2: Configure .env ───────────────────────────────────────────────────

step 2 "Configuring environment"

if [ -f .env ]; then
    skip ".env already exists"
else
    echo "  Which LLM provider will you use?"
    echo "    1) gemini     (Google AI Studio — recommended)"
    echo "    2) openai     (OpenAI API)"
    echo "    3) anthropic  (Anthropic API)"
    echo "    4) ollama     (Local, no API key needed)"
    echo ""
    read -rp "  Provider [1-4, default 1]: " PROVIDER_CHOICE
    PROVIDER_CHOICE=${PROVIDER_CHOICE:-1}

    case "$PROVIDER_CHOICE" in
        1) PROVIDER="gemini";    MODEL="gemini-2.5-flash"; KEY_VAR="GEMINI_API_KEY" ;;
        2) PROVIDER="openai";    MODEL="gpt-4o-mini";      KEY_VAR="OPENAI_API_KEY" ;;
        3) PROVIDER="anthropic"; MODEL="claude-haiku-4";    KEY_VAR="ANTHROPIC_API_KEY" ;;
        4) PROVIDER="ollama";    MODEL="llama3.2";          KEY_VAR="" ;;
        *) err "Invalid choice"; exit 1 ;;
    esac

    cp .env.example .env

    # Update provider and model
    sed -i.bak "s/^LLM_PROVIDER=.*/LLM_PROVIDER=$PROVIDER/" .env
    sed -i.bak "s/^LLM_MODEL=.*/LLM_MODEL=$MODEL/" .env

    if [ -n "$KEY_VAR" ]; then
        read -rp "  Enter your $KEY_VAR: " API_KEY
        if [ -n "$API_KEY" ]; then
            # Uncomment and set the key
            sed -i.bak "s|^# *${KEY_VAR}=.*|${KEY_VAR}=${API_KEY}|" .env
            sed -i.bak "s|^${KEY_VAR}=your-.*|${KEY_VAR}=${API_KEY}|" .env
        fi
    fi

    rm -f .env.bak
    ok "Created .env (provider: $PROVIDER, model: $MODEL)"
fi

# ── Step 3: Create Python virtualenv ─────────────────────────────────────────

step 3 "Setting up Python virtualenv"

if [ -d .venv ]; then
    skip ".venv already exists"
else
    python3 -m venv .venv
    ok "Created .venv"
fi

source .venv/bin/activate

# Determine requirements file for provider
PROVIDER_FROM_ENV=$(grep '^LLM_PROVIDER=' .env 2>/dev/null | cut -d= -f2 || echo "gemini")
REQ_FILE="requirements-${PROVIDER_FROM_ENV}.txt"
if [ ! -f "$REQ_FILE" ]; then
    REQ_FILE="requirements.txt"
fi

pip install -q -r "$REQ_FILE"
ok "Installed dependencies from $REQ_FILE"

# ── Step 4: Create output directories ────────────────────────────────────────

step 4 "Creating output directories"

DIRS=(output/claude output/deepseek output/grok output/warp logs)
CREATED=0
for d in "${DIRS[@]}"; do
    if [ ! -d "$d" ]; then
        mkdir -p "$d"
        CREATED=$((CREATED + 1))
    fi
done

if [ $CREATED -gt 0 ]; then
    ok "Created $CREATED directories"
else
    skip "All output directories exist"
fi

# ── Step 5: Start Docker Compose ─────────────────────────────────────────────

step 5 "Starting Docker services (Fuseki + RabbitMQ)"

# Use docker compose v2 or fall back to docker-compose
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
else
    DC="docker-compose"
fi

# Check if already running
if curl -sf http://localhost:3030/$/ping >/dev/null 2>&1; then
    skip "Fuseki already running at http://localhost:3030"
else
    $DC up -d

    echo "  Waiting for Fuseki..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:3030/$/ping >/dev/null 2>&1; then
            break
        fi
        sleep 2
    done

    if curl -sf http://localhost:3030/$/ping >/dev/null 2>&1; then
        ok "Fuseki ready at http://localhost:3030"
    else
        err "Fuseki did not start within 60s — check 'docker compose logs fuseki'"
    fi
fi

# Check RabbitMQ
if curl -sf -u devkg:devkg http://localhost:15672/api/overview >/dev/null 2>&1; then
    ok "RabbitMQ ready at http://localhost:15672"
else
    echo "  Waiting for RabbitMQ..."
    for i in $(seq 1 15); do
        if curl -sf -u devkg:devkg http://localhost:15672/api/overview >/dev/null 2>&1; then
            break
        fi
        sleep 2
    done
    if curl -sf -u devkg:devkg http://localhost:15672/api/overview >/dev/null 2>&1; then
        ok "RabbitMQ ready at http://localhost:15672"
    else
        err "RabbitMQ management API not reachable — check 'docker compose logs rabbitmq'"
    fi
fi

# ── Step 6: Install stop hook (optional) ─────────────────────────────────────

step 6 "Claude Code stop hook (auto-processing)"

HOOK_CMD="${DEVKG_ROOT}/hooks/stop_hook.sh"
SETTINGS_FILE="$HOME/.claude/settings.json"

# Check if hook is already configured
if [ -f "$SETTINGS_FILE" ] && grep -q "stop_hook.sh" "$SETTINGS_FILE" 2>/dev/null; then
    skip "Stop hook already configured in $SETTINGS_FILE"
else
    read -rp "  Install auto-processing hook for Claude Code? [y/N]: " INSTALL_HOOK
    if [[ "$INSTALL_HOOK" =~ ^[Yy]$ ]]; then
        mkdir -p "$(dirname "$SETTINGS_FILE")"

        if [ -f "$SETTINGS_FILE" ]; then
            # Merge hook into existing settings
            HOOK_JSON=$(jq -n --arg cmd "$HOOK_CMD" '{
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": $cmd, "timeout": 5}]}]
                }
            }')
            MERGED=$(jq -s '.[0] * .[1]' "$SETTINGS_FILE" <(echo "$HOOK_JSON"))
            echo "$MERGED" > "$SETTINGS_FILE"
        else
            jq -n --arg cmd "$HOOK_CMD" '{
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": $cmd, "timeout": 5}]}]
                }
            }' > "$SETTINGS_FILE"
        fi

        ok "Hook installed: $HOOK_CMD"
    else
        skip "Skipped (run setup.sh again to install later)"
    fi
fi

# ── Step 7: Smoke test ───────────────────────────────────────────────────────

step 7 "Smoke test"

SAMPLE="tests/fixtures/sample_session.jsonl"
SAMPLE_OUT="output/claude/sample-session-001.ttl"

if [ ! -f "$SAMPLE" ]; then
    err "Sample session not found: $SAMPLE"
else
    # Process sample with --skip-extraction (no LLM calls needed)
    python -m pipeline.jsonl_to_rdf "$SAMPLE" "$SAMPLE_OUT" --skip-extraction 2>/dev/null

    if [ -f "$SAMPLE_OUT" ]; then
        ok "Generated $SAMPLE_OUT"

        # Load into Fuseki
        if python -m pipeline.load_fuseki "$SAMPLE_OUT" --auth admin:admin 2>/dev/null; then
            TRIPLES=$(curl -sf -u admin:admin \
                -H "Accept: application/sparql-results+json" \
                --data-urlencode "query=SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }" \
                http://localhost:3030/devkg/sparql 2>/dev/null \
                | jq -r '.results.bindings[0].c.value' 2>/dev/null || echo "?")
            ok "Loaded into Fuseki ($TRIPLES triples)"
        else
            err "Failed to load into Fuseki (is it running?)"
        fi
    else
        err "Failed to generate RDF output"
    fi
fi

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}━━━ Setup complete ━━━${NC}"
echo ""
echo "  Services:"
echo "    Fuseki SPARQL UI:    http://localhost:3030"
echo "    RabbitMQ Management: http://localhost:15672  (devkg/devkg)"
echo ""
echo "  Next steps:"
echo "    # Process a real session"
echo "    source .venv/bin/activate"
echo "    python -m pipeline.jsonl_to_rdf ~/.claude/projects/.../session.jsonl output/claude/session.ttl"
echo ""
echo "    # Bulk process all Claude Code sessions"
echo "    python -m pipeline.bulk_process --limit 10"
echo ""
echo "    # Load results into Fuseki"
echo "    python -m pipeline.load_fuseki output/claude/*.ttl --auth admin:admin"
echo ""
echo "    # Query at http://localhost:3030 → dataset 'devkg' → query tab"
