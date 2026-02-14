"""
Agentic Wikidata Entity Linker using Google ADK (Agent Development Kit).

Uses a ReAct-style agent with Gemini 2.5 Flash Lite to search Wikidata,
reason about ambiguous entities, and return the best QID match.

Usage:
    cd dev-knowledge-graph
    .venv/bin/python pipeline/agentic_linker_adk.py
"""

import asyncio
import os
import sys
import re
import time
import base64
import tempfile
import atexit
import json
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 1. Credential setup (must happen BEFORE any google.adk / google.genai import)
# ---------------------------------------------------------------------------

def _init_credentials():
    """Decode base64 GCP credentials and configure env vars for ADK/Vertex AI."""
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

    # ADK Vertex AI env vars
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
    os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")
    os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ.get("CLOUD_ML_REGION", "us-east5")

    # Decode base64 credentials to temp file
    b64_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_BASE64")
    if not b64_creds:
        print("WARNING: GOOGLE_APPLICATION_CREDENTIALS_BASE64 not set", file=sys.stderr)
        return

    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        # Already set (e.g. by another init), skip
        return

    decoded = base64.b64decode(b64_creds).decode("utf-8")
    fd, creds_path = tempfile.mkstemp(suffix=".json", prefix="gcp-creds-")
    os.write(fd, decoded.encode("utf-8"))
    os.close(fd)
    os.chmod(creds_path, 0o600)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path

    # Infer project ID from credentials if not set
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        try:
            os.environ["GOOGLE_CLOUD_PROJECT"] = json.loads(decoded)["project_id"]
        except (json.JSONDecodeError, KeyError):
            pass

    atexit.register(lambda: os.unlink(creds_path) if os.path.exists(creds_path) else None)
    print(f"  Vertex AI credentials configured (project={os.environ.get('GOOGLE_CLOUD_PROJECT')}, "
          f"location={os.environ.get('GOOGLE_CLOUD_LOCATION')})", file=sys.stderr)


_init_credentials()

# Now safe to import ADK
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# ---------------------------------------------------------------------------
# 2. Wikidata search tool
# ---------------------------------------------------------------------------

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "DevKG-AgenticLinker/1.0 (https://github.com/devkg) Python/requests"}


def search_wikidata(query: str) -> dict:
    """Search Wikidata for entities matching the query string.

    Returns top 5 candidates with QID, label, and description.
    Use this to find Wikidata identifiers for technical entities.

    Args:
        query: Search term (e.g. "python programming language", "neo4j", "kubernetes").

    Returns:
        Dictionary with 'results' list containing candidates, each with
        'qid', 'label', and 'description' fields.
    """
    params = {
        "action": "wbsearchentities",
        "search": query,
        "language": "en",
        "format": "json",
        "limit": 5,
        "type": "item",
    }
    try:
        resp = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": str(e), "results": []}

    candidates = []
    for item in data.get("search", []):
        candidates.append({
            "qid": item.get("id", ""),
            "label": item.get("label", ""),
            "description": item.get("description", ""),
        })

    return {"query": query, "results": candidates}


# ---------------------------------------------------------------------------
# 3. Agent definition
# ---------------------------------------------------------------------------

SHARED_PROMPT = """\
You are a Wikidata entity linking agent for a developer knowledge graph.
You receive a technical entity name and the context sentence where it appeared.

Your goal: find the correct Wikidata QID for this entity.

Steps:
1. Search Wikidata with the entity name using the search_wikidata tool.
2. Examine the results. Prefer entries whose description mentions software, programming,
   framework, database, protocol, library, tool, or technology.
3. If no good match is found, reason about what the entity means in the given context,
   then search again with alternative or expanded terms. Examples:
   - "apis" -> try "application programming interface"
   - "k8s" -> try "kubernetes"
   - "js" -> try "javascript"
   - "backend" -> try "back end" or "backend development"
   - "agent" -> try "software agent" or "intelligent agent"
4. You may call the search tool up to 3 times total.
5. When you have found the best match (or determined there is none), return your answer.
"""

# ADK requires text output format (no structured output support like LangGraph)
AGENT_INSTRUCTION = SHARED_PROMPT + """
Respond with EXACTLY this format (no markdown, no extra text):

QID: <wikidata_id or NONE>
CONFIDENCE: <float between 0.0 and 1.0>
LABEL: <entity label from wikidata, or N/A>
DESCRIPTION: <entity description from wikidata, or N/A>
REASONING: <one sentence explaining your choice>
"""


