"""Post-extraction validation to detect prompt injection in extracted triplets.

Scans extracted SPO triplets for indicators that the source document contained
adversarial content that manipulated the LLM during extraction. Adapted from
the image-to-knowledge validator.py defense pattern.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Patterns scanned across triplet field values (subject, predicate, object).
# Each tuple: (pattern_name, regex, severity)
_TRIPLET_PATTERNS = [
    # Instruction manipulation embedded in triplet fields
    (
        "instruction_override",
        r"\b(?:ignore (?:all |previous |prior |above )?(?:instructions?|rules?|prompts?)?"
        r"|disregard (?:all|previous|prior|above)"
        r"|new instructions|override instructions?"
        r"|instead (?:extract|do|output)"
        r"|must ignore(?:\s+\w+)*)\b",
        "high",
    ),
    # Role / identity hijack
    (
        "role_override",
        r"\b(?:you are (?:now )?|act as |pretend to be |assume the role)\b",
        "high",
    ),
    # System prompt references
    (
        "system_prompt_ref",
        r"\b(?:system prompt|system message|system instruction"
        r"|reveal (?:your )?instructions?|output (?:your )?prompt)\b",
        "high",
    ),
    # Data exfiltration patterns
    (
        "exfil_attempt",
        r"\b(?:send (?:to|data)|post to|upload to|webhook|callback|exfiltrate)\b",
        "medium",
    ),
    # URLs in triplet fields (entities should not contain full URLs)
    (
        "url_in_entity",
        r"https?://[^\s]{10,}",
        "medium",
    ),
    # Encoded payloads
    (
        "encoded_payload",
        r"(?:0x[0-9a-fA-F]{20,}|\\x[0-9a-fA-F]{2}(?:\\x[0-9a-fA-F]{2}){9,})",
        "medium",
    ),
    # LLM-specific references that should not appear in knowledge triplets
    (
        "llm_reference",
        r"\b(?:anthropic|openai|gpt-?\d|claude)\b.*\b(?:instruction|prompt|ignore|system)\b",
        "high",
    ),
]

# Maximum reasonable entity name length (words)
MAX_ENTITY_WORDS = 10

_SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


@dataclass
class Finding:
    """A single injection pattern match in a triplet."""

    pattern_name: str
    severity: str
    matched_text: str
    field: str  # "subject", "predicate", or "object"
    triplet_index: int
    context: str  # "subject -> predicate -> object" summary


@dataclass
class ValidationResult:
    """Result of validating extracted triplets for injection patterns."""

    clean: bool = True
    findings: list[Finding] = field(default_factory=list)
    severity: str = "none"  # none, low, medium, high
    flagged_indices: list[int] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        """Whether this batch should be flagged for review."""
        return self.severity in ("medium", "high")


def validate_triplets(triplets: list[dict]) -> ValidationResult:
    """Scan extracted triplets for prompt injection indicators.

    Checks each triplet's subject, predicate, and object fields against
    known injection patterns. Also validates structural integrity.

    Args:
        triplets: List of dicts with subject/predicate/object keys.

    Returns:
        ValidationResult with findings, severity, and flagged triplet indices.
    """
    result = ValidationResult()

    if not triplets:
        return result

    max_severity = "none"
    flagged = set()

    for idx, triplet in enumerate(triplets):
        subject = str(triplet.get("subject", ""))
        predicate = str(triplet.get("predicate", ""))
        obj = str(triplet.get("object", ""))
        context = f"{subject} -> {predicate} -> {obj}"

        # Structural checks
        for field_name, value in [("subject", subject), ("predicate", predicate), ("object", obj)]:
            # Empty field check
            if not value.strip():
                finding = Finding(
                    pattern_name="empty_field",
                    severity="medium",
                    matched_text=f"empty {field_name}",
                    field=field_name,
                    triplet_index=idx,
                    context=context,
                )
                result.findings.append(finding)
                flagged.add(idx)
                if _SEVERITY_ORDER["medium"] > _SEVERITY_ORDER.get(max_severity, 0):
                    max_severity = "medium"

        # Entity length check (subject and object only)
        for field_name, value in [("subject", subject), ("object", obj)]:
            word_count = len(value.split())
            if word_count > MAX_ENTITY_WORDS:
                finding = Finding(
                    pattern_name="entity_length",
                    severity="medium",
                    matched_text=f"{field_name} has {word_count} words (max {MAX_ENTITY_WORDS})",
                    field=field_name,
                    triplet_index=idx,
                    context=context,
                )
                result.findings.append(finding)
                flagged.add(idx)
                if _SEVERITY_ORDER["medium"] > _SEVERITY_ORDER.get(max_severity, 0):
                    max_severity = "medium"

        # Pattern matching across all fields
        for field_name, value in [("subject", subject), ("predicate", predicate), ("object", obj)]:
            for pattern_name, pattern, severity in _TRIPLET_PATTERNS:
                matches = list(re.finditer(pattern, value, re.IGNORECASE | re.DOTALL))
                for match in matches:
                    finding = Finding(
                        pattern_name=pattern_name,
                        severity=severity,
                        matched_text=match.group()[:200],
                        field=field_name,
                        triplet_index=idx,
                        context=context[:200],
                    )
                    result.findings.append(finding)
                    flagged.add(idx)

                    if _SEVERITY_ORDER.get(severity, 0) > _SEVERITY_ORDER.get(max_severity, 0):
                        max_severity = severity

                    logger.warning(
                        "Triplet %d: injection pattern '%s' (%s) in %s: %s",
                        idx,
                        pattern_name,
                        severity,
                        field_name,
                        match.group()[:100],
                    )

    result.severity = max_severity
    result.clean = len(result.findings) == 0
    result.flagged_indices = sorted(flagged)

    if result.findings:
        logger.warning(
            "Validation found %d suspicious patterns in %d triplets "
            "(max severity: %s)",
            len(result.findings),
            len(result.flagged_indices),
            max_severity,
        )

    return result


def format_validation_report(result: ValidationResult) -> str:
    """Format a validation result as a human-readable report.

    Args:
        result: The ValidationResult to format.

    Returns:
        Formatted string report.
    """
    if result.clean:
        return "Validation: CLEAN -- no injection patterns detected."

    lines = [
        f"Validation: {result.severity.upper()} -- "
        f"{len(result.findings)} suspicious pattern(s) in "
        f"{len(result.flagged_indices)} triplet(s).",
        "",
    ]

    for i, finding in enumerate(result.findings, 1):
        lines.append(f"  {i}. [{finding.severity.upper()}] {finding.pattern_name}")
        lines.append(f"     Triplet {finding.triplet_index}, field '{finding.field}': {finding.matched_text}")
        lines.append(f"     Context: {finding.context}")
        lines.append("")

    if result.flagged:
        lines.append(
            "ACTION: Flagged triplets should be reviewed before storage. "
            "Use force=True to override."
        )

    return "\n".join(lines)
