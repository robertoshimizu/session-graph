"""Shared fixtures for DevKG pipeline tests."""

import json
import pytest

from pipeline.common import create_graph


@pytest.fixture
def empty_graph():
    """An empty RDF graph with all namespaces bound."""
    return create_graph()


@pytest.fixture
def sample_triples():
    """A list of normalized knowledge triple dicts."""
    return [
        {"subject": "neo4j", "predicate": "isTypeOf", "object": "graph database"},
        {"subject": "langchain", "predicate": "uses", "object": "python"},
        {"subject": "fuseki", "predicate": "provides", "object": "sparql endpoint"},
    ]


@pytest.fixture
def sample_jsonl_content():
    """Sample Claude Code transcript JSONL content (as a string)."""
    lines = [
        {"type": "user", "message": {"content": [{"type": "text", "text": "How does Neo4j work?"}]}},
        {"type": "assistant", "message": {
            "content": [{"type": "text", "text": "Neo4j is a graph database that stores data as nodes and relationships. It uses the Cypher query language for traversals."}],
            "timestamp": "2026-02-20T10:00:00Z",
        }},
        {"type": "user", "message": {"content": [{"type": "text", "text": "Thanks"}]}},
        {"type": "assistant", "message": {
            "content": [{"type": "text", "text": "You're welcome!"}],
            "timestamp": "2026-02-20T10:01:00Z",
        }},
    ]
    return "\n".join(json.dumps(line) for line in lines)
