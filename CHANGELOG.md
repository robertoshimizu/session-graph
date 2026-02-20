# Changelog

## 2026-02-19 — CLAUDE.md Refactoring

- Refactored CLAUDE.md from 935 → 396 lines (58% reduction)
- Consolidated 6 per-sprint changelogs into a summary table
- Merged 6 duplicate "How to Run" sections into one comprehensive block
- Consolidated file listings, design decisions, and troubleshooting into single sections
- Removed intermediate test results, bug fix narratives, and Go/No-Go tables (all validated)

## 2026-02-20 — Context-Aware Entity Linking & Hybrid Skills

- Added context-aware Wikidata entity linking: `link_entities.py` now extracts neighboring KnowledgeTriple relationships from .ttl files and passes them as disambiguation context to the ReAct agent (fixes "condition"→disease, "variation"→biological variation instead of programming/software concepts)
- Created `pipeline/snapshot_links.py` for inspecting intermediate entity linking results without interrupting a running process (reads SQLite cache in read-only mode)
- Fixed 8 mislinked entities: condition, variation, conduta, conduct, protocol conduta, editing, route, lab test — via selective cache wipe + context-aware re-link + manual pre-seeding for Portuguese medical terms
- Added stopword filters to `triple_extraction.py`: `[object object]`, IP addresses, durations, hex hashes, quantity phrases, ordinals, fractions
- Updated `/research-sessions` and `/resume-last-session` skills to hybrid KG+grep approach (SPARQL first → targeted JSONL reads → grep fallback). Demonstrated 160+ structured relationships in 0.3s vs 12MB JSONL parsing
- Fuseki state: 138,802 triples loaded (52 Claude Code sessions + wikidata links, excluding snapshot file)
