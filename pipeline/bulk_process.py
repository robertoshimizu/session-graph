#!/usr/bin/env python3
"""Bulk process all Claude Code sessions through the DevKG pipeline.

Finds all JSONL session files under ~/.claude/projects/, runs triple
extraction (Gemini), and optionally entity linking (agentic).

Usage:
    python -m pipeline.bulk_process                    # process all
    python -m pipeline.bulk_process --limit 10         # process first 10
    python -m pipeline.bulk_process --dry-run          # list sessions without processing
    python -m pipeline.bulk_process --skip-linking     # parse+extract only
    python -m pipeline.bulk_process --skip-extraction  # structure only (no Gemini)
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from pipeline.jsonl_to_rdf import build_graph


CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "claude"
WATERMARK_FILE = OUTPUT_DIR / "watermarks.json"


def is_subagent_file(path: Path) -> bool:
    """Check if a JSONL file is a subagent session (lives under a /subagents/ directory)."""
    return "/subagents/" in str(path)


def find_sessions(
    projects_dir: Path = CLAUDE_PROJECTS_DIR,
    include_subagents: bool = False,
    sort: str = "name",
) -> list[Path]:
    """Find all JSONL session files under the Claude projects directory.

    Args:
        projects_dir: Root directory to search.
        include_subagents: If False (default), skip files under /subagents/ dirs
            to avoid duplicate knowledge triples from overlapping context.
        sort: Sort order — "name" (default, alphabetical), "newest" (most
            recently modified first), or "oldest" (least recently modified first).
    """
    if not projects_dir.exists():
        print(f"Warning: {projects_dir} does not exist", file=sys.stderr)
        return []
    all_files = list(projects_dir.rglob("*.jsonl"))
    if not include_subagents:
        skipped = sum(1 for f in all_files if is_subagent_file(f))
        all_files = [f for f in all_files if not is_subagent_file(f)]
        if skipped > 0:
            print(f"Skipping {skipped} subagent files (use --include-subagents to include)", file=sys.stderr)
    if sort == "newest":
        all_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    elif sort == "oldest":
        all_files.sort(key=lambda p: p.stat().st_mtime)
    else:
        all_files.sort()
    return all_files


def load_watermarks(watermark_path: Path = WATERMARK_FILE) -> dict:
    """Load watermark file mapping session_path -> last_modified timestamp."""
    if not watermark_path.exists():
        return {}
    with open(watermark_path) as f:
        return json.load(f)


def save_watermarks(watermarks: dict, watermark_path: Path = WATERMARK_FILE) -> None:
    """Save watermark state."""
    watermark_path.parent.mkdir(parents=True, exist_ok=True)
    with open(watermark_path, "w") as f:
        json.dump(watermarks, f, indent=2)


def file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def session_needs_processing(session_path: Path, watermarks: dict) -> bool:
    """Check if a session file has changed since last processing (content hash)."""
    key = str(session_path)
    current_hash = file_hash(session_path)
    prev_hash = watermarks.get(key)
    if prev_hash is not None and current_hash == prev_hash:
        return False
    return True


def session_output_path(session_path: Path) -> Path:
    """Derive output .ttl path from a session JSONL path."""
    session_id = session_path.stem
    return OUTPUT_DIR / f"{session_id}.ttl"


def main():
    parser = argparse.ArgumentParser(
        description="Bulk process all Claude Code sessions through DevKG pipeline",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N sessions",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List sessions without processing",
    )
    parser.add_argument(
        "--skip-linking", action="store_true",
        help="Skip entity linking step (parse + extract only)",
    )
    parser.add_argument(
        "--skip-extraction", action="store_true",
        help="Skip Gemini triple extraction (structure only)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-process all sessions regardless of watermarks",
    )
    parser.add_argument(
        "--provider", default=None,
        help="LLM provider: gemini, openai, anthropic, ollama (auto-detect if omitted)",
    )
    parser.add_argument(
        "--model", default=None,
        help="Model name override",
    )
    parser.add_argument(
        "--heuristic", action="store_true",
        help="Use heuristic entity linking instead of agentic",
    )
    parser.add_argument(
        "--include-subagents", action="store_true",
        help="Include subagent session files (skipped by default to avoid duplicate triples)",
    )
    parser.add_argument(
        "--sort", choices=["name", "newest", "oldest"], default="name",
        help="Sort order for sessions: name (alphabetical, default), newest, or oldest",
    )
    args = parser.parse_args()

    # Find all sessions
    all_sessions = find_sessions(include_subagents=args.include_subagents, sort=args.sort)
    if not all_sessions:
        print("No JSONL sessions found.", file=sys.stderr)
        sys.exit(1)

    # Filter by watermarks (skip already-processed)
    watermarks = load_watermarks()
    if args.force:
        to_process = all_sessions
    else:
        to_process = [s for s in all_sessions if session_needs_processing(s, watermarks)]

    # Apply limit
    if args.limit is not None:
        to_process = to_process[:args.limit]

    print(f"Found {len(all_sessions)} total sessions, {len(to_process)} to process")

    if args.dry_run:
        print(f"\n{'Idx':>4}  {'Size':>8}  {'Path'}")
        print("-" * 90)
        for i, session in enumerate(to_process):
            size_kb = session.stat().st_size / 1024
            print(f"{i:>4}  {size_kb:>7.1f}K  {session}")
        print(f"\nTotal: {len(to_process)} sessions")
        return

    # Initialize LLM provider
    gemini_model = None
    if not args.skip_extraction:
        from pipeline.llm_providers import get_provider
        gemini_model = get_provider(provider_name=args.provider, model_name=args.model)

    # Ensure output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Process sessions
    processed = 0
    total_triples = 0
    output_files = []
    errors = []

    for i, session_path in enumerate(to_process):
        output_path = session_output_path(session_path)
        print(f"\n[{i+1}/{len(to_process)}] {session_path.name}", file=sys.stderr)

        try:
            g = build_graph(
                str(session_path),
                skip_extraction=args.skip_extraction,
                model=gemini_model,
            )

            triple_count = len(g)
            total_triples += triple_count

            g.serialize(destination=str(output_path), format="turtle")
            output_files.append(str(output_path))

            # Update watermark with content hash
            watermarks[str(session_path)] = file_hash(session_path)
            save_watermarks(watermarks)

            processed += 1
            print(f"  -> {output_path.name} ({triple_count} triples)", file=sys.stderr)

            # Brief pause between sessions for API rate limiting
            if not args.skip_extraction and i < len(to_process) - 1:
                time.sleep(1)

        except Exception as e:
            errors.append((session_path, str(e)))
            print(f"  ERROR: {e}", file=sys.stderr)

    # Entity linking (once across all outputs)
    if not args.skip_linking and output_files:
        print(f"\n{'='*60}", file=sys.stderr)
        print("Running entity linking across all outputs...", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        from pipeline.link_entities import (
            load_aliases, init_cache, extract_entities_from_ttl,
            normalize_label, link_entity_list, _ensure_agentic_init,
        )

        agentic = not args.heuristic
        if agentic:
            _ensure_agentic_init()

        aliases = load_aliases()
        cache_conn = init_cache()

        labels = extract_entities_from_ttl(output_files)
        if labels:
            normalized = list(dict.fromkeys(
                normalize_label(lbl, aliases) for lbl in labels
            ))
            print(f"Found {len(labels)} entities, {len(normalized)} after normalization")

            links_output = str(OUTPUT_DIR / "wikidata_links.ttl")
            link_entity_list(
                normalized, links_output, aliases, cache_conn,
                verbose=True, agentic=agentic,
            )

        cache_conn.close()

    # Summary
    print(f"\n{'='*60}")
    print("Bulk Processing Summary")
    print(f"{'='*60}")
    print(f"Sessions processed: {processed}/{len(to_process)}")
    print(f"Total RDF triples:  {total_triples}")
    print(f"Output directory:   {OUTPUT_DIR}")
    if errors:
        print(f"Errors:             {len(errors)}")
        for path, err in errors:
            print(f"  {path.name}: {err}")


if __name__ == "__main__":
    main()
