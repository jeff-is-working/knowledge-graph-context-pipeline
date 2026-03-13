"""MISP event export adapter for KGCP."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models import AttackPath, Entity, Triplet
from . import register_exporter
from .base import BaseExporter

logger = logging.getLogger(__name__)

# KGCP entity_type -> (MISP attribute type, MISP category)
ENTITY_TO_MISP_ATTR: dict[str, tuple[str, str]] = {
    "threat_actor": ("threat-actor", "Attribution"),
    "malware": ("malware-type", "Payload delivery"),
    "vulnerability": ("vulnerability", "External analysis"),
    "tool": ("text", "Payload delivery"),
    "organization": ("target-org", "Targeting data"),
    "location": ("text", "Targeting data"),
    "technique": ("text", "External analysis"),
    "unknown": ("text", "Other"),
}


def _confidence_tag(confidence: float) -> str:
    """Map confidence score to MISP estimative-language tag."""
    if confidence >= 0.8:
        level = "high"
    elif confidence >= 0.5:
        level = "moderate"
    else:
        level = "low"
    return f'estimative-language:confidence-in-analytic-judgment="{level}"'


def _threat_level_from_anomaly(max_anomaly: float) -> int:
    """Map maximum anomaly score to MISP threat_level_id.

    1=high, 2=medium, 3=low, 4=undefined.
    """
    if max_anomaly >= 0.7:
        return 1
    if max_anomaly >= 0.4:
        return 2
    if max_anomaly >= 0.1:
        return 3
    return 4


def _misp_attr_for_entity(entity_type: str) -> tuple[str, str]:
    """Return (MISP attribute type, MISP category) for a KGCP entity type."""
    return ENTITY_TO_MISP_ATTR.get(entity_type, ("text", "Other"))


class MISPExporter(BaseExporter):
    """Export KGCP triplets as MISP events."""

    def __init__(self, config: dict):
        super().__init__(config)
        misp_config = config.get("cti", {}).get("misp", {})
        self.url = misp_config.get("url", "")
        self.api_key = misp_config.get("api_key", "")
        self.verify_ssl = misp_config.get("verify_ssl", True)
        self.default_distribution = misp_config.get("default_distribution", 0)
        self.default_threat_level = misp_config.get("default_threat_level", 2)
        self.default_analysis = misp_config.get("default_analysis", 0)
        self.publish_on_push = misp_config.get("publish_on_push", False)
        self._attack_mapper = None
        self._attack_data_path = config.get("cti", {}).get("attack_data_path", "")

    def _get_attack_mapper(self):
        """Return a cached AttackMapper instance, creating if needed."""
        if self._attack_mapper is None:
            from .attack_mapper import AttackMapper

            cache_path = Path(self._attack_data_path) if self._attack_data_path else None
            self._attack_mapper = AttackMapper(cache_path=cache_path)
        return self._attack_mapper

    def _build_tags(
        self,
        triplets: list[Triplet],
        attack_matches: dict[str, list] | None = None,
    ) -> list[dict[str, str]]:
        """Build MISP event-level tags from triplet data."""
        tags: list[dict[str, str]] = []
        seen: set[str] = set()

        if triplets:
            confidences = sorted(t.confidence for t in triplets)
            median = confidences[len(confidences) // 2]
            tag_name = _confidence_tag(median)
            if tag_name not in seen:
                tags.append({"name": tag_name})
                seen.add(tag_name)

        if attack_matches:
            for matches in attack_matches.values():
                for m in matches:
                    tag_name = f'mitre-attack:attack-pattern="{m.technique_id} - {m.technique_name}"'
                    if tag_name not in seen:
                        tags.append({"name": tag_name})
                        seen.add(tag_name)

        return tags

    def _triplet_to_attribute(
        self,
        triplet: Triplet,
        entity_types: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Convert a triplet into MISP attributes for subject and object."""
        attributes: list[dict[str, Any]] = []
        comment = f"{triplet.subject} {triplet.predicate} {triplet.object}"

        for entity_name in (triplet.subject, triplet.object):
            etype = entity_types.get(entity_name, "unknown")
            attr_type, category = _misp_attr_for_entity(etype)
            attr: dict[str, Any] = {
                "type": attr_type,
                "category": category,
                "value": entity_name,
                "comment": comment,
                "to_ids": attr_type in ("threat-actor", "malware-type", "vulnerability"),
            }
            attributes.append(attr)

        return attributes

    def export_triplets(
        self,
        triplets: list[Triplet],
        entities: list[Entity] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Convert triplets to a MISP event dict."""
        entity_types = self._collect_entities(triplets)
        if entities:
            for e in entities:
                entity_types[e.name] = e.entity_type

        max_anomaly = 0.0
        for t in triplets:
            anomaly = t.metadata.get("anomaly_score", 0.0)
            if anomaly > max_anomaly:
                max_anomaly = anomaly

        attack_matches: dict[str, list] = {}
        try:
            mapper = self._get_attack_mapper()
            attack_matches = mapper.match_triplets(triplets, max_results_per=3)
        except Exception:
            logger.debug("ATT&CK matching unavailable, skipping technique tags")

        attributes: list[dict[str, Any]] = []
        seen_attrs: set[tuple[str, str]] = set()
        for t in triplets:
            for attr in self._triplet_to_attribute(t, entity_types):
                key = (attr["type"], attr["value"])
                if key not in seen_attrs:
                    attributes.append(attr)
                    seen_attrs.add(key)

        threat_level = kwargs.get(
            "threat_level_id",
            _threat_level_from_anomaly(max_anomaly)
            if max_anomaly > 0
            else self.default_threat_level,
        )

        event: dict[str, Any] = {
            "Event": {
                "info": kwargs.get("info", "KGCP exported event"),
                "distribution": kwargs.get("distribution", self.default_distribution),
                "threat_level_id": threat_level,
                "analysis": kwargs.get("analysis", self.default_analysis),
                "Tag": self._build_tags(triplets, attack_matches),
                "Attribute": attributes,
            }
        }

        return event

    def export_attack_path(self, path: AttackPath, **kwargs: Any) -> dict:
        """Convert an attack path to a MISP event."""
        triplets = [step.triplet for step in path.steps]

        for step in path.steps:
            step.triplet.metadata["anomaly_score"] = step.anomaly_score

        max_anomaly = max(
            (step.anomaly_score for step in path.steps), default=0.0
        )

        info = kwargs.pop(
            "info",
            f"Attack path from {path.seed_entity} "
            f"({len(path.steps)} steps, anomaly={path.total_anomaly:.2f})",
        )

        event = self.export_triplets(
            triplets,
            info=info,
            threat_level_id=_threat_level_from_anomaly(max_anomaly),
            **kwargs,
        )

        event["Event"]["x_kgcp_seed_entity"] = path.seed_entity
        event["Event"]["x_kgcp_total_anomaly"] = path.total_anomaly
        if path.time_span[0]:
            event["Event"]["x_kgcp_time_start"] = path.time_span[0]
        if path.time_span[1]:
            event["Event"]["x_kgcp_time_end"] = path.time_span[1]

        return event

    def push(self, data: Any) -> dict:
        """Push a MISP event to a remote MISP instance via PyMISP."""
        try:
            from pymisp import MISPEvent, PyMISP  # type: ignore[import-untyped]
        except ImportError:
            raise ImportError(
                "PyMISP is required for push(). "
                "Install it with: pip install kgcp[cti-platforms]"
            )

        if not self.url or not self.api_key:
            raise ValueError(
                "MISP URL and API key must be configured. "
                "Set cti.misp.url and cti.misp.api_key in config, or "
                "use KGCP_MISP_URL and KGCP_MISP_API_KEY environment variables."
            )

        misp = PyMISP(self.url, self.api_key, ssl=self.verify_ssl)

        misp_event = MISPEvent()
        misp_event.from_dict(**data.get("Event", data))

        response = misp.add_event(misp_event)

        if isinstance(response, dict) and "errors" in response:
            raise RuntimeError(f"MISP push failed: {response['errors']}")

        event_id = ""
        if isinstance(response, dict):
            event_id = str(response.get("Event", {}).get("id", ""))
        elif hasattr(response, "id"):
            event_id = str(response.id)

        if self.publish_on_push and event_id:
            misp.publish(event_id)
            logger.info("Published MISP event %s", event_id)

        logger.info("Pushed event to MISP: %s", event_id or "unknown id")
        return {"status": "success", "event_id": event_id}

    def to_file(self, data: Any, output_path: Path) -> None:
        """Write MISP event JSON to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


register_exporter("misp", MISPExporter)
