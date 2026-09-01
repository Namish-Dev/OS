"""
Personal OS — LLM-based Classification.

This is the layer between "the rule-based ProjectMatcher found
nothing" and "ask the human". It asks the local model a narrow,
constrained question — given this content and this exact list of
projects, which one (if any) fits? — and parses the answer
defensively, since small local models don't always follow output
format instructions perfectly.

If the LLM is unavailable, times out, or gives an answer we can't
confidently parse, this returns UNASSIGNED/CONFIDENCE_NONE — the
same as "no match" — so the caller falls through to asking the user.
The LLM is an optimization layer, never a hard dependency.

Platform-independent (talks to core.llm_client, not the OS/network
directly).
"""

from core.llm_client import LLMClient, LLMUnavailableError
from core.project_matcher import (
    UNASSIGNED, DISTRACTION, CONFIDENCE_HIGH, CONFIDENCE_NONE,
)

_SYSTEM_PROMPT = (
    "You are a strict classifier inside a personal productivity tool. "
    "You will be given a short description of something the user was "
    "looking at, and a list of their project names. "
    "Respond with EXACTLY ONE of the following, and nothing else: "
    "one of the project names EXACTLY as given, OR the single word "
    "DISTRACTION if this is clearly entertainment/not work-related, OR "
    "the single word UNSURE if you cannot tell. "
    "Do not explain your answer. Do not add punctuation."
)


def _build_prompt(
    label: str, kind: str, category: str, domain: str | None, url: str | None,
    workspace: str | None, vault: str | None, project_names: list[str],
) -> str:

    lines = [
        f"Content type: {kind}",
        f"Title/description: {label}",
    ]

    if domain:
        lines.append(f"Source: {domain}")

    if url:
        lines.append(f"URL: {url}")

    if workspace:
        lines.append(f"Code workspace/folder: {workspace}")

    if vault:
        lines.append(f"Notes vault: {vault}")

    lines.append(f"Detected activity category: {category}")
    lines.append("")
    lines.append("Projects:")

    for name in project_names:
        lines.append(f"- {name}")

    lines.append("")
    lines.append(
        "Which project does this belong to? A workspace/folder or vault name "
        "that closely resembles a project name (even if not identical) is "
        "strong evidence for that project. "
        "Answer with one project name, DISTRACTION, or UNSURE."
    )

    return "\n".join(lines)


def _parse_response(raw_response: str, project_names: list[str]) -> str | None:
    """
    Return a matched label (a project name or DISTRACTION), or None
    if the response can't be confidently matched to any known label.

    Checks the longest candidate labels first, so a project named
    "FastAPI" doesn't accidentally match a response that actually
    said "FastAPI Authentication".
    """

    response_lower = raw_response.strip().lower()

    if not response_lower or "unsure" in response_lower:
        return None

    candidates = sorted(
        [*project_names, DISTRACTION],
        key=len,
        reverse=True,
    )

    for candidate in candidates:
        if candidate.lower() in response_lower:
            return candidate

    return None


def classify_with_llm(
    client: LLMClient,
    label: str,
    kind: str,
    category: str,
    domain: str | None,
    project_names: list[str],
    url: str | None = None,
    workspace: str | None = None,
    vault: str | None = None,
) -> tuple[str, str]:
    """
    Ask the local LLM to classify one piece of content.

    Returns (result_label, confidence) in the same shape as
    ProjectMatcher.match_with_confidence(): result_label is a
    project name, DISTRACTION, or UNASSIGNED; confidence is
    CONFIDENCE_HIGH (LLM gave a clear answer) or CONFIDENCE_NONE
    (LLM unavailable, timed out, or genuinely unsure).
    """

    prompt = _build_prompt(label, kind, category, domain, url, workspace, vault, project_names)

    try:
        raw_response = client.generate(prompt, system=_SYSTEM_PROMPT)
    except LLMUnavailableError:
        return UNASSIGNED, CONFIDENCE_NONE

    matched = _parse_response(raw_response, project_names)

    if matched is None:
        return UNASSIGNED, CONFIDENCE_NONE

    return matched, CONFIDENCE_HIGH