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

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path


# Global counter for truncation events across the pipeline run
truncation_count = 0


# =============================================================================
# SQLite Triple Cache
# =============================================================================

_CACHE_DIR = Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)
_CACHE_PATH = _CACHE_DIR / "triple_cache.db"


def _get_cache_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_CACHE_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS triple_cache (
        message_uuid TEXT PRIMARY KEY,
        triples_json TEXT NOT NULL,
        text_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    return conn


def get_cached_triples(message_uuid: str) -> list[dict] | None:
    """Return cached triples for a message UUID, or None on cache miss."""
    conn = _get_cache_conn()
    row = conn.execute(
        "SELECT triples_json FROM triple_cache WHERE message_uuid = ?",
        (message_uuid,),
    ).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def cache_triples(message_uuid: str, triples: list[dict], text: str) -> None:
    """Store extracted triples in the cache, keyed by message UUID."""
    conn = _get_cache_conn()
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    conn.execute(
        "INSERT OR REPLACE INTO triple_cache (message_uuid, triples_json, text_hash) VALUES (?, ?, ?)",
        (message_uuid, json.dumps(triples), text_hash),
    )
    conn.commit()
    conn.close()


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
    "[object object]", "object object",
}

# Known-good short terms that should always pass validation.
# These are well-known tech abbreviations that might otherwise be caught
# by the 2-char or other filters.
WHITELISTED_ENTITIES = {
    "ai", "ui", "db", "os", "ip", "ci", "cd", "js", "ts", "go", "ml",
    "api", "sdk", "sql", "css", "jwt", "ssh", "ssl", "tls", "dns", "cdn",
    "gpu", "cpu", "ram", "ssd", "hdd", "cli", "gui", "ide", "nlp", "llm",
    "rag", "rdf", "owl", "uri", "url", "xml", "csv", "pdf", "svg", "png",
    "gif", "npm", "pip", "git", "aws", "gcp", "mcp", "rpa",
}

# File extensions commonly seen in code paths and filenames
_FILE_EXTENSIONS = (
    r"ts|tsx|js|jsx|py|json|yaml|yml|css|html|md|sql|sh|env|db|sqlite|txt|"
    r"png|csv|jsonl|xml|toml|lock|cfg|ini|log|ttl|rdf|sparql|ipynb|whl|gz|"
    r"tar|zip|jpg|jpeg|gif|svg|wasm|map|d\.ts|mjs|cjs"
)

# Precompiled regex patterns for performance (used in is_valid_entity)
_RE_FILENAME = re.compile(rf"^[\w@./-][\w./-]*\.({_FILE_EXTENSIONS})$", re.IGNORECASE)
_RE_ICD_SHORT = re.compile(r"^[a-z]\d{2,}(\.\d+)?$", re.IGNORECASE)
_RE_ICD_UNDERSCORE = re.compile(r"^[a-z]+_\d{3}_\d{3}$", re.IGNORECASE)
_RE_PROTOCOL_CODE = re.compile(r"^[a-z]+_\d+$", re.IGNORECASE)
_RE_SNAKE_CASE_3SEG = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+){2,}$")
_RE_NUMERIC_PREFIX = re.compile(r"^\d+\s")
_RE_VERSION_DECIMAL = re.compile(r"^\d+\.\d+")
_RE_BRACKETS = re.compile(r"[\[\]]")
_RE_PARENS = re.compile(r"[()]")
_RE_CSS_DIMENSION = re.compile(r"\d+(px|vh|vw|em|rem|pt|%)\b", re.IGNORECASE)


