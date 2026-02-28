"""KGCP Command Line Interface.

Usage:
    kgcp ingest <file>              Ingest a document or directory
    kgcp query <text>               Query the knowledge graph
    kgcp stats                      Show graph statistics
    kgcp export                     Export the graph
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from .config import load_config
from .extraction.confidence import infer_entity_type
from .extraction.extractor import ingest_text
from .ingestion.chunker import chunk_text_paragraphs
from .ingestion.parser_registry import parse_file, supported_extensions
from .integration.output import output_context
from .models import Document, Entity, Triplet
from .packing.packer import pack_context
from .retrieval.retriever import Retriever
from .storage.graph_cache import GraphCache
from .storage.sqlite_store import SQLiteStore

logger = logging.getLogger("kgcp")


def _get_store(config: dict) -> SQLiteStore:
    db_path = config.get("storage", {}).get("db_path", "~/.kgcp/knowledge.db")
    return SQLiteStore(db_path)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(name)s: %(message)s",
        stream=sys.stderr,
    )


@click.group()
@click.option("--config", "config_path", default=None, help="Path to config.toml")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, config_path, verbose):
    """Knowledge Graph Context Pipeline — structured context for Claude."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--recursive", "-r", is_flag=True, help="Recurse into directories")
@click.option("--source-label", default=None, help="Custom label for the source")
@click.pass_context
def ingest(ctx, path, recursive, source_label):
    """Ingest a document or directory into the knowledge graph."""
    config = ctx.obj["config"]
    store = _get_store(config)

    target = Path(path)
    files: list[Path] = []

    if target.is_dir():
        if recursive:
            for ext in supported_extensions():
                files.extend(target.rglob(f"*.{ext}"))
        else:
            for ext in supported_extensions():
                files.extend(target.glob(f"*.{ext}"))
        if not files:
            click.echo(f"No supported files found in {target}", err=True)
            store.close()
            return
    else:
        files = [target]

    total_triplets = 0

    for file_path in sorted(files):
        click.echo(f"Ingesting: {file_path.name}", err=True)

        try:
            text = parse_file(file_path)
        except (ValueError, ImportError) as e:
            click.echo(f"  Skipping: {e}", err=True)
            continue

        if not text.strip():
            click.echo("  Skipping: empty file", err=True)
            continue

        # Create document record
        doc = Document(
            source_path=str(file_path.resolve()),
            metadata={"label": source_label} if source_label else {},
        )
        store.add_document(doc)

        # Create chunks
        chunk_size = config.get("chunking", {}).get("chunk_size", 100)
        overlap = config.get("chunking", {}).get("overlap", 20)
        chunks = chunk_text_paragraphs(
            text, doc.doc_id, str(file_path), chunk_size, overlap
        )
        store.add_chunks(chunks)

        # Extract triplets
        triplets = ingest_text(text, doc.doc_id, str(file_path), config)

        if triplets:
            # Add source_path to metadata for provenance
            for t in triplets:
                t.metadata["source_path"] = str(file_path.name)

            store.add_triplets(triplets)

            # Update entity records
            for t in triplets:
                for entity_name in (t.subject, t.object):
                    entity = Entity(
                        name=entity_name,
                        entity_type=infer_entity_type(entity_name),
                        doc_ids=[doc.doc_id],
                    )
                    store.upsert_entity(entity)

            total_triplets += len(triplets)
            click.echo(
                f"  Extracted {len(triplets)} triplets from {len(chunks)} chunks",
                err=True,
            )
        else:
            click.echo("  No triplets extracted", err=True)

    click.echo(f"\nTotal: {total_triplets} triplets from {len(files)} file(s)", err=True)
    store.close()


