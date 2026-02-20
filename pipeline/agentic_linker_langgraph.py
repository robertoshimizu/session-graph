#!/usr/bin/env python3
"""
ReAct-style Wikidata entity linker using LangChain + LangGraph.

Uses an LLM agent to search Wikidata, reason about ambiguous results,
and return the best QID for developer entities.

Supports multiple LLM providers via environment variables:
    - GEMINI_API_KEY   -> Google Generative AI (default)
    - OPENAI_API_KEY   -> OpenAI
    - ANTHROPIC_API_KEY -> Anthropic
    - Ollama           -> Local Ollama (fallback)

Usage:
    python -m pipeline.agentic_linker_langgraph

Dependencies:
    pip install langchain-google-genai langgraph requests python-dotenv
"""

import os
import sys
import time
import warnings

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Suppress noisy warnings
warnings.filterwarnings("ignore", message=".*GOOGLE_API_KEY.*")
warnings.filterwarnings("ignore", message=".*GEMINI_API_KEY.*")


# ---------------------------------------------------------------------------
# Wikidata search tool
# ---------------------------------------------------------------------------

HEADERS = {
    'User-Agent': 'DevKG-AgenticLinker/1.0 (https://github.com/devkg) Python/requests'
}


@tool
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
    url = "https://www.wikidata.org/w/api.php"
    params = {
        'action': 'wbsearchentities',
        'search': query,
        'language': 'en',
        'format': 'json',
        'limit': 5,
        'type': 'item',
    }

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return {"error": str(e), "results": []}

    candidates = []
    for item in data.get('search', []):
        candidates.append({
            "qid": item.get("id", ""),
            "label": item.get("label", ""),
            "description": item.get("description", ""),
        })

    return {"query": query, "results": candidates}


# ---------------------------------------------------------------------------
# Structured response model
# ---------------------------------------------------------------------------

class WikidataMatch(BaseModel):
    """Result of a Wikidata entity linking attempt."""
    qid: str = Field(description='Wikidata QID (e.g. "Q28865") or "none" if no match found')
    confidence: float = Field(description="Confidence score from 0.0 to 1.0")
    label: str = Field(description="Entity label from Wikidata, or the original entity if no match")
    description: str = Field(description="Entity description from Wikidata, or empty string")
    reasoning: str = Field(description="Brief explanation of why this match was selected or rejected")


# ---------------------------------------------------------------------------
# Agent setup
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
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
5. CRITICAL: Only return a QID that appeared in your search results. Never guess a QID from memory.
6. CRITICAL: The returned QID's label must semantically match the input entity. If the best
   search result is about something unrelated, return qid="none".
