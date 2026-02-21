"""Tests for pipeline.common — URI helpers, graph setup, and node builders."""

from rdflib import Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD, DCTERMS

from pipeline.common import (
    slug,
    entity_uri,
    bind_namespaces,
    create_session_node,
    create_developer_node,
    create_model_node,
    create_message_node,
    create_project_node,
    add_triples_to_graph,
    DATA,
    DEVKG,
    SIOC,
)


# ---- slug() ----

class TestSlug:
    def test_basic(self):
        assert slug("Hello World") == "hello-world"

    def test_special_characters(self):
        assert slug("Neo4j + Cypher") == "neo4j-cypher"

    def test_already_clean(self):
        assert slug("neo4j") == "neo4j"

    def test_strips_leading_trailing_hyphens(self):
        assert slug("  !Hello! ") == "hello"

    def test_numbers_preserved(self):
        assert slug("python 3.12") == "python-3-12"

    def test_empty_string(self):
        assert slug("") == ""

    def test_only_special_chars(self):
        assert slug("!@#$%") == ""


# ---- entity_uri() ----

class TestEntityUri:
    def test_returns_uriref(self):
        uri = entity_uri("Neo4j")
        assert isinstance(uri, URIRef)

    def test_deterministic(self):
        assert entity_uri("Neo4j") == entity_uri("Neo4j")

    def test_path_format(self):
        uri = entity_uri("graph database")
        assert str(uri) == "http://devkg.local/data/entity/graph-database"


# ---- create_graph() / bind_namespaces() ----

class TestGraphSetup:
    def test_create_graph_returns_graph(self, empty_graph):
        from rdflib import Graph
        assert isinstance(empty_graph, Graph)

    def test_namespaces_bound(self, empty_graph):
        ns_map = dict(empty_graph.namespaces())
        assert "prov" in ns_map
        assert "sioc" in ns_map
        assert "skos" in ns_map
        assert "devkg" in ns_map
        assert "data" in ns_map
        assert "owl" in ns_map

    def test_bind_namespaces_idempotent(self, empty_graph):
        bind_namespaces(empty_graph)
        bind_namespaces(empty_graph)
        ns_map = dict(empty_graph.namespaces())
        assert "devkg" in ns_map


# ---- Node builders ----

class TestCreateSessionNode:
    def test_basic_session(self, empty_graph):
        uri = create_session_node(empty_graph, "abc-123", "claude-code")
        assert (uri, RDF.type, DEVKG.Session) in empty_graph
        assert (uri, DEVKG.hasSourcePlatform, Literal("claude-code")) in empty_graph

    def test_session_with_all_fields(self, empty_graph):
        uri = create_session_node(
            empty_graph, "abc-123", "deepseek",
            created="2026-01-01T00:00:00Z",
            modified="2026-01-02T00:00:00Z",
            title="Test Session",
            source_file="/tmp/test.jsonl",
        )
        assert (uri, DCTERMS.created, Literal("2026-01-01T00:00:00Z", datatype=XSD.dateTime)) in empty_graph
        assert (uri, DCTERMS.modified, Literal("2026-01-02T00:00:00Z", datatype=XSD.dateTime)) in empty_graph
        assert (uri, DCTERMS.title, Literal("Test Session")) in empty_graph
        assert (uri, DEVKG.hasSourceFile, Literal("/tmp/test.jsonl")) in empty_graph

    def test_session_uri_format(self, empty_graph):
        uri = create_session_node(empty_graph, "My Session", "grok")
        assert "session/my-session" in str(uri)


class TestCreateDeveloperNode:
    def test_basic(self, empty_graph):
        uri = create_developer_node(empty_graph, "Roberto")
        assert (uri, RDF.type, DEVKG.Developer) in empty_graph
        assert (uri, RDFS.label, Literal("Roberto")) in empty_graph

    def test_idempotent(self, empty_graph):
        uri1 = create_developer_node(empty_graph, "Roberto")
        uri2 = create_developer_node(empty_graph, "Roberto")
        assert uri1 == uri2
        # Should only have one type triple
        count = len(list(empty_graph.triples((uri1, RDF.type, DEVKG.Developer))))
        assert count == 1


class TestCreateModelNode:
    def test_basic(self, empty_graph):
        uri = create_model_node(empty_graph, "gemini-2.5-flash")
        assert (uri, RDF.type, DEVKG.AIModel) in empty_graph
        assert (uri, RDFS.label, Literal("gemini-2.5-flash")) in empty_graph

    def test_idempotent(self, empty_graph):
        uri1 = create_model_node(empty_graph, "claude-opus-4")
        uri2 = create_model_node(empty_graph, "claude-opus-4")
        assert uri1 == uri2


