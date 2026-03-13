"""Abstract base class for CTI exporters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..models import AttackPath, Entity, Triplet


class BaseExporter(ABC):
    """Base class for all CTI platform exporters."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def export_triplets(
        self,
        triplets: list[Triplet],
        entities: list[Entity] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Convert triplets to platform-native format."""

    @abstractmethod
    def export_attack_path(self, path: AttackPath, **kwargs: Any) -> Any:
        """Convert an attack path to platform-native format."""

    def push(self, data: Any) -> dict:
        """Push exported data to remote platform. Override in subclasses."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support push")

    def to_file(self, data: Any, output_path: Path) -> None:
        """Write exported data to a file. Override for non-JSON formats."""
        import json

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _collect_entities(self, triplets: list[Triplet]) -> dict[str, str]:
        """Collect unique entity names from triplets and infer their types.

        Returns dict of entity_name -> entity_type.
        """
        from ..extraction.confidence import infer_entity_type

        entities: dict[str, str] = {}
        for t in triplets:
            if t.subject not in entities:
                entities[t.subject] = infer_entity_type(t.subject)
            if t.object not in entities:
                entities[t.object] = infer_entity_type(t.object)
        return entities
