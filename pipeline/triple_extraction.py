"""
Triple extraction from text using an LLM with a curated predicate vocabulary.

This module builds an ontologist prompt and parses the LLM response into
normalized (subject, predicate, object) triples aligned with the devkg ontology.

Usage:
    from pipeline.vertex_ai import get_gemini_model
    from pipeline.triple_extraction import extract_triples_gemini

    model = get_gemini_model()
    triples = extract_triples_gemini(model, "Neo4j stores data as a property graph")
    # [{"subject": "neo4j", "predicate": "isTypeOf", "object": "property graph"}]
"""

import json
import re
import sys


# =============================================================================
# Curated Predicate Vocabulary (mirrors devkg.ttl)
# =============================================================================

PREDICATE_VOCABULARY = {
    "uses": "X uses technology/tool Y",
    "dependsOn": "X depends on Y",
    "enables": "X enables capability Y",
    "isPartOf": "X is part of larger Y",
    "hasPart": "X has component Y",
    "implements": "X implements pattern/spec Y",
    "extends": "X extends/specializes Y",
    "alternativeTo": "X is alternative to Y",
    "solves": "X solves problem Y",
    "produces": "X produces output Y",
    "configures": "X configures Y",
    "composesWith": "X composes/combines with Y",
    "provides": "X provides capability Y",
    "requires": "X requires Y",
    "isTypeOf": "X is a type/kind of Y",
    "builtWith": "X is built with Y",
    "deployedOn": "X is deployed on platform Y",
    "storesIn": "X stores data in Y",
    "queriedWith": "X is queried using Y",
    "integratesWith": "X integrates with Y",
    "broader": "X is a broader concept than Y",
    "narrower": "X is a narrower concept than Y",
    "relatedTo": "X is related to Y (generic)",
    "servesAs": "X serves as / acts as Y",
}

_PREDICATE_SET = set(PREDICATE_VOCABULARY.keys())


# =============================================================================
# Stopword Filter
# =============================================================================

STOPWORDS = {
    "command name", "exit", "yes", "no", "ok", "the", "it", "this",
    "that", "none", "null", "undefined", "true", "false", "n/a",
}


def is_valid_entity(name: str) -> bool:
    """Return False for entities that are noise rather than real technical concepts."""
    if not name or len(name) <= 1:
        return False
    if name in STOPWORDS:
        return False
    # Paths or shell commands
    if name.startswith("/") or "\\" in name:
        return False
    # Dimension strings like "1400px", "800px+ width"
    if re.match(r"^\d+px", name):
        return False
    # Pure numbers
    if re.match(r"^\d+$", name):
        return False
    return True


# =============================================================================
# Prompt Builder
# =============================================================================

def build_extraction_prompt(text: str) -> str:
    """Build the full ontologist prompt for triple extraction."""
    vocab_lines = "\n".join(
        f"  {pred}: {desc}" for pred, desc in PREDICATE_VOCABULARY.items()
    )

    return f"""You are an expert ontologist specializing in developer knowledge graphs. Your task is to extract factual technical relationships from the text below.

RULES:
1. Extract ONLY factual technical relationships stated or strongly implied in the text.
2. Use ONLY predicates from the vocabulary below — do not invent new predicates.
3. Normalize entity names to lowercase.
4. Skip messages about formatting, UI layout, greetings, pleasantries, or tool invocation mechanics.
5. Return [] for messages with no extractable technical knowledge.
6. Each triple must have "subject", "predicate", and "object" string fields.
7. Keep entity names concise (1-4 words typically). Use the most common/recognized name.

PREDICATE VOCABULARY:
{vocab_lines}

EXAMPLES:

Input: "Prolog enables symbolic reasoning in neurosymbolic AI architectures"
Output: [{{"subject":"prolog","predicate":"enables","object":"symbolic reasoning"}},{{"subject":"neurosymbolic ai","predicate":"composesWith","object":"prolog"}}]

Input: "We chose Neo4j over PostgreSQL for the knowledge graph because it handles graph traversal natively"
Output: [{{"subject":"neo4j","predicate":"solves","object":"graph traversal"}},{{"subject":"neo4j","predicate":"alternativeTo","object":"postgresql"}},{{"subject":"knowledge graph","predicate":"storesIn","object":"neo4j"}}]

Input: "Docker Compose configures the Fuseki triple store running on port 3030"
Output: [{{"subject":"docker compose","predicate":"configures","object":"fuseki"}},{{"subject":"fuseki","predicate":"isTypeOf","object":"triple store"}}]

Input: "Let me adjust the layout to be wider with more spacing between elements"
Output: []

Input: "The Claude Agent SDK uses the Model Context Protocol to connect to external tools"
Output: [{{"subject":"claude agent sdk","predicate":"uses","object":"model context protocol"}},{{"subject":"model context protocol","predicate":"enables","object":"external tool integration"}}]

Now extract triples from this text:

{text}"""


