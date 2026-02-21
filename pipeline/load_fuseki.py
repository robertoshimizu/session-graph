#!/usr/bin/env python3
"""Load Turtle files into Apache Jena Fuseki.

Usage:
    python load_fuseki.py <file1.ttl> [file2.ttl ...]

Fuseki must be running at http://localhost:3030.
Creates the 'devkg' dataset if it doesn't exist, then uploads Turtle files.
"""

import sys
import argparse
from pathlib import Path

import requests

FUSEKI_URL = "http://localhost:3030"
DATASET = "devkg"


def ensure_dataset(fuseki_url: str, dataset: str, auth: tuple[str, str] | None = None) -> bool:
    """Create the dataset if it doesn't exist."""
    # Check if dataset exists
    try:
        resp = requests.get(f"{fuseki_url}/$/datasets/{dataset}", timeout=5, auth=auth)
        if resp.status_code == 200:
            print(f"Dataset '{dataset}' already exists.")
            return True
    except requests.ConnectionError:
        print(f"Error: Cannot connect to Fuseki at {fuseki_url}", file=sys.stderr)
        print("Start Fuseki with: cd ~/opt/apache-jena-fuseki && ./fuseki-server", file=sys.stderr)
        return False

    # Create dataset (TDB2 persistent)
    print(f"Creating dataset '{dataset}'...")
    resp = requests.post(
        f"{fuseki_url}/$/datasets",
        data={"dbName": dataset, "dbType": "tdb2"},
        timeout=10,
        auth=auth,
    )
    if resp.status_code in (200, 201):
        print(f"Dataset '{dataset}' created successfully.")
        return True
    else:
        print(f"Failed to create dataset: {resp.status_code} {resp.text}", file=sys.stderr)
        return False


def upload_turtle(fuseki_url: str, dataset: str, ttl_path: str, auth: tuple[str, str] | None = None) -> bool:
    """Upload a Turtle file to the dataset."""
    path = Path(ttl_path)
    if not path.exists():
        print(f"  File not found: {path}", file=sys.stderr)
        return False

    print(f"  Uploading: {path.name} ({path.stat().st_size} bytes)...")

    with open(path, "rb") as f:
        resp = requests.post(
            f"{fuseki_url}/{dataset}/data",
            data=f,
            headers={"Content-Type": "text/turtle"},
            timeout=60,
            auth=auth,
        )

    if resp.status_code in (200, 201, 204):
        print(f"  Uploaded successfully.")
        return True
    else:
        print(f"  Upload failed: {resp.status_code} {resp.text}", file=sys.stderr)
        return False


def count_triples(fuseki_url: str, dataset: str, auth: tuple[str, str] | None = None) -> int | None:
    """Query the total number of triples in the dataset."""
    query = "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
    try:
        resp = requests.get(
            f"{fuseki_url}/{dataset}/sparql",
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
            timeout=10,
            auth=auth,
        )
        if resp.status_code == 200:
            results = resp.json()
            bindings = results.get("results", {}).get("bindings", [])
            if bindings:
                return int(bindings[0]["count"]["value"])
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Load Turtle files into Fuseki")
    parser.add_argument("files", nargs="+", help="Turtle files to upload")
    parser.add_argument("--fuseki-url", default=FUSEKI_URL, help="Fuseki URL")
    parser.add_argument("--dataset", default=DATASET, help="Dataset name")
    parser.add_argument("--auth", help="user:password for Fuseki auth (e.g. admin:admin)")
    args = parser.parse_args()

    auth = tuple(args.auth.split(":", 1)) if args.auth else None

    if not ensure_dataset(args.fuseki_url, args.dataset, auth=auth):
        sys.exit(1)

    success = 0
    for ttl_file in args.files:
        if upload_turtle(args.fuseki_url, args.dataset, ttl_file, auth=auth):
            success += 1

    total = count_triples(args.fuseki_url, args.dataset, auth=auth)
    print(f"\nUploaded {success}/{len(args.files)} files.")
    if total is not None:
        print(f"Total triples in dataset: {total}")


if __name__ == "__main__":
    main()
