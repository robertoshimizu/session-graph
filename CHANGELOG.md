# Changelog

## [0.4.0] — 2026-02-21

### Added
- **Real-time ingestion via Stop hook**: `hooks/stop_hook.sh` fires after every Claude Code assistant response, backgrounding `pipeline/realtime_extract.py` for automatic knowledge extraction
- Triple extraction (Gemini, top 10) + entity linking (parallel, cache-first) + Fuseki upload — all invisible to the user (~22s with warm cache)
- SHA256 watermark dedup per session — same message is never processed twice
- Guards: skips if hook is re-entrant, message < 100 chars, or already processed

### New files
- `hooks/stop_hook.sh` — Shell wrapper with venv/transcript/session guards
- `pipeline/realtime_extract.py` — Full extraction pipeline for a single response

## [0.3.0] — 2026-02-21

### Added
- **Two-level entity filtering**: Level 1 (`is_valid_entity()`) rejects garbage at extraction time (13 filter groups). Level 2 (`is_linkable_entity()`) pre-filters before Wikidata API calls. 48 whitelisted short terms bypass all filters.
- **Top-10 extraction cap**: Prompt extracts at most 10 triples per message, prioritizing architectural decisions and technology choices. Hard cap enforced in parsing.
- **Frequency-based entity linking**: `--min-sessions N` flag (default: 2) only links entities appearing in N+ sessions. ~77% of entities are single-session noise.

### Impact
- Triples per full extraction: 75,743 → 43,949 (-42%)
- Entities sent to Wikidata linker: ~28,000 → ~3,729 (-87%)

## [0.2.0] — 2026-02-20

### Added
- Context-aware Wikidata entity linking: neighboring KnowledgeTriple relationships passed as disambiguation context to the ReAct agent
- `pipeline/snapshot_links.py` for inspecting intermediate entity linking (read-only SQLite cache access)
- Stopword filters in `triple_extraction.py`: `[object object]`, IP addresses, durations, hex hashes, quantity phrases, ordinals, fractions
- Hybrid KG+grep skills (`/research-sessions`, `/resume-last-session`)

### Fixed
- 8 mislinked entities (condition, variation, conduta, conduct, protocol conduta, editing, route, lab test)

## [0.1.0] — 2026-02-19

### Changed
- Refactored CLAUDE.md from 935 → 396 lines (58% reduction)
- Consolidated duplicate sections (6 per-sprint changelogs → summary table, 6 "How to Run" → 1)
