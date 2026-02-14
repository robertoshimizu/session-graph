"""
Cognee Evaluation: Query and export the knowledge graph built by ingest.py.

Runs several search queries against the Cognee graph and exports results
for quality assessment.
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
os.environ["HUGGINGFACE_TOKENIZER"] = "nomic-ai/nomic-embed-text-v1.5"

ONTOLOGY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "ontology", "devkg.ttl"
)
if os.path.exists(ONTOLOGY_PATH):
    os.environ["ONTOLOGY_FILE_PATH"] = os.path.abspath(ONTOLOGY_PATH)

import cognee
from cognee.api.v1.search import SearchType


OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "cognee")


def save_result(name: str, data):
    """Save query result to JSON file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"{name}.json")

    # Attempt to serialize; handle non-serializable objects
    def default_serializer(obj):
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return str(obj)

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=default_serializer)
    print(f"  Saved: {filepath}")
    return filepath


async def query_graph():
    print("=" * 60)
    print("Cognee Evaluation: Querying Knowledge Graph")
    print("=" * 60)

    # Test queries relevant to the developer knowledge domain
    test_queries = [
        "What technologies and frameworks were discussed?",
        "What problems were being solved?",
        "What is the architecture of the system?",
        "What databases were mentioned?",
        "What AI models and tools were discussed?",
    ]

    # 1. GRAPH_COMPLETION search
    print("\n--- Search Type: GRAPH_COMPLETION ---")
    graph_results = {}
    for query in test_queries:
        print(f"\n  Query: {query}")
        try:
            result = await cognee.search(
                query_type=SearchType.GRAPH_COMPLETION,
                query_text=query,
            )
            graph_results[query] = result
            if result:
                # Print first result summary
                if isinstance(result, list):
                    for i, r in enumerate(result[:3]):
                        print(f"    [{i}] {str(r)[:200]}")
                else:
                    print(f"    {str(result)[:300]}")
            else:
                print("    (no results)")
        except Exception as e:
            print(f"    ERROR: {e}")
            graph_results[query] = {"error": str(e)}

    save_result("graph_completion_results", graph_results)

    # 2. Try INSIGHTS search if available
    print("\n--- Search Type: INSIGHTS ---")
    try:
        insights_results = {}
        for query in test_queries[:3]:
            print(f"\n  Query: {query}")
            result = await cognee.search(
                query_type=SearchType.INSIGHTS,
                query_text=query,
            )
            insights_results[query] = result
            if result:
                if isinstance(result, list):
                    for i, r in enumerate(result[:3]):
                        print(f"    [{i}] {str(r)[:200]}")
                else:
                    print(f"    {str(result)[:300]}")
            else:
                print("    (no results)")
        save_result("insights_results", insights_results)
    except Exception as e:
        print(f"  INSIGHTS search not available: {e}")

    # 3. Try CHUNKS search (vector similarity)
    print("\n--- Search Type: CHUNKS ---")
    try:
        chunks_results = {}
        for query in test_queries[:3]:
            print(f"\n  Query: {query}")
            result = await cognee.search(
                query_type=SearchType.CHUNKS,
                query_text=query,
            )
            chunks_results[query] = result
            if result:
                if isinstance(result, list):
                    for i, r in enumerate(result[:3]):
                        print(f"    [{i}] {str(r)[:200]}")
                else:
                    print(f"    {str(result)[:300]}")
            else:
                print("    (no results)")
        save_result("chunks_results", chunks_results)
    except Exception as e:
        print(f"  CHUNKS search not available: {e}")

    # 4. Try to access the raw Kuzu graph
    print("\n--- Raw Graph Inspection ---")
    try:
        from cognee.infrastructure.databases.graph import get_graph_engine
        graph_engine = await get_graph_engine()
        print(f"  Graph engine type: {type(graph_engine).__name__}")

        # Try to get nodes and edges
        if hasattr(graph_engine, "get_graph_data"):
            graph_data = await graph_engine.get_graph_data()
            print(f"  Graph data keys: {list(graph_data.keys()) if isinstance(graph_data, dict) else type(graph_data)}")
            save_result("raw_graph_data", graph_data)

        # Try various methods to extract graph info
        for method_name in ["get_all_nodes", "get_nodes", "get_edges", "get_all_edges"]:
            if hasattr(graph_engine, method_name):
                try:
                    data = await getattr(graph_engine, method_name)()
                    count = len(data) if hasattr(data, "__len__") else "unknown"
                    print(f"  {method_name}(): {count} items")
                    save_result(f"raw_{method_name}", data)
                except Exception as e:
                    print(f"  {method_name}(): ERROR - {e}")

    except Exception as e:
        print(f"  Could not access raw graph: {e}")
        import traceback
        traceback.print_exc()

    # 5. List available search types
    print("\n--- Available Search Types ---")
    for st in SearchType:
        print(f"  {st.name} = {st.value}")

    print("\n" + "=" * 60)
    print(f"Results saved to: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(query_graph())
