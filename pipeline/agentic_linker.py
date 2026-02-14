#!/usr/bin/env python3
"""
LLM-based Wikidata entity disambiguation.

Given an entity label + source context, uses Gemini 2.5 Flash Lite
to pick the best Wikidata QID from candidates returned by wbsearchentities.

Usage:
    python -m pipeline.agentic_linker
"""

import json
import sys
import time
from typing import Optional

import requests
from vertexai.generative_models import GenerativeModel, GenerationConfig

from pipeline.vertex_ai import init_vertex

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": "DevKG-AgenticLinker/1.0 (https://github.com/devkg) Python/requests"
}

DISAMBIGUATION_PROMPT = """\
You are a Wikidata entity disambiguation expert for a developer knowledge graph.

Given an entity mention and the sentence where it appeared, pick the Wikidata
candidate that best matches the intended meaning. Prefer software, programming,
and technology interpretations over general/scientific/historical ones.

Entity: "{entity}"
Source context: "{context}"

Candidates:
{candidates}

Rules:
- Pick the QID whose description best matches how the entity is used in the source context.
- If NO candidate is a reasonable match, return qid="none".
- Confidence: 0.9-1.0 = exact match, 0.7-0.8 = good match, 0.5-0.6 = weak match, <0.5 = none.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "qid": {"type": "string", "description": "Wikidata QID (e.g. Q28865) or 'none'"},
        "confidence": {"type": "number", "description": "0.0 to 1.0"},
    },
    "required": ["qid", "confidence"],
}

# ---------------------------------------------------------------------------
# Wikidata API
# ---------------------------------------------------------------------------


def search_candidates(entity: str, limit: int = 5) -> list[dict]:
    """Query wbsearchentities for candidate QIDs."""
    time.sleep(1)  # rate limit
    resp = requests.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbsearchentities",
            "search": entity,
            "language": "en",
            "format": "json",
            "limit": limit,
        },
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return [
        {"qid": r["id"], "label": r.get("label", ""), "description": r.get("description", "")}
        for r in resp.json().get("search", [])
    ]


# ---------------------------------------------------------------------------
# LLM disambiguation
# ---------------------------------------------------------------------------


def disambiguate(
    entity: str,
    context: str,
    candidates: list[dict],
    model: GenerativeModel,
) -> dict:
    """Ask Gemini to pick the best candidate given source context."""
    if not candidates:
        return {"qid": "none", "confidence": 0.0}

    cand_text = "\n".join(
        f"  {c['qid']}: {c['label']} — {c['description']}" for c in candidates
    )
    prompt = DISAMBIGUATION_PROMPT.format(
        entity=entity, context=context, candidates=cand_text
    )

    resp = model.generate_content(prompt)
    try:
        result = json.loads(resp.text)
        return {"qid": result.get("qid", "none"), "confidence": result.get("confidence", 0.0)}
    except (json.JSONDecodeError, AttributeError):
        print(f"  [warn] bad LLM response: {resp.text}", file=sys.stderr)
        return {"qid": "none", "confidence": 0.0}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def link_entity(entity: str, context: str, model: GenerativeModel) -> dict:
    """Full pipeline: search Wikidata -> LLM disambiguate -> return result."""
    candidates = search_candidates(entity)
    result = disambiguate(entity, context, candidates, model)
    # Attach description from candidates for display
    if result["qid"] != "none":
        for c in candidates:
            if c["qid"] == result["qid"]:
                result["description"] = c["description"]
                break
    return result


def main():
    init_vertex()
    model = GenerativeModel(
        "gemini-2.5-flash-lite",
        generation_config=GenerationConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.1,
            max_output_tokens=256,
        ),
    )

    test_cases = [
        ("python", "dedicated backend service builtWith Go, Node.js, Python"),
        ("backend", "dedicated backend service deployedOn container"),
        ("agent", "Claude agent SDK for building autonomous AI agents"),
        ("apis", "apis enable data consumption from external services"),
        ("neo4j", "Neo4j graph database for knowledge graph storage"),
    ]

    print(f"{'='*70}")
    print("Agentic Wikidata Entity Disambiguation (Gemini 2.5 Flash Lite)")
    print(f"{'='*70}\n")

    for entity, context in test_cases:
        print(f"Entity:  \"{entity}\"")
        print(f"Context: \"{context}\"")

        candidates = search_candidates(entity)
        print(f"Candidates ({len(candidates)}):")
        for c in candidates:
            print(f"  {c['qid']:>12}: {c['label']} — {c['description']}")

        result = disambiguate(entity, context, candidates, model)
        desc = ""
        if result["qid"] != "none":
            for c in candidates:
                if c["qid"] == result["qid"]:
                    desc = c["description"]
                    break

        status = "LINKED" if result["qid"] != "none" else "SKIPPED"
        print(f"Result:  [{status}] {result['qid']} (confidence={result['confidence']}) {desc}")
        print(f"{'-'*70}\n")


if __name__ == "__main__":
    main()
