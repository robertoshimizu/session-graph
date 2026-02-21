"""
Provider-agnostic LLM abstraction layer.

Replaces the Vertex AI-specific vertex_ai.py with a generic interface
that supports multiple LLM backends via a uniform generate_content() API.

Usage:
    from pipeline.llm_providers import get_provider

    model = get_provider("gemini", "gemini-2.5-flash")
    response = model.generate_content("Extract triples from this text...")
    print(response.text)

Supported providers:
    - gemini    : Google Generative AI (GEMINI_API_KEY)
    - openai    : OpenAI API (OPENAI_API_KEY)
    - anthropic : Anthropic API (ANTHROPIC_API_KEY)
    - ollama    : Local Ollama server (no API key, default http://localhost:11434)
"""

import json
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


@dataclass
class ModelResponse:
    """Uniform response object with a .text property, matching the interface
    expected by triple_extraction.py (response.text)."""

    text: str


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    All providers must implement generate_content() which accepts a prompt
    string and returns a ModelResponse with a .text attribute.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name

    @abstractmethod
    def generate_content(self, prompt: str) -> ModelResponse:
        """Send a prompt to the LLM and return the response text."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model_name})"


# ---------------------------------------------------------------------------
# Gemini via google-genai (uses GEMINI_API_KEY, NOT Vertex AI)
# ---------------------------------------------------------------------------


class GeminiProvider(LLMProvider):
    """Google Gemini provider using the google-genai SDK.

    Supports two backends (auto-detected):
      - Vertex AI: when GOOGLE_APPLICATION_CREDENTIALS or ADC is configured
        (requires ANTHROPIC_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT + CLOUD_ML_REGION)
      - Gemini Developer API: when only GEMINI_API_KEY is available
    """

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        super().__init__(model_name)
        try:
            from google import genai
        except ImportError:
            raise ImportError(
                "google-genai package required. Install: pip install google-genai"
            )

        project = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        region = os.environ.get("CLOUD_ML_REGION", "us-east5")
        use_vertex = bool(project)

        if use_vertex:
            self._client = genai.Client(
                vertexai=True,
                project=project,
                location=region,
            )
            backend = f"vertex-ai ({project}/{region})"
        else:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "No Vertex AI project or GEMINI_API_KEY found. "
                    "Set ANTHROPIC_VERTEX_PROJECT_ID + CLOUD_ML_REGION for Vertex AI, "
                    "or GEMINI_API_KEY for the Gemini Developer API."
                )
            self._client = genai.Client(api_key=api_key, vertexai=False)
            backend = "gemini-developer-api"

        print(f"  Gemini provider: {model_name} ({backend})", file=sys.stderr)

    def generate_content(self, prompt: str) -> ModelResponse:
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.2,
                "max_output_tokens": 8192,
            },
        )
        return ModelResponse(text=response.text)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(self, model_name: str = "gpt-4o-mini"):
        super().__init__(model_name)
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai package required. Install: pip install openai"
            )

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set.")

        self._client = OpenAI(api_key=api_key)
        print(f"  OpenAI provider: {model_name}", file=sys.stderr)

    def generate_content(self, prompt: str) -> ModelResponse:
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=8192,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or ""
        return ModelResponse(text=text)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class AnthropicProvider(LLMProvider):
    """Anthropic API provider."""

    def __init__(self, model_name: str = "claude-haiku-4-5-latest"):
        super().__init__(model_name)
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError(
                "anthropic package required. Install: pip install anthropic"
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set.")

        self._client = Anthropic(api_key=api_key)
        print(f"  Anthropic provider: {model_name}", file=sys.stderr)

    def generate_content(self, prompt: str) -> ModelResponse:
        response = self._client.messages.create(
            model=self.model_name,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = response.content[0].text
        return ModelResponse(text=text)


# ---------------------------------------------------------------------------
# Ollama (local)
# ---------------------------------------------------------------------------


class OllamaProvider(LLMProvider):
    """Ollama local server provider (no API key needed)."""

    def __init__(self, model_name: str = "llama3.1"):
        super().__init__(model_name)
        self._base_url = os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        print(
            f"  Ollama provider: {model_name} ({self._base_url})",
            file=sys.stderr,
        )

    def generate_content(self, prompt: str) -> ModelResponse:
        import requests

        response = requests.post(
            f"{self._base_url}/api/generate",
            json={
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.2,
                    "num_predict": 8192,
                },
            },
            timeout=120,
        )
        response.raise_for_status()
        text = response.json().get("response", "")
        return ModelResponse(text=text)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDER_MAP = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
}

# Default models per provider
_DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-latest",
    "ollama": "llama3.1",
}


def get_provider(
    provider_name: str | None = None,
    model_name: str | None = None,
) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider_name: One of 'gemini', 'openai', 'anthropic', 'ollama'.
                       If None, auto-detects from available env vars.
        model_name: Model identifier. If None, uses the provider's default.

    Returns:
        An LLMProvider instance with generate_content() method.

    Raises:
        RuntimeError: If no provider can be determined or initialized.
    """
    if provider_name is None:
        provider_name = _auto_detect_provider()

    provider_name = provider_name.lower()

    if provider_name not in _PROVIDER_MAP:
        raise ValueError(
            f"Unknown provider '{provider_name}'. "
            f"Supported: {', '.join(_PROVIDER_MAP.keys())}"
        )

    if model_name is None:
        model_name = _DEFAULT_MODELS[provider_name]

    cls = _PROVIDER_MAP[provider_name]
    return cls(model_name)


def _auto_detect_provider() -> str:
    """Auto-detect provider from environment variables.

    Priority order: GEMINI_API_KEY > OPENAI_API_KEY > ANTHROPIC_API_KEY > ollama fallback.
    """
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"

    # Check if Ollama is available as a fallback
    try:
        import requests

        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            return "ollama"
    except Exception:
        pass

    raise RuntimeError(
        "No LLM provider detected. Set one of: GEMINI_API_KEY, "
        "OPENAI_API_KEY, ANTHROPIC_API_KEY, or start Ollama locally."
    )


def list_providers() -> list[str]:
    """Return the list of supported provider names."""
    return list(_PROVIDER_MAP.keys())
