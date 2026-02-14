"""
Vertex AI authentication for Gemini models.

Usage:
    from pipeline.vertex_ai import init_vertex, get_gemini_model

    credentials = init_vertex()
    model = get_gemini_model()
    response = model.generate_content("Extract triples from ...")
"""

import os
import sys
import json
import base64
import tempfile
import atexit

from dotenv import load_dotenv
from google.oauth2 import service_account
import google.auth.transport.requests
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig


def init_vertex() -> service_account.Credentials:
    """Initialize Vertex AI SDK from base64-encoded service account credentials."""
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

    b64_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_BASE64")
    if not b64_creds:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS_BASE64 not set in .env")

    decoded = base64.b64decode(b64_creds).decode("utf-8")

    # Write to temp file with restricted permissions
    fd, creds_path = tempfile.mkstemp(suffix=".json", prefix="gcp-creds-")
    os.write(fd, decoded.encode("utf-8"))
    os.close(fd)
    os.chmod(creds_path, 0o600)

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path

    credentials = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)

    # Project and location
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        try:
            project = json.loads(decoded).get("project_id")
        except (json.JSONDecodeError, KeyError):
            pass
    if not project:
        raise RuntimeError("Could not determine GCP project ID")

    location = os.environ.get("VERTEX_AI_LOCATION", "us-central1")

    vertexai.init(project=project, location=location, credentials=credentials)

    # Cleanup temp file on exit
    atexit.register(lambda: os.unlink(creds_path) if os.path.exists(creds_path) else None)

    print(f"✓ Vertex AI initialized (project={project}, location={location})", file=sys.stderr)
    return credentials


def get_gemini_model(model_name: str | None = None) -> GenerativeModel:
    """Return a GenerativeModel configured for JSON output."""
    if model_name is None:
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    config = GenerationConfig(
        response_mime_type="application/json",
        temperature=0.2,
        max_output_tokens=4096,
    )

    return GenerativeModel(model_name, generation_config=config)
