"""TAXII 2.1 read-only server for KGCP STIX bundle distribution.

Implements the TAXII 2.1 specification (OASIS) endpoints:
  - GET  /taxii2/              Discovery
  - GET  /api/                 API Root
  - GET  /api/collections/     List collections
  - GET  /api/collections/{id}/           Collection detail
  - GET  /api/collections/{id}/objects/   Get STIX objects
  - GET  /api/collections/{id}/manifest/  Object manifest

All endpoints are read-only. Authentication via API key in header.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..config import load_config
from ..export.base import BaseExporter

logger = logging.getLogger(__name__)

TAXII_CONTENT_TYPE = "application/taxii+json;version=2.1"
STIX_CONTENT_TYPE = "application/stix+json;version=2.1"

# Default collection for all KGCP triplets
DEFAULT_COLLECTION_ID = "kgcp-all-triplets"
DEFAULT_COLLECTION_TITLE = "KGCP All Triplets"
DEFAULT_COLLECTION_DESCRIPTION = (
    "All triplets from the KGCP knowledge graph, exported as STIX 2.1 objects."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def create_app(config: dict | None = None) -> Any:
    """Create and configure the TAXII 2.1 FastAPI application.

    Args:
        config: KGCP config dict. If None, loads from default locations.

    Returns:
        FastAPI application instance.
    """
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError(
            "FastAPI and uvicorn are required for the TAXII server. "
            "Install with: pip install kgcp[taxii]"
        )

    if config is None:
        config = load_config()

    taxii_config = config.get("cti", {}).get("taxii", {})
    api_key = taxii_config.get("api_key", "")
    server_title = taxii_config.get("title", "KGCP TAXII 2.1 Server")
    api_root_path = "/api"
    max_content_length = taxii_config.get("max_content_length", 10_000_000)

    app = FastAPI(
        title=server_title,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # --- Auth dependency ---

    async def verify_api_key(authorization: str | None = Header(None)):
        """Validate API key from Authorization header if configured."""
        if not api_key:
            return  # No auth configured — open server
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization header required")
        # Accept "Bearer <key>" or raw key
        token = authorization
        if token.lower().startswith("bearer "):
            token = token[7:]
        if token != api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

    # --- TAXII responses ---

    def taxii_response(data: dict, content_type: str = TAXII_CONTENT_TYPE) -> JSONResponse:
        return JSONResponse(content=data, headers={"Content-Type": content_type})

    # --- Helper: build STIX bundle from store ---

    def _get_stix_bundle(
        added_after: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """Generate a STIX bundle from the triplet store."""
        from ..export.stix_adapter import STIXExporter
        from ..storage.sqlite_store import SQLiteStore

        store = SQLiteStore(config["storage"]["db_path"])
        try:
            triplets = store.get_all_triplets()
        finally:
            store.close()

        # Filter by added_after if provided
        if added_after and triplets:
            triplets = [
                t for t in triplets
                if t.first_seen and t.first_seen >= added_after
            ]

        # Apply limit
        if limit and limit > 0:
            triplets = triplets[:limit]

        if not triplets:
            return {
                "type": "bundle",
                "id": "bundle--empty",
                "objects": [],
            }

        exporter = STIXExporter(config)
        return exporter.export_triplets(triplets)

    def _get_manifest(added_after: str | None = None, limit: int | None = None) -> list[dict]:
        """Build manifest entries from the triplet store."""
        from ..storage.sqlite_store import SQLiteStore

        store = SQLiteStore(config["storage"]["db_path"])
        try:
            triplets = store.get_all_triplets()
        finally:
            store.close()

        if added_after and triplets:
            triplets = [
                t for t in triplets
                if t.first_seen and t.first_seen >= added_after
            ]

        if limit and limit > 0:
            triplets = triplets[:limit]

        entries: list[dict] = []
        for t in triplets:
            obj_id = hashlib.sha256(
                f"{t.subject}|{t.predicate}|{t.object}".encode()
            ).hexdigest()[:16]
            entries.append({
                "id": f"relationship--{obj_id}",
                "date_added": t.first_seen or _now_iso(),
                "version": t.last_seen or t.first_seen or _now_iso(),
                "media_type": STIX_CONTENT_TYPE,
            })
        return entries

    # --- Collection info ---

    def _collection_info(can_read: bool = True) -> dict:
        return {
            "id": DEFAULT_COLLECTION_ID,
            "title": DEFAULT_COLLECTION_TITLE,
            "description": DEFAULT_COLLECTION_DESCRIPTION,
            "can_read": can_read,
            "can_write": False,
            "media_types": [STIX_CONTENT_TYPE],
        }

    # --- Routes ---

    @app.get("/taxii2/")
    async def discovery(_: None = Depends(verify_api_key)):
        """TAXII 2.1 Discovery endpoint."""
        return taxii_response({
            "title": server_title,
            "description": "KGCP TAXII 2.1 server for STIX bundle distribution",
            "default": f"{api_root_path}/",
            "api_roots": [f"{api_root_path}/"],
        })

    @app.get(f"{api_root_path}/")
    async def api_root(_: None = Depends(verify_api_key)):
        """TAXII 2.1 API Root endpoint."""
        return taxii_response({
            "title": server_title,
            "description": "KGCP knowledge graph STIX objects",
            "versions": ["application/taxii+json;version=2.1"],
            "max_content_length": max_content_length,
        })

    @app.get(f"{api_root_path}/collections/")
    async def list_collections(_: None = Depends(verify_api_key)):
        """TAXII 2.1 Collections endpoint."""
        return taxii_response({
            "collections": [_collection_info()],
        })

    @app.get(f"{api_root_path}/collections/{{collection_id}}/")
    async def get_collection(
        collection_id: str, _: None = Depends(verify_api_key)
    ):
        """TAXII 2.1 Collection detail endpoint."""
        if collection_id != DEFAULT_COLLECTION_ID:
            raise HTTPException(status_code=404, detail="Collection not found")
        return taxii_response(_collection_info())

    @app.get(f"{api_root_path}/collections/{{collection_id}}/objects/")
    async def get_objects(
        collection_id: str,
        added_after: str | None = Query(None),
        limit: int | None = Query(None, ge=1, le=10000),
        _: None = Depends(verify_api_key),
    ):
        """TAXII 2.1 Get Objects endpoint — returns STIX 2.1 bundle."""
        if collection_id != DEFAULT_COLLECTION_ID:
            raise HTTPException(status_code=404, detail="Collection not found")

        bundle = _get_stix_bundle(added_after=added_after, limit=limit)
        return taxii_response(bundle, content_type=STIX_CONTENT_TYPE)

    @app.get(f"{api_root_path}/collections/{{collection_id}}/manifest/")
    async def get_manifest(
        collection_id: str,
        added_after: str | None = Query(None),
        limit: int | None = Query(None, ge=1, le=10000),
        _: None = Depends(verify_api_key),
    ):
        """TAXII 2.1 Manifest endpoint."""
        if collection_id != DEFAULT_COLLECTION_ID:
            raise HTTPException(status_code=404, detail="Collection not found")

        entries = _get_manifest(added_after=added_after, limit=limit)
        return taxii_response({"objects": entries})

    return app


def run_server(config: dict | None = None, host: str = "127.0.0.1", port: int = 9500):
    """Run the TAXII server with uvicorn."""
    try:
        import uvicorn
    except ImportError:
        raise ImportError(
            "uvicorn is required to run the TAXII server. "
            "Install with: pip install kgcp[taxii]"
        )

    app = create_app(config)
    logger.info("Starting KGCP TAXII 2.1 server on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
