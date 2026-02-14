"""
Cognee Evaluation: Ingest Claude Code JSONL session data into Cognee's knowledge graph.

Configures Cognee to use Ollama (llama3) for LLM and nomic-embed-text for embeddings,
then ingests extracted conversation text from Claude Code session logs.
"""

import asyncio
import json
import os
import sys

# Set environment variables BEFORE importing cognee
os.environ["LLM_PROVIDER"] = "ollama"
os.environ["LLM_MODEL"] = "llama3:latest"
os.environ["LLM_ENDPOINT"] = "http://localhost:11434/v1"
os.environ["LLM_API_KEY"] = "ollama"

os.environ["EMBEDDING_PROVIDER"] = "ollama"
os.environ["EMBEDDING_MODEL"] = "nomic-embed-text:latest"
os.environ["EMBEDDING_ENDPOINT"] = "http://localhost:11434/api/embed"
os.environ["EMBEDDING_DIMENSIONS"] = "768"
os.environ["EMBEDDING_BATCH_SIZE"] = "1"  # Serialize embedding calls for local Ollama
os.environ["HUGGINGFACE_TOKENIZER"] = "nomic-ai/nomic-embed-text-v1.5"

# Disable multi-user access control (not needed for evaluation)
os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] = "false"

# Use the project's ontology if available
ONTOLOGY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "ontology", "devkg.ttl"
)
if os.path.exists(ONTOLOGY_PATH):
    os.environ["ONTOLOGY_FILE_PATH"] = os.path.abspath(ONTOLOGY_PATH)
    print(f"[config] Ontology file: {os.path.abspath(ONTOLOGY_PATH)}")

import cognee


# ---------------------------------------------------------------------------
# JSONL Parsing
# ---------------------------------------------------------------------------

JSONL_FILES = [
    os.path.expanduser(
        "~/.claude/projects/-Users-robertoshimizu-GitRepo-Hacks-claude_hacks-dev-knowledge-graph/"
        "ec11ec1e-9d4f-4694-9a7d-b8cfce8e539c.jsonl"
    ),
    os.path.expanduser(
        "~/.claude/projects/-Users-robertoshimizu-GitRepo-Hacks-ddxplus/"
        "1319ccca-549c-4109-9284-fc764131e8c7.jsonl"
    ),
]


def extract_text_from_content(content) -> str:
    """Extract plain text from a Claude message content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_name = block.get("name", "unknown")
                    tool_input = block.get("input", {})
                    # Summarize tool calls briefly
                    if isinstance(tool_input, dict):
                        summary = ", ".join(
                            f"{k}={str(v)[:80]}" for k, v in tool_input.items()
                        )
                    else:
                        summary = str(tool_input)[:200]
                    parts.append(f"[Tool: {tool_name}({summary})]")
                elif block.get("type") == "tool_result":
                    # Skip verbose tool results
                    pass
        return "\n".join(parts)
    return ""


def parse_jsonl(filepath: str) -> list[str]:
    """
    Parse a Claude Code JSONL file and extract conversation text.

    Returns a list of text chunks (one per message), prefixed with role.
    Each chunk includes a unique message index to avoid content hash collisions.
    """
    texts = []
    session_id = os.path.basename(filepath).replace(".jsonl", "")
    msg_idx = 0

    with open(filepath, "r") as f:
        for line in f:
            try:
                obj = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            msg = obj.get("message", {})
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue

            content = extract_text_from_content(msg.get("content", ""))
            if not content or len(content.strip()) < 20:
                continue

            # Strip system reminders from content
            if "<system-reminder>" in content:
                import re
                content = re.sub(
                    r"<system-reminder>.*?</system-reminder>",
                    "",
                    content,
                    flags=re.DOTALL,
                )
                content = content.strip()
                if len(content) < 20:
                    continue

            # Truncate very long messages to avoid overwhelming the LLM
            if len(content) > 3000:
                content = content[:3000] + "\n[...truncated...]"

            msg_idx += 1
            # Include msg index to ensure uniqueness for Cognee content hashing
            texts.append(
                f"[Session: {session_id[:8]}, msg {msg_idx}] [{role}]: {content}"
            )

    return texts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("Cognee Evaluation: Ingesting Claude Code Sessions")
    print("=" * 60)

    # Reset any previous Cognee data
    print("\n[1/4] Resetting Cognee state...")
    try:
        await cognee.prune.prune_data()
        await cognee.prune.prune_system(metadata=True)
    except Exception as e:
        print(f"  Prune skipped (fresh state): {e}")
    print("  Done.")

    # Parse JSONL files
    print("\n[2/4] Parsing JSONL files...")
    all_texts = []
    for filepath in JSONL_FILES:
        if not os.path.exists(filepath):
            print(f"  WARNING: File not found: {filepath}")
            continue
        texts = parse_jsonl(filepath)
        print(f"  {os.path.basename(filepath)}: {len(texts)} messages extracted")
        all_texts.extend(texts)

    if not all_texts:
        print("ERROR: No texts extracted. Exiting.")
        sys.exit(1)

    # Deduplicate by content (Cognee uses content hashing)
    seen_hashes = set()
    unique_texts = []
    for t in all_texts:
        import hashlib
        h = hashlib.md5(t.encode()).hexdigest()
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_texts.append(t)
    all_texts = unique_texts
    print(f"  Total unique messages to ingest: {len(all_texts)}")

    # Group messages per session into larger documents for better entity extraction
    session_docs = {}
    for t in all_texts:
        # Extract session id from prefix
        sid = t.split("]")[0].split(":")[1].strip().split(",")[0]
        if sid not in session_docs:
            session_docs[sid] = []
        session_docs[sid].append(t)

    # Create one document per session (concatenate messages)
    docs = []
    for sid, messages in session_docs.items():
        doc = f"=== Developer Session {sid} ===\n\n" + "\n\n".join(messages)
        # Cognee has limits; truncate very large docs
        if len(doc) > 50000:
            doc = doc[:50000] + "\n\n[...session truncated...]"
        docs.append(doc)
    print(f"  Consolidated into {len(docs)} session documents")

    # Add data to Cognee
    print("\n[3/4] Adding data to Cognee...")
    await cognee.add(docs)
    print("  Data added.")

    # Build knowledge graph
    print("\n[4/4] Running cognify() to build knowledge graph...")
    print("  (This uses Ollama llama3 for entity extraction - may take a while)")
    try:
        result = await cognee.cognify()
        print(f"  cognify() completed. Result type: {type(result)}")
        if result:
            print(f"  Result: {str(result)[:500]}")
    except Exception as e:
        print(f"  ERROR during cognify(): {e}")
        import traceback
        traceback.print_exc()
        print("\n  Continuing to evaluation despite error...")

    print("\n" + "=" * 60)
    print("Ingestion complete. Run evaluate.py to inspect the graph.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