# =============================================================================
# Normalization
# =============================================================================

def normalize_entity(name: str) -> str:
    """Normalize an entity name: lowercase, strip, collapse spaces, remove trailing punctuation."""
    name = name.strip().lower()
    name = re.sub(r"\s+", " ", name)
    name = name.rstrip(".,;:")
    return name


def normalize_predicate(pred: str) -> str:
    """Normalize a predicate to match PREDICATE_VOCABULARY keys.

    Tries exact match first, then converts common formats (snake_case,
    space-separated, hyphenated) to camelCase. Falls back to 'relatedTo'.
    """
    pred = pred.strip()

    # Exact match
    if pred in _PREDICATE_SET:
        return pred

    # Try converting various formats to camelCase
    # Split on underscores, spaces, or hyphens
    parts = re.split(r"[_\s-]+", pred.lower())
    if len(parts) > 1:
        camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
        if camel in _PREDICATE_SET:
            return camel

    # Case-insensitive search as last resort
    pred_lower = pred.lower()
    for key in _PREDICATE_SET:
        if key.lower() == pred_lower:
            return key

    return "relatedTo"


def normalize_triple(triple: dict) -> dict:
    """Apply normalization to all parts of a triple."""
    return {
        "subject": normalize_entity(triple["subject"]),
        "predicate": normalize_predicate(triple["predicate"]),
        "object": normalize_entity(triple["object"]),
    }


# =============================================================================
# Extraction
# =============================================================================

def _parse_triples_response(raw: str) -> list[dict] | None:
    """Parse raw LLM response text into a list of triple dicts.

    Returns None if parsing fails entirely.
    """
    # Try direct JSON parse
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON array in response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    # Handle dict wrapper (e.g., {"triples": [...]})
    if isinstance(parsed, dict):
        for key in parsed:
            if isinstance(parsed[key], list):
                parsed = parsed[key]
                break
        else:
            return None

    if not isinstance(parsed, list):
        return None

    # Validate and normalize
    triples = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        if not all(
            k in item and isinstance(item[k], str)
            for k in ("subject", "predicate", "object")
        ):
            continue
        normalized = normalize_triple(item)
        if (normalized["subject"] and normalized["predicate"] and normalized["object"]
                and is_valid_entity(normalized["subject"])
                and is_valid_entity(normalized["object"])):
            triples.append(normalized)

    return triples


MAX_RETRIES = 2


def extract_triples_gemini(model, text: str) -> list[dict]:
    """Extract knowledge triples from text using a Gemini model.

    Args:
        model: A vertexai GenerativeModel instance (from vertex_ai.get_gemini_model).
        text: The text to extract triples from.

    Returns:
        A list of normalized triple dicts, each with 'subject', 'predicate', 'object'.
    """
    if not text or len(text.strip()) < 30:
        return []

    max_chars = 1500

    for attempt in range(1 + MAX_RETRIES):
        truncated = text[:max_chars]
        prompt = build_extraction_prompt(truncated)

        try:
            response = model.generate_content(prompt)
            raw = response.text.strip()
        except Exception as e:
            print(f"[triple_extraction] API error (attempt {attempt + 1}): {e}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                max_chars = 1000  # shorter input on retry
                continue
            return []

        triples = _parse_triples_response(raw)
        if triples is not None:
            return triples

        # Parse failed — retry with shorter input
        if attempt < MAX_RETRIES:
            print(f"[triple_extraction] JSON parse failed (attempt {attempt + 1}), retrying with shorter input: {raw[:100]}", file=sys.stderr)
            max_chars = 1000
        else:
            print(f"[triple_extraction] JSON parse failed after {attempt + 1} attempts: {raw[:200]}", file=sys.stderr)

    return []
