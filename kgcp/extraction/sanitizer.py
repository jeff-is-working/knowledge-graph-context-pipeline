"""Input text sanitization before LLM prompt interpolation.

Strips control characters, ANSI escapes, and detects injection signal
phrases in untrusted document content before it reaches extraction prompts.
Adapted from the image-to-knowledge sanitize.py defense pattern.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# Phrases that signal prompt injection attempts in document text.
# Each tuple: (pattern_name, regex, severity)
_INJECTION_SIGNALS = [
    # Instruction override / manipulation
    (
        "instruction_override",
        r"\b(?:ignore (?:the )?(?:above|previous|prior|all) (?:instructions?|rules?|prompts?)"
        r"|disregard (?:the )?(?:above|previous|prior|all)"
        r"|new instructions|updated instructions|override (?:the )?instructions?"
        r"|instead[,.]?\s*(?:extract|output|return|do)"
        r"|do not (?:extract|follow|obey))\b",
        "high",
    ),
    # Role / identity override
    (
        "role_override",
        r"\b(?:you are (?:now|a|an)|act as|pretend to be|assume the role"
        r"|your (?:new )?(?:role|task|job|purpose) is)\b",
        "high",
    ),
    # System prompt probing
    (
        "system_prompt_ref",
        r"\b(?:(?:output|reveal|show|repeat|print) (?:your )?(?:system )?(?:prompt|instructions?)"
        r"|system prompt|system message|system instruction)\b",
        "high",
    ),
    # Data exfiltration
    (
        "exfil_attempt",
        r"\b(?:send (?:to|data|the)|post to|upload to|forward to"
        r"|webhook|callback|exfiltrate)\b",
        "medium",
    ),
    # Encoded payloads
    (
        "encoded_payload",
        r"(?:0x[0-9a-fA-F]{20,}|\\x[0-9a-fA-F]{2}(?:\\x[0-9a-fA-F]{2}){9,})",
        "medium",
    ),
    # Code execution attempts
    (
        "code_execution",
        r"```(?:python|bash|sh|shell|javascript|js)\s*\n.*(?:exec|eval|import os|subprocess|system\()",
        "high",
    ),
]

# Context words that indicate legitimate security/CTI discussion
_LEGITIMATE_CTI_CONTEXT = frozenset([
    "threat", "actor", "vulnerability", "cve", "exploit", "malware",
    "phishing", "spear", "attack", "campaign", "defense", "defender",
    "mitigation", "indicator", "ioc", "ttps", "apt", "ransomware",
    "incident", "forensic", "detection", "hunt", "intelligence",
    "adversary", "breach", "compromise", "lateral", "persistence",
    "privilege", "escalation", "exfiltration", "c2", "command and control",
    "authentication", "credential", "rotate", "protect", "secure",
])


@dataclass
class SanitizeResult:
    """Result of sanitizing input text."""

    text: str
    clean: bool = True
    stripped: list[str] = field(default_factory=list)
    injection_signals: list[dict] = field(default_factory=list)
    truncated: bool = False


def sanitize_for_prompt(text: str, max_length: int = 20000) -> SanitizeResult:
    """Sanitize text before interpolating into LLM prompts.

    Strips control characters and ANSI escape sequences that could be used
    to manipulate prompt parsing. Preserves newlines and tabs.

    Args:
        text: Raw document text (untrusted).
        max_length: Maximum character length before truncation.

    Returns:
        SanitizeResult with cleaned text and audit trail.
    """
    result = SanitizeResult(text=text)

    if not text:
        return result

    original = text

    # Strip ANSI escape sequences
    cleaned = _ANSI_ESCAPE_RE.sub("", text)
    if cleaned != text:
        result.stripped.append("ANSI escape sequences")
        result.clean = False
        text = cleaned

    # Strip control characters (preserve \n, \t, \r)
    cleaned = _CONTROL_CHAR_RE.sub("", text)
    if cleaned != text:
        result.stripped.append("control characters")
        result.clean = False
        text = cleaned

    # Enforce max length
    if len(text) > max_length:
        text = text[:max_length] + "\n[TEXT TRUNCATED]"
        result.truncated = True
        result.stripped.append(f"truncated from {len(original)} to {max_length} chars")

    result.text = text

    if result.stripped:
        logger.info("Sanitized input: %s", ", ".join(result.stripped))

    return result


def detect_injection_signals(text: str) -> list[dict]:
    """Scan text for phrases that commonly signal prompt injection.

    This runs on the raw document text BEFORE it reaches the LLM, as an
    early warning system. Detection does not block processing -- it provides
    signals that the pipeline can log and act on.

    Args:
        text: Document text to scan.

    Returns:
        List of signal dicts with pattern, severity, matched_text, context.
    """
    if not text:
        return []

    signals = []
    text_lower = text.lower()

    # Check if the text is primarily legitimate CTI/security content
    cti_word_count = sum(1 for word in _LEGITIMATE_CTI_CONTEXT if word in text_lower)
    is_cti_context = cti_word_count >= 3

    for pattern_name, pattern, severity in _INJECTION_SIGNALS:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            # Reduce severity for legitimate security content
            effective_severity = severity
            if is_cti_context and severity == "high":
                # CTI reports discussing attack techniques may mention these phrases
                # in descriptive context -- downgrade but still report
                if _is_descriptive_context(match.group(), text, match.start()):
                    effective_severity = "low"

            signals.append({
                "pattern": pattern_name,
                "severity": effective_severity,
                "matched_text": match.group()[:200],
                "position": match.start(),
                "context": text[max(0, match.start() - 40):match.end() + 40][:200],
            })

            logger.warning(
                "Injection signal '%s' (%s) at position %d: %s",
                pattern_name,
                effective_severity,
                match.start(),
                match.group()[:100],
            )

    return signals


def _is_descriptive_context(matched: str, full_text: str, match_pos: int) -> bool:
    """Check if a match appears in descriptive/analytical context.

    Reduces false positives when security reports discuss attack techniques
    that happen to use injection-like phrases.
    """
    # Get surrounding context window
    start = max(0, match_pos - 100)
    end = min(len(full_text), match_pos + len(matched) + 100)
    context = full_text[start:end].lower()

    # Descriptive framing indicators -- the text is ABOUT the technique
    descriptive_markers = [
        "the attacker", "threat actor", "adversary", "the malware",
        "the campaign", "was observed", "has been seen", "is known to",
        "technique involves", "method of", "in order to", "as part of",
        "the vulnerability", "researchers found", "analysis shows",
        "report indicates", "according to",
    ]
    return any(marker in context for marker in descriptive_markers)
