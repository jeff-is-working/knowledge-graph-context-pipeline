"""KGCP entity types and predicates mapped to STIX 2.1 SDO/SRO types."""

from __future__ import annotations

# KGCP entity_type -> STIX 2.1 SDO type
ENTITY_TO_STIX_SDO: dict[str, str] = {
    "threat_actor": "threat-actor",
    "malware": "malware",
    "organization": "identity",
    "location": "location",
    "technique": "attack-pattern",
    "tool": "tool",
    "vulnerability": "vulnerability",
    "unknown": "identity",
}

# For SDOs that map to "identity", the identity_class value
_IDENTITY_CLASSES: dict[str, str] = {
    "organization": "organization",
    "unknown": "unknown",
}

# KGCP predicate -> (STIX relationship_type, is_reversed)
# is_reversed=True means subject/object swap in the SRO
PREDICATE_TO_STIX_REL: dict[str, tuple[str, bool]] = {
    "targets": ("targets", False),
    "exploits": ("exploits", False),
    "uses": ("uses", False),
    "deploys": ("uses", False),
    "installs": ("uses", False),
    "delivers": ("delivers", False),
    "compromises": ("compromises", False),
    "breaches": ("compromises", False),
    "infiltrates": ("compromises", False),
    "develops": ("authored-by", True),
    "creates": ("authored-by", True),
    "authors": ("authored-by", True),
    "controls": ("controls", False),
    "operates": ("controls", False),
    "connects to": ("communicates-with", False),
    "exfiltrates": ("exfiltrates-to", False),
    "attacks": ("targets", False),
    "funds": ("related-to", False),
    "owns": ("related-to", False),
    "produces": ("authored-by", True),
    "employs": ("uses", False),
    "leads": ("related-to", False),
    "manages": ("related-to", False),
}

DEFAULT_RELATIONSHIP = ("related-to", False)


def stix_type_for_entity(entity_type: str) -> str:
    """Return the STIX 2.1 SDO type for a KGCP entity type."""
    return ENTITY_TO_STIX_SDO.get(entity_type, "identity")


def entity_identity_class(entity_type: str) -> str | None:
    """Return identity_class if the SDO maps to 'identity', else None."""
    return _IDENTITY_CLASSES.get(entity_type)


def stix_relationship_for_predicate(predicate: str) -> tuple[str, bool]:
    """Return (STIX relationship_type, is_reversed) for a KGCP predicate.

    is_reversed=True means subject and object should be swapped
    when creating the STIX SRO (e.g., 'develops' becomes 'authored-by'
    with source/target flipped).
    """
    return PREDICATE_TO_STIX_REL.get(predicate.lower().strip(), DEFAULT_RELATIONSHIP)