class TestCreateMessageNode:
    def test_user_message(self, empty_graph):
        session_uri = DATA["session/test"]
        dev_uri = DATA["developer/roberto"]
        uri = create_message_node(
            empty_graph, "msg-001", "user", session_uri,
            creator_uri=dev_uri,
        )
        assert (uri, RDF.type, DEVKG.UserMessage) in empty_graph
        assert (uri, SIOC.has_creator, dev_uri) in empty_graph

    def test_assistant_message(self, empty_graph):
        session_uri = DATA["session/test"]
        uri = create_message_node(
            empty_graph, "msg-002", "assistant", session_uri,
        )
        assert (uri, RDF.type, DEVKG.AssistantMessage) in empty_graph

    def test_content_truncation(self, empty_graph):
        session_uri = DATA["session/test"]
        long_content = "x" * 3000
        uri = create_message_node(
            empty_graph, "msg-003", "assistant", session_uri,
            content=long_content,
        )
        stored = str(list(empty_graph.objects(uri, SIOC.content))[0])
        assert len(stored) == 2003  # 2000 + "..."
        assert stored.endswith("...")

    def test_parent_message(self, empty_graph):
        session_uri = DATA["session/test"]
        parent = DATA["message/msg-001"]
        uri = create_message_node(
            empty_graph, "msg-002", "user", session_uri,
            parent_uri=parent,
        )
        assert (uri, DEVKG.hasParentMessage, parent) in empty_graph


class TestCreateProjectNode:
    def test_basic(self, empty_graph):
        uri = create_project_node(empty_graph, "dev-knowledge-graph")
        assert (uri, RDF.type, DEVKG.Project) in empty_graph

    def test_custom_label(self, empty_graph):
        uri = create_project_node(empty_graph, "dev-kg", label="Dev Knowledge Graph")
        assert (uri, RDFS.label, Literal("Dev Knowledge Graph")) in empty_graph


# ---- add_triples_to_graph() ----

class TestAddTriplesToGraph:
    def test_creates_entity_nodes(self, empty_graph, sample_triples):
        session_uri = DATA["session/test"]
        msg_uri = DATA["message/msg-001"]
        add_triples_to_graph(empty_graph, msg_uri, sample_triples, session_uri)

        # Check entity nodes exist
        neo4j_uri = entity_uri("neo4j")
        assert (neo4j_uri, RDF.type, DEVKG.Entity) in empty_graph
        assert (neo4j_uri, RDFS.label, Literal("neo4j")) in empty_graph

    def test_creates_direct_edges(self, empty_graph, sample_triples):
        session_uri = DATA["session/test"]
        msg_uri = DATA["message/msg-001"]
        add_triples_to_graph(empty_graph, msg_uri, sample_triples, session_uri)

        neo4j_uri = entity_uri("neo4j")
        graph_db_uri = entity_uri("graph database")
        assert (neo4j_uri, DEVKG["isTypeOf"], graph_db_uri) in empty_graph

    def test_creates_reified_triples(self, empty_graph, sample_triples):
        session_uri = DATA["session/test"]
        msg_uri = DATA["message/msg-001"]
        add_triples_to_graph(empty_graph, msg_uri, sample_triples, session_uri)

        # Should have 3 KnowledgeTriple nodes
        kt_nodes = list(empty_graph.subjects(RDF.type, DEVKG.KnowledgeTriple))
        assert len(kt_nodes) == 3

    def test_creates_topic_links(self, empty_graph, sample_triples):
        session_uri = DATA["session/test"]
        msg_uri = DATA["message/msg-001"]
        add_triples_to_graph(empty_graph, msg_uri, sample_triples, session_uri)

        # Message should mention topics
        topics = list(empty_graph.objects(msg_uri, DEVKG.mentionsTopic))
        # 3 triples = 6 entity mentions, but some may be unique
        assert len(topics) == 6  # all unique in sample_triples

    def test_entity_dedup(self, empty_graph):
        """Entities appearing in multiple triples should only be created once."""
        session_uri = DATA["session/test"]
        msg_uri = DATA["message/msg-001"]
        triples = [
            {"subject": "python", "predicate": "uses", "object": "pip"},
            {"subject": "python", "predicate": "enables", "object": "scripting"},
        ]
        add_triples_to_graph(empty_graph, msg_uri, triples, session_uri)

        python_uri = entity_uri("python")
        type_triples = list(empty_graph.triples((python_uri, RDF.type, DEVKG.Entity)))
        assert len(type_triples) == 1