def is_valid_entity(name: str) -> bool:
    """Return False for entities that are noise rather than real technical concepts.

    Filters (in order):
    - Empty / single char
    - Stopwords
    - Whitelist bypass for known-good short terms
    - Paths, special-char prefixes, filenames
    - Medical/ICD codes, protocol codes, snake_case identifiers
    - Numeric prefixes, versions, dimensions, percentages
    - Code syntax fragments (brackets, parens, npm scopes)
    - 2-char ambiguous noise
    - 4+ word phrases
    """
    if not name or len(name) <= 1:
        return False
    if name in STOPWORDS:
        return False

    # --- Whitelist: known-good short terms skip all other filters ---
    if name in WHITELISTED_ENTITIES:
        return True

    # --- Starts with special characters (hex colors, issue refs, npm scopes,
    #     pricing, globs, dotfiles, CLI flags, ports, DOM selectors) ---
    if name[0] in ("#", "@", "$", "*", "!", "~", ".", ":", "-"):
        return False

    # Paths or shell commands
    if name.startswith("/") or "\\" in name:
        return False

    # --- Filenames with extensions (e.g., __init__.py, config.json, auth-utils.ts) ---
    if _RE_FILENAME.match(name):
        return False

    # --- Medical/ICD codes (e.g., a021, j458, k25.0, e_148) ---
    if _RE_ICD_SHORT.match(name):
        return False
    # ICD pattern with double underscore segments (e.g., ansied_022_001)
    if _RE_ICD_UNDERSCORE.match(name):
        return False

    # --- Internal protocol codes (e.g., cefaleia_007, coloproc_015, dengue_008) ---
    if _RE_PROTOCOL_CODE.match(name):
        return False

    # --- snake_case code identifiers with 3+ segments (e.g., anthropic_api_key) ---
    if _RE_SNAKE_CASE_3SEG.match(name):
        return False

    # --- Numeric-prefixed phrases (e.g., "0 bytes data", "1 llm call") ---
    if _RE_NUMERIC_PREFIX.match(name):
        return False

    # --- Version/decimal strings (e.g., "0.3", "0.75 confidence", "5.0.0") ---
    if _RE_VERSION_DECIMAL.match(name):
        return False

    # Dimension strings like "1400px", "800px+ width"
    if re.match(r"^\d+px", name):
        return False

    # Pure numbers
    if re.match(r"^\d+$", name):
        return False
    # IP addresses (e.g., 10.158.0.38, 192.168.1.1)
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", name):
        return False
    # Duration/measurement strings (e.g., "120 seconds", "120s", "500ms", "10mb", "50 mb limit")
    if re.match(r"^\d+\s*(seconds?|minutes?|hours?|days?|ms|s|m|h|kb|mb|gb|tb)\b", name, re.IGNORECASE):
        return False
    # Hex strings / git hashes (e.g., "7f9ef80", "81b9518")
    if re.match(r"^[0-9a-f]{6,}$", name, re.IGNORECASE):
        return False
    # Quantity phrases (e.g., "80 tests", "3 files", "10 endpoints")
    if re.match(r"^\d+\s+\w+s$", name):
        return False
    # Ordinal phrases (e.g., "7th character extensions")
    if re.match(r"^\d+(st|nd|rd|th)\b", name, re.IGNORECASE):
        return False
    # Fraction/ratio strings (e.g., "8/8h", "3/4")
    if re.match(r"^\d+/\d+", name):
        return False

    # --- CSS dimensions in phrases (e.g., "100vh", "height 280px", "max height 200px") ---
    if _RE_CSS_DIMENSION.search(name):
        return False

    # --- Percentage values (e.g., "100%", "50% discount") ---
    if "%" in name:
        return False

    # --- Code syntax fragments (e.g., "[]", "candidates[0]", "[object object]") ---
    if _RE_BRACKETS.search(name):
        return False

    # --- Function calls (e.g., "_init_vertex_credentials()", "express.json()") ---
    if _RE_PARENS.search(name):
        return False

    # --- npm scoped packages (e.g., "@radix-ui/react-dialog") ---
    # (Already caught by special-char prefix check for '@', but kept for clarity)

    # --- Two-char ambiguous noise (e.g., "aa", "bp", "ct", "df") ---
    # Well-known 2-char terms are in WHITELISTED_ENTITIES and already returned True above
    if len(name) == 2:
        return False

    # Reject phrases with 4+ words — entities should be 1-3 words
    if len(name.split()) > 3:
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
7. Entity names MUST be 1-3 words maximum. Use the most common/recognized name for the technology, tool, or concept. NEVER use full phrases or descriptions as entity names.
8. Extract AT MOST 10 triples per message. If you identify more than 10 relationships, return only the top 10 most important ones. Prioritize relationships that capture architectural decisions, technology choices, and integration patterns over trivial implementation details.
   - GOOD entities: "neo4j", "python", "claude agent sdk", "urinary tract infection"
   - BAD entities: "notification when claude finishes responding", "follow-up if no improvement in 48h", "migration from npm to native"
   - If you can't name it in 1-3 words, it's not an entity — it's a description. Skip it.
