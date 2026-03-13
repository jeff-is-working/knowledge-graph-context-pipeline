"""OpenCTI export adapter for KGCP.

Exports KGCP triplets as STIX 2.1 bundles enriched with OpenCTI-specific
extensions, and optionally pushes them to an OpenCTI instance via pycti
or the GraphQL REST API.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models import AttackPath, Entity, Triplet
from . import register_exporter
from .base import BaseExporter

logger = logging.getLogger(__name__)

IMPORT_BUNDLE_MUTATION = """
mutation ImportBundle($input: StixBundleAddInput!) {
  stixBundleAdd(input: $input) {
    id
    event_type
    context_data {
      id
      message
    }
  }
}
""".strip()


def _add_opencti_extensions(bundle: dict) -> dict:
    """Enrich STIX bundle objects with OpenCTI-specific extensions."""
    for obj in bundle.get("objects", []):
        obj_type = obj.get("type", "")
        if obj_type in ("relationship", "bundle"):
            continue

        confidence = obj.get("confidence")
        if confidence is not None:
            obj["x_opencti_score"] = int(confidence)
        elif "x_opencti_score" not in obj:
            obj["x_opencti_score"] = 50

    return bundle


class OpenCTIExporter(BaseExporter):
    """Export KGCP data as OpenCTI-compatible STIX 2.1 bundles.

    Composes a STIXExporter for base bundle generation, then layers
    OpenCTI extensions. Push supports pycti (preferred) or REST fallback.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        opencti_config = config.get("cti", {}).get("opencti", {})
        self.url: str = opencti_config.get("url", "")
        self.api_key: str = opencti_config.get("api_key", "")
        self.verify_ssl: bool = opencti_config.get("verify_ssl", True)
        self._stix_exporter: Any | None = None

    def _get_stix_exporter(self) -> Any:
        """Return a cached STIXExporter instance."""
        if self._stix_exporter is None:
            from .stix_adapter import STIXExporter
            self._stix_exporter = STIXExporter(self.config)
        return self._stix_exporter

    def export_triplets(
        self,
        triplets: list[Triplet],
        entities: list[Entity] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Convert triplets to an OpenCTI-enriched STIX 2.1 bundle."""
        stix = self._get_stix_exporter()
        bundle = stix.export_triplets(triplets, entities=entities, **kwargs)
        return _add_opencti_extensions(bundle)

    def export_attack_path(self, path: AttackPath, **kwargs: Any) -> dict:
        """Convert an attack path to an OpenCTI-enriched STIX 2.1 bundle."""
        stix = self._get_stix_exporter()
        bundle = stix.export_attack_path(path, **kwargs)
        return _add_opencti_extensions(bundle)

    def push(self, data: Any) -> dict:
        """Push STIX bundle to OpenCTI. Tries pycti first, REST fallback."""
        if not self.url:
            raise ValueError(
                "OpenCTI URL not configured. Set cti.opencti.url in "
                "config.toml or the KGCP_OPENCTI_URL environment variable."
            )
        if not self.api_key:
            raise ValueError(
                "OpenCTI API key not configured. Set cti.opencti.api_key in "
                "config.toml or the KGCP_OPENCTI_API_KEY environment variable."
            )

        bundle_json = json.dumps(data, default=str)

        # Strategy 1: pycti (preferred)
        try:
            from pycti import OpenCTIApiClient  # type: ignore[import-untyped]

            logger.info("Pushing STIX bundle to OpenCTI via pycti (%s)", self.url)
            client = OpenCTIApiClient(
                self.url, self.api_key, ssl_verify=self.verify_ssl,
            )
            client.stix2.import_bundle(bundle_json)
            logger.info("Successfully imported bundle via pycti")
            return {"status": "success", "method": "pycti"}
        except ImportError:
            logger.debug("pycti not installed; falling back to REST")
        except Exception:
            logger.exception("pycti import_bundle failed; falling back to REST")

        # Strategy 2: REST / GraphQL (fallback)
        import requests

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "query": IMPORT_BUNDLE_MUTATION,
            "variables": {"input": {"content": bundle_json}},
        }

        url = self.url.rstrip("/")
        logger.info("Pushing STIX bundle to OpenCTI via REST (%s/graphql)", url)
        resp = requests.post(
            f"{url}/graphql",
            json=payload,
            headers=headers,
            verify=self.verify_ssl,
            timeout=120,
        )
        resp.raise_for_status()

        result = resp.json()
        errors = result.get("errors")
        if errors:
            raw_err = json.dumps(errors, indent=2)
            raise RuntimeError(
                f"OpenCTI GraphQL errors: {self._sanitize_error(raw_err)}"
            )

        logger.info("Successfully imported bundle via REST GraphQL")
        return {"status": "success", "method": "rest"}

    def to_file(self, data: Any, output_path: Path) -> None:
        """Write OpenCTI-enriched STIX bundle to JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


register_exporter("opencti", OpenCTIExporter)
