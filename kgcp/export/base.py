"""Abstract base class for CTI exporters."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..models import AttackPath, Entity, Triplet

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

MAX_ENTITY_NAME_LEN = 512
MAX_ERROR_MSG_LEN = 1000


class BaseExporter(ABC):
    """Base class for all CTI platform exporters."""

    def __init__(self, config: dict):
        self.config = config

    @staticmethod
    def _sanitize_entity_name(name: str) -> str:
        """Sanitize an entity name before sending to external APIs.

        Strips control characters, ANSI escapes, and enforces max length.
        """
        name = _ANSI_ESCAPE_RE.sub("", name)
        name = _CONTROL_CHAR_RE.sub("", name)
        name = name.strip()
        if len(name) > MAX_ENTITY_NAME_LEN:
            name = name[:MAX_ENTITY_NAME_LEN]
        return name

    @staticmethod
    def _sanitize_error(message: str) -> str:
        """Sanitize an error message from a remote server.

        Strips ANSI escapes, control characters, and truncates.
        """
        message = _ANSI_ESCAPE_RE.sub("", message)
        message = _CONTROL_CHAR_RE.sub("", message)
        if len(message) > MAX_ERROR_MSG_LEN:
            message = message[:MAX_ERROR_MSG_LEN] + "... (truncated)"
        return message

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
            subj = self._sanitize_entity_name(t.subject)
            obj = self._sanitize_entity_name(t.object)
            if subj not in entities:
                entities[subj] = infer_entity_type(subj)
            if obj not in entities:
                entities[obj] = infer_entity_type(obj)
        return entities
