"""Shared RDF construction logic for all platform parsers.

Provides namespace constants, URI helpers, and reusable graph-building functions
that all parsers (Claude Code, DeepSeek, Grok, Warp) share.
"""

import re
import hashlib

from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD, OWL, SKOS, DCTERMS

# =============================================================================
# Namespace Constants
# =============================================================================

PROV = Namespace("http://www.w3.org/ns/prov#")
SIOC = Namespace("http://rdfs.org/sioc/ns#")
SCHEMA = Namespace("http://schema.org/")
DEVKG = Namespace("http://devkg.local/ontology#")
DATA = Namespace("http://devkg.local/data/")
WD = Namespace("http://www.wikidata.org/entity/")


# =============================================================================
# URI Helpers
# =============================================================================

def slug(text: str) -> str:
    """Create a URI-safe slug from text."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def entity_uri(name: str) -> URIRef:
    """Create a deterministic URI for an extracted entity."""
    return DATA[f"entity/{slug(name)}"]


# =============================================================================
# Graph Setup
# =============================================================================

def bind_namespaces(g: Graph) -> None:
    """Bind all standard namespaces to a graph."""
    g.bind("prov", PROV)
    g.bind("sioc", SIOC)
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)
    g.bind("schema", SCHEMA)
    g.bind("devkg", DEVKG)
    g.bind("data", DATA)
    g.bind("owl", OWL)


def create_graph() -> Graph:
    """Create a new RDF graph with all namespaces bound."""
    g = Graph()
    bind_namespaces(g)
    return g


# =============================================================================
# Node Builders
# =============================================================================

def create_session_node(
    g: Graph,
    session_id: str,
    platform: str,
    *,
    created: str | None = None,
    modified: str | None = None,
    title: str | None = None,
    source_file: str | None = None,
) -> URIRef:
    """Create a devkg:Session node in the graph.

    Returns the session URI.
    """
    session_uri = DATA[f"session/{slug(session_id)}"]
    g.add((session_uri, RDF.type, DEVKG.Session))
    g.add((session_uri, DEVKG.hasSourcePlatform, Literal(platform)))

    if created:
        g.add((session_uri, DCTERMS.created, Literal(created, datatype=XSD.dateTime)))
    if modified:
        g.add((session_uri, DCTERMS.modified, Literal(modified, datatype=XSD.dateTime)))
    if title:
        g.add((session_uri, DCTERMS.title, Literal(title)))
    if source_file:
        g.add((session_uri, DEVKG.hasSourceFile, Literal(source_file)))

    return session_uri


def create_developer_node(g: Graph, name: str, dev_id: str | None = None) -> URIRef:
    """Create a devkg:Developer node. Returns the developer URI."""
    uri_part = slug(dev_id or name)
    dev_uri = DATA[f"developer/{uri_part}"]
    if (dev_uri, RDF.type, DEVKG.Developer) not in g:
        g.add((dev_uri, RDF.type, DEVKG.Developer))
        g.add((dev_uri, RDFS.label, Literal(name)))
    return dev_uri


def create_model_node(g: Graph, model_id: str) -> URIRef:
    """Create a devkg:AIModel node. Returns the model URI."""
    model_uri = DATA[f"model/{slug(model_id)}"]
    if (model_uri, RDF.type, DEVKG.AIModel) not in g:
        g.add((model_uri, RDF.type, DEVKG.AIModel))
        g.add((model_uri, DEVKG.hasModel, Literal(model_id)))
        g.add((model_uri, RDFS.label, Literal(model_id)))
    return model_uri


def create_message_node(
    g: Graph,
    msg_id: str,
    role: str,
    session_uri: URIRef,
    *,
    creator_uri: URIRef | None = None,
    timestamp: str | None = None,
    content: str | None = None,
    parent_uri: URIRef | None = None,
) -> URIRef:
    """Create a devkg:UserMessage or devkg:AssistantMessage node.

    Args:
        role: "user" or "assistant"
    Returns the message URI.
    """
    msg_uri = DATA[f"message/{msg_id}"]

    if role == "user":
        g.add((msg_uri, RDF.type, DEVKG.UserMessage))
        if creator_uri:
            g.add((msg_uri, SIOC.has_creator, creator_uri))
    else:
        g.add((msg_uri, RDF.type, DEVKG.AssistantMessage))

    g.add((msg_uri, DEVKG.hasMessageId, Literal(msg_id)))
    g.add((msg_uri, DEVKG.usedInSession, session_uri))
    g.add((msg_uri, SIOC.has_container, session_uri))

    if timestamp:
        g.add((msg_uri, DCTERMS.created, Literal(timestamp, datatype=XSD.dateTime)))
    if content:
        stored = content if len(content) <= 2000 else content[:2000] + "..."
        g.add((msg_uri, SIOC.content, Literal(stored)))
    if parent_uri:
        g.add((msg_uri, DEVKG.hasParentMessage, parent_uri))

    return msg_uri


def create_project_node(g: Graph, project_slug: str, label: str | None = None) -> URIRef:
    """Create a devkg:Project node. Returns the project URI."""
    proj_uri = DATA[f"project/{slug(project_slug)}"]
    if (proj_uri, RDF.type, DEVKG.Project) not in g:
        g.add((proj_uri, RDF.type, DEVKG.Project))
        g.add((proj_uri, RDFS.label, Literal(label or project_slug)))
    return proj_uri


# =============================================================================
# Knowledge Triple Helpers
# =============================================================================

def add_triples_to_graph(
    g: Graph,
    msg_uri: URIRef,
    triples: list[dict],
    session_uri: URIRef,
) -> None:
    """Add extracted knowledge triples to the RDF graph.

    For each triple, creates:
    - Entity nodes (subject and object) with type and label
    - A direct edge using the devkg predicate (for fast traversal)
    - A reified KnowledgeTriple node (for provenance tracking)
    - mentionsTopic links from the message to both entities
    """
    for t in triples:
        subj_name = t["subject"]
        pred_name = t["predicate"]
        obj_name = t["object"]

        subj_uri = entity_uri(subj_name)
        obj_uri = entity_uri(obj_name)

        # Create Entity nodes if not already present
        if (subj_uri, RDF.type, DEVKG.Entity) not in g:
            g.add((subj_uri, RDF.type, DEVKG.Entity))
            g.add((subj_uri, RDFS.label, Literal(subj_name)))

        if (obj_uri, RDF.type, DEVKG.Entity) not in g:
            g.add((obj_uri, RDF.type, DEVKG.Entity))
            g.add((obj_uri, RDFS.label, Literal(obj_name)))

        # Direct edge: subject --predicate--> object
        pred_uri = DEVKG[pred_name]
        g.add((subj_uri, pred_uri, obj_uri))

        # Reified KnowledgeTriple for provenance
        triple_id = hashlib.md5(
            f"{subj_name}|{pred_name}|{obj_name}|{msg_uri}".encode()
        ).hexdigest()[:12]
        triple_uri = DATA[f"triple/{triple_id}"]
        g.add((triple_uri, RDF.type, DEVKG.KnowledgeTriple))
        g.add((triple_uri, DEVKG.tripleSubject, subj_uri))
        g.add((triple_uri, DEVKG.tripleObject, obj_uri))
        g.add((triple_uri, DEVKG.triplePredicateLabel, Literal(pred_name)))
        g.add((triple_uri, DEVKG.extractedFrom, msg_uri))
        g.add((triple_uri, DEVKG.extractedInSession, session_uri))

        # Backward-compatible topic links from message to entities
        g.add((msg_uri, DEVKG.mentionsTopic, subj_uri))
        g.add((msg_uri, DEVKG.mentionsTopic, obj_uri))
