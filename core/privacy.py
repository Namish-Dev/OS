"""
Personal OS — Privacy and Redaction Engine.

Ensures sensitive data (API keys, tokens, passwords, private keys)
is never stored in the database or sent to LLMs.
Enforces size limits on terminal output and handles exclusions.
"""

import os
import re
from pathlib import Path

# Configurable limits
DEFAULT_MAX_OUTPUT_CHARS = 8192
DEFAULT_MAX_DIFF_CHARS = 16384

# Sensitive file patterns that should never have contents recorded
EXCLUDED_FILE_PATTERNS = [
    re.compile(r"(^|[/\\])\.env(\..+)?$", re.IGNORECASE),
    re.compile(r"(^|[/\\])id_rsa(\..+)?$", re.IGNORECASE),
    re.compile(r"(^|[/\\])id_ed25519(\..+)?$", re.IGNORECASE),
    re.compile(r"(^|[/\\]).*\.pem$", re.IGNORECASE),
    re.compile(r"(^|[/\\]).*\.key$", re.IGNORECASE),
    re.compile(r"(^|[/\\])credentials(\.json|\.ini)?$", re.IGNORECASE),
    re.compile(r"(^|[/\\])secrets?\.json$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.git[/\\]", re.IGNORECASE),
]

# Sensitive token / secret regexes
SECRET_PATTERNS = [
    # OpenAI & AI service keys
    (re.compile(r"\b(sk-[A-Za-z0-9_\-]{20,})\b"), "[REDACTED_SECRET]"),
    # GitHub personal access tokens
    (re.compile(r"\b(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{36,})\b"), "[REDACTED_SECRET]"),
    # AWS access key IDs
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "[REDACTED_SECRET]"),
    # Generic bearer tokens
    (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE), r"\1[REDACTED_SECRET]"),
    # Passwords in URLs / connection strings (e.g. postgres://user:pass@host)
    (re.compile(r"(://[^:\s]+:)([^@\s]+)(@)", re.IGNORECASE), r"\1[REDACTED_SECRET]\3"),
    # Common key-value secrets (e.g. api_key = "...", password = "...")
    (
        re.compile(r"""((?:api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd|pwd)\s*[:=]\s*["']?)([^"'\s;&]{8,})""", re.IGNORECASE),
        r"\1[REDACTED_SECRET]",
    ),
    # PEM Private keys
    (
        re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9_-]+ )?PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
]


def redact_secrets(text: str | None) -> str:
    """
    Scan text for common API keys, tokens, passwords, and secrets,
    replacing them with safe redaction placeholders.
    """
    if not text:
        return ""

    result = str(text)
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)

    return result


def is_sensitive_file(file_path: str | Path | None) -> bool:
    """Check if a file path corresponds to a known sensitive file pattern."""
    if not file_path:
        return False
    path_str = str(file_path).replace("\\", "/")
    for pattern in EXCLUDED_FILE_PATTERNS:
        if pattern.search(path_str):
            return True
    return False


def truncate_output(output: str | None, max_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> str:
    """
    Truncate large command output or logs while preserving both head
    and tail (where stacktraces and exit errors typically appear).
    """
    if not output:
        return ""

    if len(output) <= max_chars:
        return output

    # Preserve half from start and half from end
    keep = max_chars // 2
    head = output[:keep]
    tail = output[-keep:]
    omitted = len(output) - (keep * 2)
    return f"{head}\n\n[... {omitted} characters truncated by Personal OS ...]\n\n{tail}"


def sanitize_terminal_event(payload: dict) -> dict:
    """
    Redact secrets and enforce output limits on a raw terminal event payload.
    """
    clean = dict(payload)

    # Command line
    if "command" in clean and clean["command"]:
        clean["command"] = redact_secrets(str(clean["command"]).strip())

    # Output / stderr
    if "output" in clean and clean["output"]:
        redacted = redact_secrets(str(clean["output"]))
        clean["output"] = truncate_output(redacted)

    return clean