8. Use "relatedTo" ONLY as a last resort when NO other predicate fits. Always prefer a specific predicate. Ask yourself: does X use Y? depend on Y? enable Y? integrate with Y? serve as Y? If any specific predicate applies, use it instead of relatedTo.

PREDICATE VOCABULARY:
{vocab_lines}

PREDICATE SELECTION GUIDE (to avoid overusing "relatedTo"):
- If X connects to or works with external system Y → use "integratesWith" (not relatedTo)
- If X is a kind/type/instance of category Y → use "isTypeOf" (not relatedTo)
- If X needs or depends on Y to function → use "requires" or "dependsOn" (not relatedTo)
- If X makes Y possible or supports Y → use "enables" (not relatedTo)
- If X can substitute for Y → use "alternativeTo" (not relatedTo)
- If X employs or leverages Y → use "uses" (not relatedTo)
- If X generates or creates Y → use "produces" (not relatedTo)
- If X handles or transforms Y → use "configures" or "produces" (not relatedTo)

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

WRONG vs CORRECT (do NOT use relatedTo when a specific predicate fits):

Input: "The MCP adapter translates database queries into MCP-formatted requests"
WRONG:  [{{"subject":"mcp adapter","predicate":"relatedTo","object":"db query"}}]
CORRECT: [{{"subject":"mcp adapter","predicate":"produces","object":"mcp-formatted request"}},{{"subject":"mcp adapter","predicate":"integratesWith","object":"database"}}]

Input: "ProbLog is a probabilistic logic programming language based on Prolog"
WRONG:  [{{"subject":"problog","predicate":"relatedTo","object":"prolog"}}]
CORRECT: [{{"subject":"problog","predicate":"isTypeOf","object":"probabilistic logic programming language"}},{{"subject":"problog","predicate":"extends","object":"prolog"}}]

Input: "Tunnel architecture provides an alternative to reverse proxy for exposing services"
WRONG:  [{{"subject":"tunnel architecture","predicate":"relatedTo","object":"reverse proxy"}}]
CORRECT: [{{"subject":"tunnel architecture","predicate":"alternativeTo","object":"reverse proxy"}},{{"subject":"tunnel architecture","predicate":"enables","object":"exposing services"}}]

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
# Truncation Detection & Salvage
# =============================================================================

def _is_truncated(raw: str) -> bool:
    """Detect if the LLM response was truncated mid-JSON.

    Heuristics:
    - Contains '[' but no matching ']'
    - Ends mid-string or mid-object (trailing quote, comma, colon, open brace)
    - Bracket counting shows unclosed structures
    """
    stripped = raw.strip()
    if not stripped:
        return False

    # Has opening bracket but no closing bracket
    if "[" in stripped and "]" not in stripped:
        return True

    # Count unmatched brackets/braces
    open_brackets = stripped.count("[") - stripped.count("]")
    open_braces = stripped.count("{") - stripped.count("}")
    if open_brackets > 0 or open_braces > 0:
        return True

    # Ends with characters that suggest mid-JSON truncation
    if stripped[-1] in (",", ":", '"', "{"):
        return True

    return False


def _salvage_truncated_json(raw: str) -> list | None:
    """Try to salvage complete triple objects from truncated JSON.

    Strategy: find all complete {"subject":...,"predicate":...,"object":...} objects
    that appear before the truncation point.
    """
    # Find all complete JSON objects with the triple pattern
    pattern = r'\{[^{}]*"subject"\s*:\s*"[^"]*"\s*,\s*"predicate"\s*:\s*"[^"]*"\s*,\s*"object"\s*:\s*"[^"]*"[^{}]*\}'
    matches = re.findall(pattern, raw, re.DOTALL)
    if not matches:
        return None

    salvaged = []
    for m in matches:
        try:
            obj = json.loads(m)
            salvaged.append(obj)
        except json.JSONDecodeError:
            continue

    return salvaged if salvaged else None