7. When you have found the best match (or determined there is none), return your answer.
"""


# Module-level singleton: reuse the same model instance across calls to avoid
# repeated initialization overhead and suppress per-instantiation warnings.
_shared_model = None


def _get_shared_model():
    """Return a shared LangChain chat model instance (created once).

    Auto-detects provider from env vars:
        GEMINI_API_KEY   -> ChatGoogleGenerativeAI
        OPENAI_API_KEY   -> ChatOpenAI
        ANTHROPIC_API_KEY -> ChatAnthropic
        (fallback)       -> ChatOllama
    """
    global _shared_model
    if _shared_model is not None:
        return _shared_model

    if os.environ.get("GEMINI_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        _shared_model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=os.environ["GEMINI_API_KEY"],
        )
        print("  Linker agent: Gemini (google-generativeai)", file=sys.stderr)
    elif os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        _shared_model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        print("  Linker agent: OpenAI (gpt-4o-mini)", file=sys.stderr)
    elif os.environ.get("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        _shared_model = ChatAnthropic(model="claude-haiku-4-5-latest", temperature=0)
        print("  Linker agent: Anthropic (claude-haiku-4-5-latest)", file=sys.stderr)
    else:
        from langchain_ollama import ChatOllama
        _shared_model = ChatOllama(model="llama3.1", temperature=0)
        print("  Linker agent: Ollama (llama3.1)", file=sys.stderr)

    return _shared_model


def create_linker_agent():
    """Create the ReAct agent for Wikidata entity linking."""
    model = _get_shared_model()
    tools = [search_wikidata]

    agent = create_react_agent(
        model=model,
        tools=tools,
        response_format=WikidataMatch,
        prompt=SYSTEM_PROMPT,
    )
    return agent


# ---------------------------------------------------------------------------
# Linking function
# ---------------------------------------------------------------------------

def link_entity(
    entity: str,
    context: str,
) -> tuple[WikidataMatch, float]:
    """Link a single entity to Wikidata using the ReAct agent.

    Reuses a shared model instance; agent state is per-invocation
    (no leakage between entities).
    Returns (WikidataMatch, elapsed_seconds).
    """
    agent = create_linker_agent()

    user_message = f"Entity: {entity}\nContext: {context}"

    start = time.time()

    result = agent.invoke(
        {"messages": [("user", user_message)]},
    )

    elapsed = time.time() - start

    # Extract structured response
    structured = result.get("structured_response")
    if structured is None:
        # Fallback: try to parse from last message
        last_msg = result["messages"][-1]
        return WikidataMatch(
            qid="none",
            confidence=0.0,
            label=entity,
            description="",
            reasoning=f"Agent did not return structured output. Last message: {last_msg.content[:200]}",
        ), elapsed

    return structured, elapsed


# ---------------------------------------------------------------------------
# Main: test cases
# ---------------------------------------------------------------------------

def main():
    test_cases = [
        ("python", "dedicated backend service builtWith Go, Node.js, Python"),
        ("backend", "dedicated backend service deployedOn container"),
        ("agent", "Claude agent SDK for building autonomous AI agents"),
        ("apis", "apis enable data consumption from external services"),
        ("neo4j", "Neo4j graph database for knowledge graph storage"),
        ("k8s", "k8s orchestrates container deployments across clusters"),
        ("js", "frontend built with js and react framework"),
    ]

    results = []

    print("\n" + "=" * 90)
    print("  Agentic Wikidata Entity Linker (LangGraph)")
    print("=" * 90 + "\n")

    for entity, context in test_cases:
        print(f"  Linking: '{entity}' ...", end="", flush=True)
        try:
            match, elapsed = link_entity(entity, context)
            results.append((entity, context, match, elapsed))
            print(f" -> {match.qid} ({elapsed:.1f}s)")
        except Exception as e:
            print(f" ERROR: {e}")
            results.append((
                entity, context,
                WikidataMatch(
                    qid="ERROR",
                    confidence=0.0,
                    label=entity,
                    description=str(e),
                    reasoning="",
                ),
                0.0,
            ))

    # Print results table
    print("\n" + "=" * 90)
    print(f"{'Entity':<12} {'QID':<14} {'Conf':>5}  {'Label':<30} {'Time':>6}")
    print("-" * 90)
    for _, _, match, elapsed in results:
        label = (match.label[:28] + "..") if len(match.label) > 30 else match.label
        print(f"{match.label if len(match.label) <= 12 else match.label[:12]:<12} {match.qid:<14} {match.confidence:>5.2f}  {label:<30} {elapsed:>5.1f}s")
    print("-" * 90)

    total = sum(e for _, _, _, e in results)
    linked = sum(1 for _, _, m, _ in results if m.qid not in ("NONE", "ERROR", "none", "error", ""))
    print(f"Linked: {linked}/{len(results)} | Total time: {total:.1f}s | "
          f"Avg: {total / len(results):.1f}s per entity\n")

    # Show reasoning
    print("REASONING:")
    print("-" * 90)
    for entity, _, match, _ in results:
        print(f"  {entity:<12} {match.reasoning}")
    print()


if __name__ == "__main__":
    main()
