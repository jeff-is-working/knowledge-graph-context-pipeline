"""TheHive alert export adapter for KGCP."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import AttackPath, Entity, Triplet
from . import register_exporter
from .base import BaseExporter

logger = logging.getLogger(__name__)

# KGCP entity type -> (TheHive observable dataType, type tag)
_ENTITY_TYPE_TO_OBSERVABLE: dict[str, tuple[str, str]] = {
    "threat_actor": ("other", "type:threat-actor"),
    "malware": ("other", "type:malware"),
    "vulnerability": ("other", "type:vulnerability"),
    "tool": ("other", "type:tool"),
    "organization": ("other", "type:organization"),
    "location": ("other", "type:location"),
    "technique": ("other", "type:technique"),
    "unknown": ("other", "type:unknown"),
}

_DEFAULT_OBSERVABLE = ("other", "type:unknown")


def _anomaly_to_severity(max_anomaly: float) -> int:
    """Map anomaly score to TheHive severity (1=low, 2=med, 3=high, 4=critical)."""
    if max_anomaly >= 0.8:
        return 4
    if max_anomaly >= 0.6:
        return 3
    if max_anomaly >= 0.3:
        return 2
    return 1


def _make_source_ref(seed_entity: str, timestamp: str) -> str:
    """Generate a deterministic sourceRef from seed entity and timestamp."""
    content = f"{seed_entity}|{timestamp}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _build_description(
    triplets: list[Triplet],
    entity_types: dict[str, str],
    time_span: tuple[str, str] | None = None,
) -> str:
    """Build a concise natural language description from triplets."""
    if not triplets:
        return "No triplets available."

    lines: list[str] = []

    # Entities by type
    typed: dict[str, list[str]] = {}
    for name, etype in sorted(entity_types.items()):
        typed.setdefault(etype, []).append(name)

    entity_parts: list[str] = []
    for etype, names in sorted(typed.items()):
        label = etype.replace("_", " ")
        if len(names) == 1:
            entity_parts.append(f"{names[0]} ({label})")
        else:
            entity_parts.append(f"{', '.join(sorted(names))} ({label}s)")
    if entity_parts:
        lines.append("Entities involved: " + "; ".join(entity_parts) + ".")

    # Key relationships (up to 10)
    rel_summaries: list[str] = []
    for t in triplets[:10]:
        rel_summaries.append(f"{t.subject} {t.predicate} {t.object}")
    if rel_summaries:
        lines.append("Key relationships: " + "; ".join(rel_summaries) + ".")
    if len(triplets) > 10:
        lines.append(f"({len(triplets)} total relationships.)")

    # Time span
    if time_span and time_span[0] and time_span[1]:
        start = time_span[0][:10]
        end = time_span[1][:10]
        if start == end:
            lines.append(f"Observed on {start}.")
        else:
            lines.append(f"Time span: {start} to {end}.")

    return "\n".join(lines)


def _compute_time_span(triplets: list[Triplet]) -> tuple[str, str]:
    """Determine earliest first_seen and latest last_seen."""
    first_times = [t.first_seen for t in triplets if t.first_seen]
    last_times = [t.last_seen for t in triplets if t.last_seen]
    return (min(first_times) if first_times else "", max(last_times) if last_times else "")


class TheHiveExporter(BaseExporter):
    """Export KGCP triplets and attack paths as TheHive alerts."""

    def __init__(self, config: dict):
        super().__init__(config)
        thehive_config = config.get("cti", {}).get("thehive", {})
        self.url = thehive_config.get("url", "")
        self.api_key = thehive_config.get("api_key", "")
        self.verify_ssl = thehive_config.get("verify_ssl", True)
        self.timeout = thehive_config.get("timeout", 120)
        self.default_severity = thehive_config.get("default_severity", 2)
        self.default_tlp = thehive_config.get("default_tlp", 2)

    def _make_observable(
        self, entity_name: str, entity_type: str, triplets: list[Triplet]
    ) -> dict:
        """Create a TheHive observable dict for an entity."""
        entity_name = self._sanitize_entity_name(entity_name)
        data_type, type_tag = _ENTITY_TYPE_TO_OBSERVABLE.get(
            entity_type, _DEFAULT_OBSERVABLE
        )

        context_parts: list[str] = []
        for t in triplets:
            subj = self._sanitize_entity_name(t.subject)
            obj = self._sanitize_entity_name(t.object)
            if subj == entity_name or obj == entity_name:
                context_parts.append(f"{subj} {t.predicate} {obj}")
        message = "; ".join(context_parts[:5]) if context_parts else ""

        tags = [type_tag]
        if entity_type != "unknown":
            tags.append(f"entity:{entity_name}")

        return {
            "dataType": data_type,
            "data": entity_name,
            "message": message,
            "tags": tags,
        }

    def _compute_max_anomaly(self, triplets: list[Triplet]) -> float:
        """Find the maximum anomaly score across all triplets."""
        max_score = 0.0
        for t in triplets:
            score = t.metadata.get("anomaly_score", 0.0)
            if isinstance(score, (int, float)) and score > max_score:
                max_score = score
        return max_score

    def export_triplets(
        self,
        triplets: list[Triplet],
        entities: list[Entity] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Convert triplets to a TheHive alert dict."""
        if not triplets:
            return {
                "title": "KGCP Alert (empty)",
                "description": "No triplets provided.",
                "severity": self.default_severity,
                "tlp": self.default_tlp,
                "type": "kgcp-alert",
                "source": "KGCP",
                "sourceRef": _make_source_ref("empty", datetime.now(timezone.utc).isoformat()),
                "tags": [],
                "observables": [],
            }

        entity_types = self._collect_entities(triplets)
        if entities:
            for e in entities:
                entity_types[e.name] = e.entity_type

        time_span = _compute_time_span(triplets)
        seed_entity = triplets[0].subject

        # Title
        title = kwargs.get("title")
        if not title:
            span_label = ""
            if time_span[0] and time_span[1]:
                start = time_span[0][:10]
                end = time_span[1][:10]
                span_label = f" ({start} to {end})" if start != end else f" ({start})"
            title = f"KGCP: {seed_entity}{span_label}"

        # Severity
        max_anomaly = self._compute_max_anomaly(triplets)
        severity = kwargs.get("severity", _anomaly_to_severity(max_anomaly))
        if max_anomaly == 0.0 and "severity" not in kwargs:
            severity = self.default_severity

        tlp = kwargs.get("tlp", self.default_tlp)

        # Tags
        tags: list[str] = sorted({etype for etype in entity_types.values() if etype != "unknown"})

        source_ref = _make_source_ref(seed_entity, datetime.now(timezone.utc).isoformat())
        description = _build_description(triplets, entity_types, time_span)

        observables: list[dict] = []
        for name, etype in sorted(entity_types.items()):
            observables.append(self._make_observable(name, etype, triplets))

        return {
            "title": title,
            "description": description,
            "severity": severity,
            "tlp": tlp,
            "type": "kgcp-alert",
            "source": "KGCP",
            "sourceRef": source_ref,
            "tags": tags,
            "observables": observables,
        }

    def export_attack_path(self, path: AttackPath, **kwargs: Any) -> dict:
        """Convert an attack path to a TheHive alert dict."""
        triplets = [step.triplet for step in path.steps]

        max_anomaly = max(
            (step.anomaly_score for step in path.steps), default=0.0
        )
        if path.total_anomaly > max_anomaly:
            max_anomaly = path.total_anomaly

        severity = kwargs.get("severity", _anomaly_to_severity(max_anomaly))

        # Title
        span_label = ""
        if path.time_span[0] and path.time_span[1]:
            start = path.time_span[0][:10]
            end = path.time_span[1][:10]
            span_label = f" ({start} to {end})" if start != end else f" ({start})"
        title = kwargs.get("title", f"KGCP Attack Path: {path.seed_entity}{span_label}")

        entity_types = self._collect_entities(triplets)

        # Description
        desc_lines: list[str] = [
            f"Attack path reconstructed from seed entity: {path.seed_entity}.",
            f"Steps: {len(path.steps)}. Total anomaly score: {path.total_anomaly:.2f}.",
        ]
        if path.entities_involved:
            desc_lines.append(
                f"Entities involved: {', '.join(sorted(path.entities_involved))}."
            )
        base_desc = _build_description(triplets, entity_types, path.time_span)
        desc_lines.append("")
        desc_lines.append(base_desc)
        description = "\n".join(desc_lines)

        tags: list[str] = ["attack-path"]
        tags.extend(sorted({etype for etype in entity_types.values() if etype != "unknown"}))

        source_ref = _make_source_ref(path.seed_entity, datetime.now(timezone.utc).isoformat())

        observables: list[dict] = []
        for name, etype in sorted(entity_types.items()):
            observables.append(self._make_observable(name, etype, triplets))

        return {
            "title": title,
            "description": description,
            "severity": severity,
            "tlp": kwargs.get("tlp", self.default_tlp),
            "type": "kgcp-alert",
            "source": "KGCP",
            "sourceRef": source_ref,
            "tags": tags,
            "observables": observables,
        }

    def push(self, data: dict) -> dict:
        """Push an alert to TheHive via thehive4py."""
        try:
            from thehive4py import TheHiveApi
            from thehive4py.models import Alert, AlertArtifact
        except ImportError:
            raise ImportError(
                "thehive4py required for push. "
                "Install: pip install kgcp[cti-platforms]"
            )

        if not self.url:
            raise ValueError(
                "TheHive URL not configured. "
                "Set cti.thehive.url in config.toml or KGCP_THEHIVE_URL env var."
            )
        if not self.api_key:
            raise ValueError(
                "TheHive API key not configured. "
                "Set cti.thehive.api_key in config.toml or KGCP_THEHIVE_API_KEY env var."
            )

        api = TheHiveApi(self.url, self.api_key, cert=self.verify_ssl)
        api.session.timeout = self.timeout

        artifacts: list = []
        for obs in data.get("observables", []):
            artifact = AlertArtifact(
                dataType=obs["dataType"],
                data=obs["data"],
                message=obs.get("message", ""),
                tags=obs.get("tags", []),
            )
            artifacts.append(artifact)

        alert = Alert(
            title=data["title"],
            description=data["description"],
            severity=data["severity"],
            tlp=data["tlp"],
            type=data["type"],
            source=data["source"],
            sourceRef=data["sourceRef"],
            tags=data.get("tags", []),
            artifacts=artifacts,
        )

        response = api.create_alert(alert)
        if response.status_code in (200, 201):
            logger.info("Alert created in TheHive: %s", data["title"])
            return response.json()

        sanitized_msg = self._sanitize_error(response.text)
        logger.error(
            "Failed to create alert: %s %s",
            response.status_code, sanitized_msg,
        )
        return {
            "error": True,
            "status_code": response.status_code,
            "message": sanitized_msg,
        }

    def to_file(self, data: Any, output_path: Path) -> None:
        """Write TheHive alert JSON to a file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


register_exporter("thehive", TheHiveExporter)
