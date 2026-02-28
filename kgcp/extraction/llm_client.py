"""LLM client for OpenAI-compatible API endpoints.

Adapted from AIKG's llm.py — handles API calls and JSON extraction.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)


def call_llm(
    prompt: str,
    config: dict[str, Any],
    system_prompt: str = "",
) -> str:
    """Call an OpenAI-compatible chat completion endpoint.

    Args:
        prompt: User message content.
        config: Must contain llm.base_url, llm.model, llm.api_key, etc.
        system_prompt: Optional system message.

    Returns:
        The assistant's response text.

    Raises:
        requests.HTTPError: On non-2xx responses.
        ConnectionError: If the LLM endpoint is unreachable.
    """
    llm_cfg = config["llm"]
    url = llm_cfg["base_url"]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {llm_cfg['api_key']}",
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": llm_cfg["model"],
        "messages": messages,
        "temperature": llm_cfg.get("temperature", 0.8),
        "max_tokens": llm_cfg.get("max_tokens", 8192),
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.ConnectionError:
        raise ConnectionError(
            f"Cannot reach LLM endpoint at {url}. "
            "Is Ollama running? Try: ollama serve"
        )

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def extract_json_from_text(text: str) -> list[dict] | None:
    """Extract a JSON array from LLM response text.

    Handles:
    - JSON inside code blocks (```json ... ```)
    - Direct JSON arrays
    - Truncated JSON (reconstructs from complete objects)
    - Common formatting issues (trailing commas, unquoted keys)

    Returns:
        Parsed list of dicts, or None if extraction fails.
    """
    # Try code block extraction first
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_block:
        text = code_block.group(1).strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Find the outermost array
    bracket_start = text.find("[")
    if bracket_start == -1:
        # No array found — try extracting individual objects
        objects = []
        for match in re.finditer(r"\{[^{}]*\}", text):
            try:
                obj = json.loads(match.group())
                objects.append(obj)
            except json.JSONDecodeError:
                continue
        return objects if objects else None

    # Track bracket depth to find matching close
    depth = 0
    bracket_end = -1
    for i in range(bracket_start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                bracket_end = i
                break

    if bracket_end != -1:
        candidate = text[bracket_start : bracket_end + 1]
        # Fix trailing commas before ] or }
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            result = json.loads(candidate)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Last resort: extract individual complete objects
    objects = []
    for match in re.finditer(r"\{[^{}]*\}", text):
        try:
            obj = json.loads(match.group())
            objects.append(obj)
        except json.JSONDecodeError:
            continue

    return objects if objects else None