@cli.command()
@click.argument("query_text")
@click.option("--budget", "-b", default=2048, help="Token budget (default: 2048)")
@click.option(
    "--format", "-f", "fmt",
    default="yaml",
    type=click.Choice(["yaml", "compact", "markdown", "nl"], case_sensitive=False),
    help="Output format (default: yaml)",
)
@click.option("--hops", default=2, help="Graph traversal hops (default: 2)")
@click.option("--to-clipboard", is_flag=True, help="Copy to clipboard")
@click.option("--to-file", default=None, help="Write to file")
@click.pass_context
def query(ctx, query_text, budget, fmt, hops, to_clipboard, to_file):
    """Query the knowledge graph and get packed context."""
    config = ctx.obj["config"]
    store = _get_store(config)

    retriever = Retriever(store)
    triplets = retriever.query(query_text, hops=hops)

    if not triplets:
        click.echo("No matching triplets found.", err=True)
        store.close()
        return

    click.echo(
        f"Retrieved {len(triplets)} triplets, packing as {fmt}...",
        err=True,
    )

    packed = pack_context(triplets, format=fmt, budget=budget)
    output_context(packed, to_clipboard=to_clipboard, to_file=to_file)

    store.close()


@cli.command()
@click.option("--communities", is_flag=True, help="Show community breakdown")
@click.pass_context
def stats(ctx, communities):
    """Show knowledge graph statistics."""
    config = ctx.obj["config"]
    store = _get_store(config)

    db_stats = store.get_stats()
    click.echo("Knowledge Graph Statistics")
    click.echo("=" * 40)
    click.echo(f"Documents:          {db_stats['documents']}")
    click.echo(f"Chunks:             {db_stats['chunks']}")
    click.echo(f"Triplets:           {db_stats['triplets']}")
    click.echo(f"  Extracted:        {db_stats['extracted_triplets']}")
    click.echo(f"  Inferred:         {db_stats['inferred_triplets']}")
    click.echo(f"Entities:           {db_stats['entities']}")
    click.echo(f"Avg Confidence:     {db_stats['avg_confidence']}")

    if communities:
        click.echo("\nCommunity Analysis")
        click.echo("-" * 40)
        all_triplets = store.get_all_triplets()
        if all_triplets:
            cache = GraphCache()
            cache.build_from_triplets(all_triplets)
            graph_stats = cache.stats()
            click.echo(f"Graph Nodes:        {graph_stats['nodes']}")
            click.echo(f"Graph Edges:        {graph_stats['edges']}")
            click.echo(f"Communities:        {graph_stats['communities']}")
            click.echo(f"Density:            {graph_stats['density']}")

            comm_entities = cache.get_community_entities()
            for comm_id, entities in sorted(comm_entities.items()):
                click.echo(f"\n  Community {comm_id} ({len(entities)} entities):")
                for e in sorted(entities)[:10]:
                    click.echo(f"    - {e}")
                if len(entities) > 10:
                    click.echo(f"    ... and {len(entities) - 10} more")
        else:
            click.echo("No triplets in graph.")

    # Show recent documents
    docs = store.list_documents()
    if docs:
        click.echo(f"\nRecent Documents ({len(docs)} total):")
        for doc in docs[:5]:
            click.echo(f"  - {Path(doc.source_path).name} ({doc.ingested_at[:10]})")

    store.close()


@cli.command()
@click.option(
    "--format", "-f", "fmt",
    default="json",
    type=click.Choice(["json", "yaml", "compact"], case_sensitive=False),
    help="Export format",
)
@click.option("--output", "-o", default=None, help="Output file path")
@click.pass_context
def export(ctx, fmt, output):
    """Export the full knowledge graph."""
    import json

    config = ctx.obj["config"]
    store = _get_store(config)

    triplets = store.get_all_triplets()
    if not triplets:
        click.echo("No triplets to export.", err=True)
        store.close()
        return

    if fmt == "json":
        data = [
            {
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object,
                "confidence": t.confidence,
                "inferred": t.inferred,
                "doc_id": t.doc_id,
            }
            for t in triplets
        ]
        content = json.dumps(data, indent=2)
    elif fmt in ("yaml", "compact"):
        packed = pack_context(triplets, format=fmt, budget=999999)
        content = packed.content
    else:
        content = ""

    if output:
        Path(output).write_text(content)
        click.echo(f"Exported {len(triplets)} triplets to {output}", err=True)
    else:
        click.echo(content)

    store.close()


def main():
    cli()


if __name__ == "__main__":
    main()
