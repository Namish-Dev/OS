"""
Personal OS — Local LLM Client.

A thin wrapper around a local Ollama server. This is the "LLM
Interface" layer — everything else in Personal OS talks to this
module, never to Ollama directly, so the underlying model (or even
the runtime — Ollama vs LM Studio vs raw llama.cpp) can be swapped
later without touching any calling code:

    Personal OS
         |
    LLMClient (this file)
         |
    Qwen3 4B today  →  Qwen3 8B later, if ever needed

The LLM is never running continuously and is never on the hot path
for sensors/database/timer/etc — it's called on-demand, only when a
rule-based match genuinely fails (see core/review_queue.py).

Platform-independent — plain HTTP to 127.0.0.1, works identically on
Windows and Linux, wherever Ollama is installed.
"""

import json

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3:4b"

# Local inference on a 4GB-VRAM card is not instant — this needs to
# be generous enough that a real classification call doesn't spuriously
# time out, but short enough that a hung/absent Ollama server fails
# fast instead of blocking the review flow indefinitely.
DEFAULT_TIMEOUT_SECONDS = 30


class LLMUnavailableError(Exception):
    """Raised when the local LLM server can't be reached or errors out.

    Callers (like review_queue) should catch this and fall back to
    asking the user directly — the LLM is an optimization, never a
    hard dependency for Personal OS to keep functioning.
    """


class LLMClient:
    """Minimal client for a local Ollama-compatible server."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate(self, prompt: str, system: str | None = None) -> str:
        """
        Send a single-turn prompt to the local model and return its
        raw text response.

        Raises LLMUnavailableError if the server can't be reached,
        times out, or returns an error — callers must handle this
        and fall back gracefully (never let an LLM outage break the
        rest of Personal OS).
        """

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }

        if system:
            payload["system"] = system

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMUnavailableError(f"Local LLM unreachable: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMUnavailableError(f"Local LLM returned invalid JSON: {exc}") from exc

        text = data.get("response")

        if text is None:
            raise LLMUnavailableError("Local LLM response missing 'response' field")

        return text.strip()

    def is_available(self) -> bool:
        """Quick check whether the local Ollama server is reachable at all."""

        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return response.ok
        except requests.RequestException:
            return False