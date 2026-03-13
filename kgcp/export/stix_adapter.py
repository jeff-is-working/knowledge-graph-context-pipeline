"""STIX 2.1 bundle export adapter for KGCP."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import AttackPath, Entity, Triplet
from . import register_exporter
from .base import BaseExporter
from .entity_type_map import (
    entity_identity_class,
    stix_relationship_for_predicate,
    stix_type_for_entity,
)

# STIX 2.1 namespace for deterministic UUIDs
_STIX_NAMESPACE = uuid.UUID("00abedb4-aa42-466c-9c01-fed23315a9b7")


def _deterministic_id(sdo_type: str, *parts: str) -> str:
    """Generate a deterministic STIX ID from type + identifying parts."""
    seed = "|".join(parts)
    ns_uuid = uuid.uuid5(_STIX_NAMESPACE, seed)
    return f"{sdo_type}--{ns_uuid}"


def _parse_timestamp(iso_str: str) -> str:
    """Normalize an ISO timestamp to STIX format (UTC, Z suffix)."""
    if not iso_str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class STIXExporter(BaseExporter):
    """Export KGCP triplets as STIX 2.1 bundles."""

    def __init__(self, config: dict):
        super().__init__(config)
        stix_config = config.get("cti", {}).get("stix", {})
        self.default_confidence = stix_config.get("default_confidence", 50)
        self.identity_name = stix_config.get("identity_name", "KGCP")
        self._producer_id = _deterministic_id("identity", "kgcp-producer", self.identity_name)

    def _make_producer_identity(self) -> dict:
        """Create the STIX identity for KGCP as the producing tool."""
        return {
            "type": "identity",
            "spec_version": "2.1",
            "id": self._producer_id,
            "created": _parse_timestamp(""),
            "modified": _parse_timestamp(""),
            "name": self.identity_name,
            "identity_class": "system",
        }

    def _make_sdo(self, entity_name: str, entity_type: str) -> dict:
        """Create a STIX SDO from a KGCP entity."""
        sdo_type = stix_type_for_entity(entity_type)
        stix_id = _deterministic_id(sdo_type, entity_name, entity_type)

        sdo: dict[str, Any] = {
            "type": sdo_type,
            "spec_version": "2.1",
            "id": stix_id,
            "created": _parse_timestamp(""),
            "modified": _parse_timestamp(""),
            "name": entity_name,
            "created_by_ref": self._producer_id,
        }

        identity_class = entity_identity_class(entity_type)
        if identity_class:
            sdo["identity_class"] = identity_class

        if sdo_type == "malware":
            sdo["is_family"] = True

        return sdo

    def _make_sro(
        self,
        triplet: Triplet,
        entity_sdos: dict[str, dict],
    ) -> dict | None:
        """Create a STIX SRO (relationship) from a KGCP triplet."""
        rel_type, is_reversed = stix_relationship_for_predicate(triplet.predicate)

        source_name = triplet.object if is_reversed else triplet.subject
        target_name = triplet.subject if is_reversed else triplet.object

        source_sdo = entity_sdos.get(source_name)
        target_sdo = entity_sdos.get(target_name)
        if not source_sdo or not target_sdo:
            return None

        confidence = int(triplet.confidence * 100)

        sro: dict[str, Any] = {
            "type": "relationship",
            "spec_version": "2.1",
            "id": _deterministic_id(
                "relationship",
                source_sdo["id"], rel_type, target_sdo["id"],
                triplet.triplet_id,
            ),
            "created": _parse_timestamp(triplet.first_seen),
            "modified": _parse_timestamp(triplet.last_seen),
            "relationship_type": rel_type,
            "source_ref": source_sdo["id"],
            "target_ref": target_sdo["id"],
            "confidence": confidence,
            "created_by_ref": self._producer_id,
            "x_kgcp_triplet_id": triplet.triplet_id,
            "x_kgcp_predicate": triplet.predicate,
        }

        if triplet.observation_count > 1:
            sro["x_kgcp_observation_count"] = triplet.observation_count

        return sro

    def export_triplets(
        self,
        triplets: list[Triplet],
        entities: list[Entity] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Convert triplets to a STIX 2.1 bundle.

        Returns a dict representing the STIX bundle.
        """
        # Collect entity types
        entity_types = self._collect_entities(triplets)

        # Override with explicit entity list if provided
        if entities:
            for e in entities:
                entity_types[e.name] = e.entity_type

        # Build SDOs for all entities
        entity_sdos: dict[str, dict] = {}
        for name, etype in entity_types.items():
            entity_sdos[name] = self._make_sdo(name, etype)

        # Build SROs for all triplets
        sros: list[dict] = []
        for t in triplets:
            sro = self._make_sro(t, entity_sdos)
            if sro:
                sros.append(sro)

        # Assemble bundle
        objects: list[dict] = [self._make_producer_identity()]
        objects.extend(entity_sdos.values())
        objects.extend(sros)

        bundle = {
            "type": "bundle",
            "id": f"bundle--{uuid.uuid4()}",
            "objects": objects,
        }
        return bundle

    def export_attack_path(self, path: AttackPath, **kwargs: Any) -> dict:
        """Convert an attack path to a STIX 2.1 bundle.

        Includes a grouping SDO that references all path steps.
        """
        triplets = [step.triplet for step in path.steps]
        bundle = self.export_triplets(triplets, **kwargs)

        # Add a grouping object for the attack path
        step_sro_ids = [
            obj["id"] for obj in bundle["objects"]
            if obj["type"] == "relationship"
        ]

        if step_sro_ids:
            grouping = {
                "type": "grouping",
                "spec_version": "2.1",
                "id": _deterministic_id("grouping", path.seed_entity, "attack-path"),
                "created": _parse_timestamp(path.time_span[0] if path.time_span[0] else ""),
                "modified": _parse_timestamp(""),
                "name": f"Attack path from {path.seed_entity}",
                "context": "suspicious-activity",
                "object_refs": step_sro_ids,
                "created_by_ref": self._producer_id,
                "x_kgcp_seed_entity": path.seed_entity,
                "x_kgcp_total_anomaly": path.total_anomaly,
            }
            bundle["objects"].append(grouping)

        return bundle

    def to_file(self, data: Any, output_path: Path) -> None:
        """Write STIX bundle to JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# Register with the export system
register_exporter("stix", STIXExporter)
