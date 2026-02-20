# Contributing to session-graph

Thank you for your interest in contributing. The most impactful way to contribute is **adding a new platform parser** -- every new parser unlocks an entire category of AI sessions for knowledge graph extraction.

## Adding a New Platform Parser

This is the primary contribution vector. Parsers for Cursor, ChatGPT, VS Code Copilot, Windsurf, and Aider are all wanted.

### Parser Interface

Every parser is a Python module in `pipeline/` that follows the same pattern. Look at any existing parser (`jsonl_to_rdf.py`, `deepseek_to_rdf.py`, `grok_to_rdf.py`, `warp_to_rdf.py`) as a reference.

Your parser must:

1. **Define a `build_graph()` function** that returns an `rdflib.Graph`:

```python
def build_graph(input_path: str, skip_extraction: bool = False, model=None) -> Graph:
    """Parse source data and build an RDF graph."""
    g = create_graph()

    # 1. Read the source format (JSON, SQLite, Markdown, etc.)
    # 2. Create session and message nodes using common.py helpers
    # 3. For each assistant message, call extract_triples_gemini()
    # 4. Return the graph

    return g
```

2. **Define a `main()` function** with standard CLI arguments:

```python
def main():
    parser = argparse.ArgumentParser(description="Convert <Platform> to RDF Turtle")
    parser.add_argument("input", help="Path to input file")
    parser.add_argument("output", help="Path to output Turtle file")
    parser.add_argument("--skip-extraction", action="store_true")
    parser.add_argument("--model", help="LLM model name override")
    # Add platform-specific args (e.g., --conversation, --db-path)
    args = parser.parse_args()
    # ...
```

3. **Use shared helpers from `pipeline/common.py`**:

```python
from pipeline.common import (
    PROV, SIOC, DEVKG, DATA,
    slug, create_graph, create_session_node, create_developer_node,
    create_model_node, create_message_node, add_triples_to_graph,
)
from pipeline.triple_extraction import extract_triples_gemini
```

4. **Be runnable as a module**: `python -m pipeline.your_parser input output.ttl`

### Key Helpers (from `common.py`)

| Function | Purpose |
|----------|---------|
| `create_graph()` | Creates an `rdflib.Graph` with all namespaces bound |
| `create_session_node(g, session_id, platform, ...)` | Creates a PROV Activity + SIOC Forum node |
| `create_message_node(g, msg_id, role, session_uri, ...)` | Creates a SIOC Post + PROV Entity node |
| `create_developer_node(g, name)` | Creates a PROV Agent for the human user |
| `create_model_node(g, model_id)` | Creates a PROV Agent for the AI model |
| `add_triples_to_graph(g, msg_uri, triples, session_uri)` | Adds extracted `(s,p,o)` triples with provenance |
| `slug(text)` | Creates URI-safe slugs |

### What Your Parser Should Produce

The output RDF must follow the devkg ontology (`ontology/devkg.ttl`):

- **Sessions** are typed as both `prov:Activity` and `sioc:Forum`
- **Messages** are typed as both `sioc:Post` and `prov:Entity`
- **Platform** is set via `devkg:platform` (e.g., `"cursor"`, `"chatgpt"`, `"copilot"`)
- **Provenance**: every message links to its session, every triple links to its source message
- **Triple extraction**: call `extract_triples_gemini(model, text)` on assistant message text only

### Checklist for a New Parser

- [ ] Module in `pipeline/` named `<platform>_to_rdf.py`
- [ ] Uses `common.py` helpers (do not duplicate RDF construction logic)
- [ ] Sets `platform` correctly in `create_session_node()`
- [ ] Only extracts triples from assistant messages
- [ ] Handles `--skip-extraction` flag
- [ ] Includes docstring with usage examples
- [ ] Tested on real data from the platform

### Where to Find Source Data

| Platform | Data Location | Format |
|----------|--------------|--------|
| Cursor | `~/.cursor/...` or `~/.cursor-server/...` SQLite | SQLite with JSON blobs |
| VS Code Copilot | `Chat: Export Session...` (Ctrl+Shift+P) | JSON |
| ChatGPT | Settings > Data Controls > Export | JSON zip |
| Windsurf | `~/.windsurf/...` | SQLite (similar to Cursor) |
| Aider | `.aider.chat.history.md` in project root | Markdown |

## Adding a New LLM Provider

The project uses `pipeline/vertex_ai.py` for LLM access. To add a new provider:

1. Implement a wrapper that exposes the same interface as `get_gemini_model()` -- the returned object must support `generate_content(prompt)` returning a response with a `.text` attribute.
2. Update `triple_extraction.py` if the new provider needs different prompt formatting.
3. Wire it into the CLI `--model` argument in each parser's `main()`.

## Code Style

- **Python 3.11+** with type hints
- **rdflib** for all RDF construction -- do not generate Turtle strings manually
- Use `pipeline/common.py` for shared namespace constants and node builders
- Print progress/diagnostics to `stderr` (`print(..., file=sys.stderr)`)
- Output only the final `.ttl` to `stdout` or to the specified output file
- Keep imports from `pipeline.*` at the top, use relative paths via module syntax (`python -m pipeline.xxx`)

## Testing

There is no formal test suite yet. To validate your parser:

1. **Structure-only test** (no API calls needed):
   ```bash
   python -m pipeline.your_parser input output.ttl --skip-extraction
   ```
   Verify the output `.ttl` is valid Turtle and contains the expected session/message structure.

2. **Full extraction test** (requires Vertex AI credentials):
   ```bash
   python -m pipeline.your_parser input output.ttl --model gemini-2.5-flash
   ```
   Check that knowledge triples appear in the output.

3. **Load into Fuseki** and run sample queries from `pipeline/sample_queries.sparql` to verify provenance links work.

4. **Validate RDF**: Use `rapper -i turtle output.ttl` or load into any RDF tool to check for syntax errors.

## Submitting a Pull Request

1. Fork the repository and create a feature branch
2. Keep changes focused -- one parser or feature per PR
3. Include a brief description of the source data format and where users can obtain their export
4. If adding a parser, include a small anonymized test fixture if possible
5. Run your parser on real data and verify the output loads into Fuseki without errors

## Reporting Issues

Open an issue on GitHub with:

- What you were trying to do
- The command you ran
- The error output (redact any file paths or personal data)
- Your Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