def build_agent() -> Agent:
    """Create the Wikidata linker agent."""
    return Agent(
        name="wikidata_linker",
        model="gemini-2.5-flash-lite",
        description="Links developer entities to Wikidata QIDs",
        instruction=AGENT_INSTRUCTION,
        tools=[search_wikidata],
    )


# ---------------------------------------------------------------------------
# 4. Result parsing
# ---------------------------------------------------------------------------

@dataclass
class LinkResult:
    entity: str
    qid: str
    confidence: float
    label: str
    description: str
    reasoning: str
    elapsed_s: float


def parse_agent_response(text: str, entity: str, elapsed: float) -> LinkResult:
    """Parse the structured text response from the agent."""
    def extract(field: str) -> str:
        pattern = rf"^{field}:\s*(.+)$"
        m = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    qid = extract("QID")
    if qid.upper() == "NONE":
        qid = "NONE"

    conf_str = extract("CONFIDENCE")
    try:
        confidence = float(conf_str)
    except (ValueError, TypeError):
        confidence = 0.0

    return LinkResult(
        entity=entity,
        qid=qid,
        confidence=confidence,
        label=extract("LABEL"),
        description=extract("DESCRIPTION"),
        reasoning=extract("REASONING"),
        elapsed_s=elapsed,
    )


# ---------------------------------------------------------------------------
# 5. Runner logic
# ---------------------------------------------------------------------------

APP_NAME = "wikidata_linker_app"
USER_ID = "dev"


async def link_entity(entity: str, context: str) -> LinkResult:
    """Run the agent to link a single entity."""
    agent = build_agent()
    session_service = InMemorySessionService()
    session_id = f"session-{entity.replace(' ', '_')}"

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
    )

    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    prompt = f"Entity: {entity}\nContext: {context}"
    content = types.Content(
        role="user",
        parts=[types.Part(text=prompt)],
    )

    t0 = time.time()
    final_text = ""

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    final_text += part.text

    elapsed = time.time() - t0
    return parse_agent_response(final_text, entity, elapsed)


# ---------------------------------------------------------------------------
# 6. Main: test cases
# ---------------------------------------------------------------------------

TEST_CASES = [
    ("python",  "dedicated backend service builtWith Go, Node.js, Python"),
    ("backend", "dedicated backend service deployedOn container"),
    ("agent",   "Claude agent SDK for building autonomous AI agents"),
    ("apis",    "apis enable data consumption from external services"),
    ("neo4j",   "Neo4j graph database for knowledge graph storage"),
    ("k8s",     "k8s orchestrates container deployments across clusters"),
    ("js",      "frontend built with js and react framework"),
]


async def main():
    print("\n" + "=" * 90)
    print("  Agentic Wikidata Entity Linker (Google ADK + Gemini 2.5 Flash Lite)")
    print("=" * 90 + "\n")

    results: list[LinkResult] = []
    for entity, context in TEST_CASES:
        print(f"  Linking: '{entity}' ...", end="", flush=True)
        try:
            r = await link_entity(entity, context)
            results.append(r)
            print(f" -> {r.qid} ({r.elapsed_s:.1f}s)")
        except Exception as e:
            print(f" ERROR: {e}")
            results.append(LinkResult(
                entity=entity, qid="ERROR", confidence=0.0,
                label="", description=str(e), reasoning="", elapsed_s=0.0,
            ))

    # Print results table
    print("\n" + "=" * 90)
    print(f"{'Entity':<12} {'QID':<14} {'Conf':>5}  {'Label':<30} {'Time':>6}")
    print("-" * 90)
    for r in results:
        label = (r.label[:28] + "..") if len(r.label) > 30 else r.label
        print(f"{r.entity:<12} {r.qid:<14} {r.confidence:>5.2f}  {label:<30} {r.elapsed_s:>5.1f}s")
    print("-" * 90)

    total = sum(r.elapsed_s for r in results)
    linked = sum(1 for r in results if r.qid not in ("NONE", "ERROR", ""))
    print(f"Linked: {linked}/{len(results)} | Total time: {total:.1f}s | "
          f"Avg: {total / len(results):.1f}s per entity\n")

    # Show reasoning
    print("REASONING:")
    print("-" * 90)
    for r in results:
        print(f"  {r.entity:<12} {r.reasoning}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
