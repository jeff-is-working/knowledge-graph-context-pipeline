"""Token counting utilities.

Uses a simple word-based estimator by default.
Falls back to tiktoken if available for precise counts.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimate token count for a text string.

    Uses the ~4 chars per token heuristic (good for English text).
    If tiktoken is available, uses cl100k_base for precise counts.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # Fallback: ~4 chars per token, ~0.75 tokens per word
        return max(1, len(text) // 4)
