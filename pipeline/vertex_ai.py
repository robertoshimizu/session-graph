"""
Vertex AI authentication for Gemini and Claude models.

Usage:
    from pipeline.vertex_ai import init_vertex, get_gemini_model, get_claude_model

    credentials = init_vertex()
    model = get_gemini_model()                          # Gemini
    model = get_claude_model("claude-haiku-4-5-v2")     # Claude via Vertex AI
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


_GLOBAL_ONLY_MODELS = {"gemini-3-flash-preview", "gemini-3-pro-preview"}


def get_gemini_model(model_name: str | None = None) -> GenerativeModel:
    """Return a GenerativeModel configured for JSON output."""
    if model_name is None:
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    # Some models (e.g. gemini-3-flash-preview) require global endpoint
    if model_name in _GLOBAL_ONLY_MODELS:
        vertexai.init(location="global")
        print(f"  Re-initialized Vertex AI with location=global for {model_name}", file=sys.stderr)

    config = GenerationConfig(
        response_mime_type="application/json",
        temperature=0.2,
        max_output_tokens=8192,
    )

    return GenerativeModel(model_name, generation_config=config)


# Cache project/location from init_vertex for Claude client
_vertex_project: str | None = None
_vertex_location: str | None = None


def get_claude_model(model_name: str = "claude-haiku-4-5@20251001"):
    """Return an AnthropicVertex client + model name tuple for Claude on Vertex AI.

    Returns a wrapper object with a generate_content() method matching the Gemini
    interface so triple_extraction.py can use it transparently.

    Note: Claude on Vertex AI requires us-east5 region, regardless of VERTEX_AI_LOCATION.
    """
    from anthropic import AnthropicVertex

    global _vertex_project
    if _vertex_project is None:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            b64 = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_BASE64", "")
            if b64:
                try:
                    project = json.loads(base64.b64decode(b64).decode()).get("project_id")
                except Exception:
                    pass
        _vertex_project = project

    # Claude on Vertex AI is only available in us-east5
    claude_region = os.environ.get("CLAUDE_VERTEX_REGION", "us-east5")

    client = AnthropicVertex(project_id=_vertex_project, region=claude_region)
    print(f"  Claude model: {model_name} (project={_vertex_project}, region={claude_region})", file=sys.stderr)

    return ClaudeModelWrapper(client, model_name)


class ClaudeModelWrapper:
    """Wraps AnthropicVertex to match Gemini's generate_content() interface."""

    def __init__(self, client, model_name: str):
        self._client = client
        self._model_name = model_name

    def generate_content(self, prompt: str):
        response = self._client.messages.create(
            model=self._model_name,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return ClaudeResponse(response)


class ClaudeResponse:
    """Wraps Anthropic response to expose .text like Gemini."""

    def __init__(self, response):
        self._response = response

    @property
    def text(self) -> str:
        return self._response.content[0].text