# =============================================================================
# Extraction
# =============================================================================

def _parse_triples_response(raw: str) -> list[dict] | None:
    """Parse raw LLM response text into a list of triple dicts.

    Returns None if parsing fails entirely. If the response is truncated,
    attempts to salvage any complete triple objects before the truncation point.
    """
    global truncation_count

    truncated = _is_truncated(raw)
    parsed = None

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
                pass

        # If still no parse and truncated, try salvaging complete objects
        if parsed is None and truncated:
            truncation_count += 1
            print(f"[triple_extraction] Truncated response detected (total: {truncation_count}), attempting salvage: ...{raw[-80:]}", file=sys.stderr)
            parsed = _salvage_truncated_json(raw)
            if parsed:
                print(f"[triple_extraction] Salvaged {len(parsed)} complete triples from truncated response", file=sys.stderr)

        if parsed is None:
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

    # Enforce max 10 triples per message — keep the first 10 (LLM is instructed
    # to prioritize the most important relationships, so order matters)
    MAX_TRIPLES_PER_MESSAGE = 10
    if len(triples) > MAX_TRIPLES_PER_MESSAGE:
        triples = triples[:MAX_TRIPLES_PER_MESSAGE]

    return triples


MAX_RETRIES = 2
# Input character limits: first attempt and retry
_INITIAL_MAX_CHARS = 1500
_RETRY_MAX_CHARS = 1000
_TRUNCATION_RETRY_MAX_CHARS = 800


def extract_triples_gemini(model, text: str) -> list[dict]:
    """Extract knowledge triples from text using a Gemini model.

    Handles three failure modes:
    1. API errors — retry with shorter input
    2. Truncated JSON — salvage complete triples, then retry with shorter input
    3. Unparseable response — retry with shorter input

    Args:
        model: A vertexai GenerativeModel instance (from vertex_ai.get_gemini_model).
        text: The text to extract triples from.

    Returns:
        A list of normalized triple dicts, each with 'subject', 'predicate', 'object'.
    """
    if not text or len(text.strip()) < 30:
        return []

    max_chars = _INITIAL_MAX_CHARS

    for attempt in range(1 + MAX_RETRIES):
        input_text = text[:max_chars]
        prompt = build_extraction_prompt(input_text)

        try:
            response = model.generate_content(prompt)
            raw = response.text.strip()
        except Exception as e:
            print(f"[triple_extraction] API error (attempt {attempt + 1}): {e}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                max_chars = _RETRY_MAX_CHARS
                continue
            return []

        # Check for truncation before parsing
        was_truncated = _is_truncated(raw)

        triples = _parse_triples_response(raw)
        if triples is not None:
            if was_truncated:
                print(f"[triple_extraction] Recovered {len(triples)} triples from truncated response (attempt {attempt + 1})", file=sys.stderr)
            return triples

        # Parse failed — determine retry strategy
        if attempt < MAX_RETRIES:
            if was_truncated:
                # Truncation: use aggressively shorter input so output fits in token budget
                max_chars = _TRUNCATION_RETRY_MAX_CHARS
                print(f"[triple_extraction] Truncated JSON (attempt {attempt + 1}), retrying with {max_chars} chars: ...{raw[-80:]}", file=sys.stderr)
            else:
                max_chars = _RETRY_MAX_CHARS
                print(f"[triple_extraction] JSON parse failed (attempt {attempt + 1}), retrying with shorter input: {raw[:100]}", file=sys.stderr)
        else:
            print(f"[triple_extraction] JSON parse failed after {attempt + 1} attempts: {raw[:200]}", file=sys.stderr)

    return []


def get_truncation_count() -> int:
    """Return the total number of truncation events detected during this run."""
    return truncation_count


def reset_truncation_count() -> None:
    """Reset the truncation counter (e.g., at the start of a new pipeline run)."""
    global truncation_count
    truncation_count = 0
