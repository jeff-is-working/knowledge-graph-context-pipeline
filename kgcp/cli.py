"""KGCP Command Line Interface.

Usage:
    kgcp ingest <file>              Ingest a document or directory
    kgcp query <text>               Query the knowledge graph
    kgcp stats                      Show graph statistics
    kgcp export                     Export the graph
    kgcp baseline create            Snapshot current graph
    kgcp baseline list              Show all baselines
    kgcp baseline show [ID]         Show baseline details
    kgcp baseline delete ID         Delete a baseline
    kgcp anomalies                  Surface anomalous relationships
    kgcp paths <entity>             Reconstruct attack paths
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from .anomaly.detector import AnomalyDetector
from .config import load_config
from .extraction.confidence import infer_entity_type
from .extraction.extractor import extract_from_chunks, ingest_text
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

        # Extract triplets using the same chunks stored in DB
        triplets = extract_from_chunks(chunks, config)

        if triplets:
            # Add source_path to metadata for provenance
            for t in triplets:
                t.metadata["source_path"] = str(file_path.name)

            store.upsert_triplets(triplets)

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
@click.option("--anomalies", is_flag=True, help="Include anomaly scores in output")
@click.option("--since", default=None, help="Filter triplets observed after this date (ISO, quarter, or relative like 90d)")
@click.option("--until", default=None, help="Filter triplets first seen before this date (ISO, quarter, or relative)")
@click.option("--unified", is_flag=True, help="Enable cross-algebra unified scoring")
@click.option("--min-anomaly", default=None, type=float, help="Minimum anomaly score threshold")
@click.pass_context
def query(ctx, query_text, budget, fmt, hops, to_clipboard, to_file, anomalies, since, until, unified, min_anomaly):
    """Query the knowledge graph and get packed context."""
    from .temporal.date_utils import parse_date

    config = ctx.obj["config"]
    store = _get_store(config)

    # Parse temporal filters
    parsed_since = None
    parsed_until = None
    if since:
        try:
            parsed_since = parse_date(since)
        except ValueError as e:
            click.echo(f"Invalid --since value: {e}", err=True)
            store.close()
            return
    if until:
        try:
            parsed_until = parse_date(until)
        except ValueError as e:
            click.echo(f"Invalid --until value: {e}", err=True)
            store.close()
            return

    # Read fusion weights from config
    fusion_weights = None
    if unified:
        fusion_weights = config.get("fusion", {}).get("weights")

    retriever = Retriever(store)
    triplets = retriever.query(
        query_text, hops=hops, include_anomaly_scores=anomalies,
        since=parsed_since, until=parsed_until,
        unified_scoring=unified, fusion_weights=fusion_weights,
        min_anomaly_score=min_anomaly,
    )

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
@click.option("--anomalies", is_flag=True, help="Show anomaly summary")
@click.pass_context
def stats(ctx, communities, anomalies):
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

    if anomalies:
        click.echo("\nAnomaly Summary")
        click.echo("-" * 40)
        detector = AnomalyDetector(store)
        bl = detector.get_latest_baseline()
        if bl:
            click.echo(f"Latest Baseline:    {bl.baseline_id[:8]}... ({bl.created_at[:10]})")
            min_score = config.get("anomaly", {}).get("min_display_score", 0.3)
            scores = store.get_anomaly_scores(min_score=min_score, baseline_id=bl.baseline_id, limit=10)
            if scores:
                click.echo(f"Anomalous Triplets: {len(scores)} (score >= {min_score})")
                for r in scores[:5]:
                    click.echo(f"  {r.score:.2f}  {r.subject} -> {r.predicate} -> {r.object}")
            else:
                click.echo("No anomalous triplets found. Run 'kgcp anomalies' to score.")
        else:
            click.echo("No baseline. Run 'kgcp baseline create' first.")

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


@cli.group()
def baseline():
    """Manage graph baselines for anomaly detection."""
    pass


@baseline.command("create")
@click.option("--label", "-l", default="", help="Label for the baseline")
@click.pass_context
def baseline_create(ctx, label):
    """Snapshot the current graph as a baseline."""
    config = ctx.obj["config"]
    store = _get_store(config)
    detector = AnomalyDetector(store)

    bl = detector.create_and_save_baseline(label=label)
    click.echo(f"Baseline created: {bl.baseline_id[:8]}...")
    click.echo(f"  Nodes:       {bl.node_count}")
    click.echo(f"  Edges:       {bl.edge_count}")
    click.echo(f"  Communities: {bl.community_count}")
    click.echo(f"  Predicates:  {len(bl.predicate_histogram)}")
    store.close()


@baseline.command("list")
@click.pass_context
def baseline_list(ctx):
    """Show all saved baselines."""
    config = ctx.obj["config"]
    store = _get_store(config)
    detector = AnomalyDetector(store)

    baselines = detector.list_baselines()
    if not baselines:
        click.echo("No baselines found. Run 'kgcp baseline create' first.")
        store.close()
        return

    click.echo(f"{'ID':10s}  {'Label':20s}  {'Nodes':>6s}  {'Edges':>6s}  {'Created':12s}")
    click.echo("-" * 60)
    for bl in baselines:
        click.echo(
            f"{bl.baseline_id[:8]:10s}  {bl.label[:20]:20s}  {bl.node_count:6d}  "
            f"{bl.edge_count:6d}  {bl.created_at[:10]:12s}"
        )
    store.close()


@baseline.command("show")
@click.argument("baseline_id", required=False, default=None)
@click.pass_context
def baseline_show(ctx, baseline_id):
    """Show baseline details (defaults to latest)."""
    config = ctx.obj["config"]
    store = _get_store(config)

    if baseline_id:
        # Try prefix match
        baselines = store.list_baselines()
        bl = None
        for b in baselines:
            if b.baseline_id.startswith(baseline_id):
                bl = b
                break
        if not bl:
            bl = store.get_baseline(baseline_id)
    else:
        bl = store.get_latest_baseline()

    if not bl:
        click.echo("No baseline found.", err=True)
        store.close()
        return

    click.echo(f"Baseline: {bl.baseline_id}")
    click.echo(f"Label:    {bl.label or '(none)'}")
    click.echo(f"Created:  {bl.created_at}")
    click.echo(f"Nodes:    {bl.node_count}")
    click.echo(f"Edges:    {bl.edge_count}")
    click.echo(f"Communities: {bl.community_count}")
    click.echo(f"\nPredicate Histogram ({len(bl.predicate_histogram)} predicates):")
    for pred, count in sorted(bl.predicate_histogram.items(), key=lambda x: -x[1])[:15]:
        click.echo(f"  {count:4d}  {pred}")
    if len(bl.predicate_histogram) > 15:
        click.echo(f"  ... and {len(bl.predicate_histogram) - 15} more")

    store.close()


@baseline.command("delete")
@click.argument("baseline_id")
@click.pass_context
def baseline_delete(ctx, baseline_id):
    """Delete a baseline and its anomaly scores."""
    config = ctx.obj["config"]
    store = _get_store(config)

    # Try prefix match
    baselines = store.list_baselines()
    target = None
    for b in baselines:
        if b.baseline_id.startswith(baseline_id):
            target = b
            break

    if not target:
        click.echo(f"Baseline '{baseline_id}' not found.", err=True)
        store.close()
        return

    store.delete_baseline(target.baseline_id)
    click.echo(f"Deleted baseline {target.baseline_id[:8]}...")
    store.close()


@cli.command()
@click.option("--since", default=None, help="Only score triplets from docs ingested after this date (ISO)")
@click.option("--min-score", default=0.3, type=float, help="Minimum anomaly score to display (default: 0.3)")
@click.option("--limit", default=50, type=int, help="Maximum results to show")
@click.option("--entity", default=None, help="Show drift analysis for a specific entity")
@click.option(
    "--format", "-f", "fmt",
    default="table",
    type=click.Choice(["table", "json", "yaml"], case_sensitive=False),
    help="Output format",
)
@click.pass_context
def anomalies(ctx, since, min_score, limit, entity, fmt):
    """Surface anomalous relationships in the knowledge graph."""
    import json as json_mod

    config = ctx.obj["config"]
    store = _get_store(config)
    detector = AnomalyDetector(store)

    bl = detector.get_latest_baseline()
    if not bl:
        click.echo("No baseline found. Run 'kgcp baseline create' first.", err=True)
        store.close()
        return

    # Entity drift mode
    if entity:
        drift = detector.detect_entity_drift(entity, bl)
        if fmt == "json":
            click.echo(json_mod.dumps(drift, indent=2))
        else:
            click.echo(f"Entity Drift: {drift['entity']}")
            click.echo("-" * 40)
            if drift.get("community_change"):
                cc = drift["community_change"]
                click.echo(f"Community:    {cc['old']} -> {cc['new']}")
            else:
                click.echo("Community:    unchanged")
            click.echo(f"Centrality:   {drift['centrality_delta']:+.4f}")
            if drift["new_predicates"]:
                click.echo(f"New predicates:  {', '.join(drift['new_predicates'])}")
            if drift["lost_predicates"]:
                click.echo(f"Lost predicates: {', '.join(drift['lost_predicates'])}")
            if drift["new_neighbors"]:
                click.echo(f"New neighbors:   {', '.join(drift['new_neighbors'])}")
        store.close()
        return

    # Score triplets
    if since:
        results = detector.score_triplets_since(since, bl)
    else:
        results = detector.score_all_triplets(bl)

    # Filter by min_score
    results = [r for r in results if r.score >= min_score][:limit]

    if not results:
        click.echo(f"No anomalies found above score {min_score}.", err=True)
        store.close()
        return

    click.echo(
        f"Found {len(results)} anomalous triplets (score >= {min_score}, baseline {bl.baseline_id[:8]}...)",
        err=True,
    )

    if fmt == "json":
        data = [
            {
                "triplet_id": r.triplet_id[:8],
                "score": r.score,
                "subject": r.subject,
                "predicate": r.predicate,
                "object": r.object,
                "signals": r.signals,
            }
            for r in results
        ]
        click.echo(json_mod.dumps(data, indent=2))
    elif fmt == "yaml":
        lines = ["anomalies:"]
        for r in results:
            lines.append(f"  - score: {r.score}")
            lines.append(f"    triplet: [{r.subject}, {r.predicate}, {r.object}]")
            sig_parts = ", ".join(f"{k}: {v}" for k, v in sorted(r.signals.items()) if v > 0)
            lines.append(f"    signals: {{{sig_parts}}}")
        click.echo("\n".join(lines))
    else:
        # Table format
        click.echo(f"{'Score':>6s}  {'Subject':20s}  {'Predicate':20s}  {'Object':20s}")
        click.echo("-" * 70)
        for r in results:
            click.echo(
                f"{r.score:6.2f}  {r.subject[:20]:20s}  {r.predicate[:20]:20s}  {r.object[:20]:20s}"
            )

    store.close()


@cli.command()
@click.option("--entity", default=None, help="Filter trends to a specific entity")
@click.option("--window", default=None, type=int, help="Window size in days (default: from config)")
@click.option("--min-observations", default=None, type=int, help="Minimum observations for a trend")
@click.option("--since", default=None, help="Only include triplets after this date")
@click.option("--until", default=None, help="Only include triplets before this date")
@click.option(
    "--format", "-f", "fmt",
    default="table",
    type=click.Choice(["table", "json"], case_sensitive=False),
    help="Output format",
)
@click.option("--limit", default=20, type=int, help="Maximum trends to show")
@click.pass_context
def trends(ctx, entity, window, min_observations, since, until, fmt, limit):
    """Detect frequency trends in entity-predicate relationships."""
    import json as json_mod

    from .temporal.date_utils import parse_date
    from .temporal.trends import detect_trends

    config = ctx.obj["config"]
    store = _get_store(config)
    temporal_config = config.get("temporal", {})

    window_days = window or temporal_config.get("default_window_days", 90)
    min_obs = min_observations or temporal_config.get("min_trend_observations", 2)

    # Parse time filters
    parsed_since = None
    parsed_until = None
    if since:
        try:
            parsed_since = parse_date(since)
        except ValueError as e:
            click.echo(f"Invalid --since value: {e}", err=True)
            store.close()
            return
    if until:
        try:
            parsed_until = parse_date(until)
        except ValueError as e:
            click.echo(f"Invalid --until value: {e}", err=True)
            store.close()
            return

    # Get triplets (optionally time-scoped)
    if parsed_since or parsed_until:
        triplets = store.get_triplets_in_range(since=parsed_since, until=parsed_until)
    else:
        triplets = store.get_all_triplets()

    if not triplets:
        click.echo("No triplets found.", err=True)
        store.close()
        return

    results = detect_trends(
        triplets, entity=entity, window_days=window_days, min_observations=min_obs,
    )[:limit]

    if not results:
        click.echo("No trends detected.", err=True)
        store.close()
        return

    if fmt == "json":
        data = [
            {
                "entity": t.entity,
                "predicate": t.predicate,
                "direction": t.direction,
                "change_ratio": round(t.change_ratio, 2),
                "window_counts": t.window_counts,
            }
            for t in results
        ]
        click.echo(json_mod.dumps(data, indent=2))
    else:
        click.echo(f"{'Entity':20s}  {'Predicate':20s}  {'Direction':12s}  {'Change':>8s}  Windows")
        click.echo("-" * 80)
        for t in results:
            windows_str = " ".join(str(c) for c in t.window_counts)
            click.echo(
                f"{t.entity[:20]:20s}  {t.predicate[:20]:20s}  {t.direction:12s}  "
                f"{t.change_ratio:+8.2f}  [{windows_str}]"
            )

    store.close()


@cli.command()
@click.argument("entity")
@click.option("--hops", default=2, type=int, help="Graph traversal hops (default: 2)")
@click.option("--since", default=None, help="Only include steps after this date (ISO, quarter, or relative)")
@click.option("--until", default=None, help="Only include steps before this date")
@click.option("--min-anomaly", default=0.0, type=float, help="Minimum anomaly score for steps")
@click.option("--limit", default=100, type=int, help="Maximum number of steps")
@click.option(
    "--format", "-f", "fmt",
    default="timeline",
    type=click.Choice(["timeline", "yaml", "json", "compact"], case_sensitive=False),
    help="Output format (default: timeline)",
)
@click.option("--to-file", default=None, help="Write output to file")
@click.option("--budget", "-b", default=2048, type=int, help="Token budget for yaml format")
@click.pass_context
def paths(ctx, entity, hops, since, until, min_anomaly, limit, fmt, to_file, budget):
    """Reconstruct temporally-ordered attack paths from a seed entity."""
    import json as json_mod

    from .retrieval.attack_paths import reconstruct_attack_path
    from .temporal.date_utils import parse_date

    config = ctx.obj["config"]
    store = _get_store(config)

    # Parse temporal filters
    parsed_since = None
    parsed_until = None
    if since:
        try:
            parsed_since = parse_date(since)
        except ValueError as e:
            click.echo(f"Invalid --since value: {e}", err=True)
            store.close()
            return
    if until:
        try:
            parsed_until = parse_date(until)
        except ValueError as e:
            click.echo(f"Invalid --until value: {e}", err=True)
            store.close()
            return

    path = reconstruct_attack_path(
        seed_entity=entity,
        store=store,
        hops=hops,
        since=parsed_since,
        until=parsed_until,
        min_anomaly_score=min_anomaly,
        limit=limit,
    )

    if not path.steps:
        click.echo(f"No attack path found for entity '{entity}'.", err=True)
        store.close()
        return

    click.echo(
        f"Attack path from '{entity}': {len(path.steps)} steps, "
        f"{len(path.entities_involved)} entities",
        err=True,
    )

    if fmt == "json":
        data = {
            "seed_entity": path.seed_entity,
            "total_anomaly": path.total_anomaly,
            "time_span": {"start": path.time_span[0], "end": path.time_span[1]},
            "entities_involved": sorted(path.entities_involved),
            "steps": [
                {
                    "index": s.step_index,
                    "timestamp": s.timestamp,
                    "subject": s.triplet.subject,
                    "predicate": s.triplet.predicate,
                    "object": s.triplet.object,
                    "anomaly_score": s.anomaly_score,
                    "anomaly_signals": s.anomaly_signals,
                }
                for s in path.steps
            ],
        }
        output = json_mod.dumps(data, indent=2)

    elif fmt == "yaml":
        lines = [
            f"# Attack path from '{entity}'",
            f"path_metadata:",
            f"  seed_entity: {path.seed_entity}",
            f"  total_anomaly: {path.total_anomaly}",
            f"  entities: {len(path.entities_involved)}",
            f"  time_span: [{path.time_span[0]}, {path.time_span[1]}]",
            f"timeline:",
        ]
        for s in path.steps:
            lines.append(f"  - step: {s.step_index}")
            lines.append(f"    timestamp: {s.timestamp}")
            lines.append(f"    triplet: [{s.triplet.subject}, {s.triplet.predicate}, {s.triplet.object}]")
            if s.anomaly_score > 0:
                lines.append(f"    anomaly_score: {s.anomaly_score}")
                if s.anomaly_signals:
                    sig_parts = ", ".join(
                        f"{k}: {v}" for k, v in sorted(s.anomaly_signals.items()) if v > 0
                    )
                    lines.append(f"    signals: {{{sig_parts}}}")
        output = "\n".join(lines)

    elif fmt == "compact":
        lines = []
        for s in path.steps:
            date_part = s.timestamp[:10] if len(s.timestamp) >= 10 else s.timestamp
            line = f"{date_part}  {s.triplet.subject} -> {s.triplet.predicate} -> {s.triplet.object}"
            if s.anomaly_score > 0:
                line += f" [!anomaly:{s.anomaly_score:.2f}]"
            lines.append(line)
        output = "\n".join(lines)

    else:
        # timeline (default) — human-readable table
        lines = [
            f"Attack Path: {entity}",
            f"Time Span: {path.time_span[0][:10] if path.time_span[0] else '?'} to "
            f"{path.time_span[1][:10] if path.time_span[1] else '?'}",
            f"Total Anomaly: {path.total_anomaly:.2f}",
            "",
            f"{'#':>3s}  {'Date':10s}  {'Score':>6s}  {'Subject':20s}  {'Predicate':20s}  {'Object':20s}",
            "-" * 85,
        ]
        for s in path.steps:
            date_part = s.timestamp[:10] if len(s.timestamp) >= 10 else s.timestamp
            score_str = f"{s.anomaly_score:.2f}" if s.anomaly_score > 0 else "  -   "
            lines.append(
                f"{s.step_index:3d}  {date_part:10s}  {score_str:>6s}  "
                f"{s.triplet.subject[:20]:20s}  {s.triplet.predicate[:20]:20s}  "
                f"{s.triplet.object[:20]:20s}"
            )
        output = "\n".join(lines)

    if to_file:
        Path(to_file).write_text(output + "\n")
        click.echo(f"Written to {to_file}", err=True)
    else:
        click.echo(output)

    store.close()


@cli.group("export-cti")
def export_cti():
    """Export knowledge graph to CTI platforms (STIX, MISP, OpenCTI, TheHive)."""
    pass


@export_cti.command("stix")
@click.option("--entity", default=None, help="Seed entity for attack path export")
@click.option("--query", "query_text", default=None, help="Query text to select triplets")
@click.option("--since", default=None, help="Filter triplets after this date")
@click.option("--until", default=None, help="Filter triplets before this date")
@click.option("--hops", default=2, type=int, help="Graph traversal hops (default: 2)")
@click.option("--output", "-o", default=None, help="Output file path")
@click.pass_context
def export_stix(ctx, entity, query_text, since, until, hops, output):
    """Export triplets or attack paths as a STIX 2.1 bundle."""
    import json as json_mod

    from .export.stix_adapter import STIXExporter
    from .temporal.date_utils import parse_date

    config = ctx.obj["config"]
    store = _get_store(config)
    exporter = STIXExporter(config)

    parsed_since = None
    parsed_until = None
    if since:
        try:
            parsed_since = parse_date(since)
        except ValueError as e:
            click.echo(f"Invalid --since value: {e}", err=True)
            store.close()
            return
    if until:
        try:
            parsed_until = parse_date(until)
        except ValueError as e:
            click.echo(f"Invalid --until value: {e}", err=True)
            store.close()
            return

    if entity:
        # Attack path mode
        from .retrieval.attack_paths import reconstruct_attack_path

        path = reconstruct_attack_path(
            seed_entity=entity, store=store, hops=hops,
            since=parsed_since, until=parsed_until,
        )
        if not path.steps:
            click.echo(f"No attack path found for '{entity}'.", err=True)
            store.close()
            return
        click.echo(
            f"Exporting attack path: {len(path.steps)} steps, "
            f"{len(path.entities_involved)} entities",
            err=True,
        )
        bundle = exporter.export_attack_path(path)
    elif query_text:
        # Query mode
        retriever = Retriever(store)
        triplets = retriever.query(query_text, hops=hops)
        if not triplets:
            click.echo("No matching triplets found.", err=True)
            store.close()
            return
        click.echo(f"Exporting {len(triplets)} triplets as STIX 2.1", err=True)
        bundle = exporter.export_triplets(triplets)
    else:
        # Full graph export
        triplets = store.get_all_triplets()
        if not triplets:
            click.echo("No triplets to export.", err=True)
            store.close()
            return
        click.echo(f"Exporting all {len(triplets)} triplets as STIX 2.1", err=True)
        bundle = exporter.export_triplets(triplets)

    content = json_mod.dumps(bundle, indent=2, default=str)

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(content)
        click.echo(f"STIX bundle written to {output}", err=True)
        click.echo(f"  Objects: {len(bundle['objects'])}", err=True)
    else:
        click.echo(content)

    store.close()


@export_cti.command("attack-map")
@click.option("--entity", default=None, help="Seed entity to map")
@click.option("--query", "query_text", default=None, help="Query text to select triplets")
@click.option("--hops", default=2, type=int, help="Graph traversal hops")
@click.option("--max-matches", default=3, type=int, help="Max ATT&CK matches per triplet")
@click.option("--update", is_flag=True, help="Download fresh ATT&CK data")
@click.option(
    "--format", "-f", "fmt",
    default="table",
    type=click.Choice(["table", "json"], case_sensitive=False),
    help="Output format",
)
@click.pass_context
def export_attack_map(ctx, entity, query_text, hops, max_matches, update, fmt):
    """Map triplets to MITRE ATT&CK techniques."""
    import json as json_mod

    from .export.attack_mapper import AttackMapper

    config = ctx.obj["config"]
    store = _get_store(config)

    cache_path = config.get("cti", {}).get("attack_data_path")
    mapper = AttackMapper(cache_path=Path(cache_path) if cache_path else None)

    if update:
        click.echo("Downloading fresh ATT&CK data...", err=True)
        mapper.ensure_data(force_download=True)
        click.echo(f"Loaded {len(mapper._techniques)} techniques", err=True)

    # Select triplets
    if entity:
        from .retrieval.attack_paths import reconstruct_attack_path
        path = reconstruct_attack_path(seed_entity=entity, store=store, hops=hops)
        triplets = [s.triplet for s in path.steps]
    elif query_text:
        retriever = Retriever(store)
        triplets = retriever.query(query_text, hops=hops)
    else:
        triplets = store.get_all_triplets()

    if not triplets:
        click.echo("No triplets found.", err=True)
        store.close()
        return

    click.echo(f"Mapping {len(triplets)} triplets to ATT&CK...", err=True)
    results = mapper.match_triplets(triplets, max_results_per=max_matches)

    if not results:
        click.echo("No ATT&CK technique matches found.", err=True)
        store.close()
        return

    if fmt == "json":
        data = {
            tid: [
                {
                    "technique_id": m.technique_id,
                    "technique_name": m.technique_name,
                    "confidence": round(m.match_confidence, 3),
                    "tactic": m.tactic,
                    "matched_on": m.matched_on,
                }
                for m in matches
            ]
            for tid, matches in results.items()
        }
        click.echo(json_mod.dumps(data, indent=2))
    else:
        click.echo(
            f"{'Technique':14s}  {'Name':30s}  {'Confidence':>10s}  {'Tactic':20s}  Matched On"
        )
        click.echo("-" * 110)
        for tid, matches in results.items():
            for m in matches:
                click.echo(
                    f"{m.technique_id:14s}  {m.technique_name[:30]:30s}  "
                    f"{m.match_confidence:10.3f}  {m.tactic[:20]:20s}  {m.matched_on[:40]}"
                )

    click.echo(f"\n{len(results)} triplets matched to ATT&CK techniques", err=True)
    store.close()


def _select_triplets(ctx, entity, query_text, hops, since=None, until=None):
    """Shared helper: select triplets by entity, query, or full graph."""
    from .temporal.date_utils import parse_date

    config = ctx.obj["config"]
    store = _get_store(config)

    parsed_since = None
    parsed_until = None
    if since:
        try:
            parsed_since = parse_date(since)
        except ValueError as e:
            click.echo(f"Invalid --since value: {e}", err=True)
            store.close()
            return None, None, store
    if until:
        try:
            parsed_until = parse_date(until)
        except ValueError as e:
            click.echo(f"Invalid --until value: {e}", err=True)
            store.close()
            return None, None, store

    path = None
    if entity:
        from .retrieval.attack_paths import reconstruct_attack_path
        path = reconstruct_attack_path(
            seed_entity=entity, store=store, hops=hops,
            since=parsed_since, until=parsed_until,
        )
        if not path.steps:
            click.echo(f"No attack path found for '{entity}'.", err=True)
            store.close()
            return None, None, store
        triplets = [s.triplet for s in path.steps]
    elif query_text:
        retriever = Retriever(store)
        triplets = retriever.query(query_text, hops=hops)
    else:
        triplets = store.get_all_triplets()

    if not triplets:
        click.echo("No triplets found.", err=True)
        store.close()
        return None, None, store

    return triplets, path, store


@export_cti.command("misp")
@click.option("--entity", default=None, help="Seed entity for attack path export")
@click.option("--query", "query_text", default=None, help="Query text to select triplets")
@click.option("--since", default=None, help="Filter triplets after this date")
@click.option("--until", default=None, help="Filter triplets before this date")
@click.option("--hops", default=2, type=int, help="Graph traversal hops")
@click.option("--event-info", default=None, help="MISP event info/title")
@click.option("--output", "-o", default=None, help="Output file path")
@click.option("--push", "do_push", is_flag=True, help="Push to MISP instance")
@click.pass_context
def export_misp(ctx, entity, query_text, since, until, hops, event_info, output, do_push):
    """Export triplets as a MISP event."""
    import json as json_mod

    from .export.misp_adapter import MISPExporter

    config = ctx.obj["config"]
    triplets, path, store = _select_triplets(ctx, entity, query_text, hops, since, until)
    if triplets is None:
        return

    exporter = MISPExporter(config)
    kwargs = {}
    if event_info:
        kwargs["info"] = event_info

    if path:
        click.echo(f"Exporting attack path as MISP event: {len(path.steps)} steps", err=True)
        event = exporter.export_attack_path(path, **kwargs)
    else:
        click.echo(f"Exporting {len(triplets)} triplets as MISP event", err=True)
        event = exporter.export_triplets(triplets, **kwargs)

    if do_push:
        try:
            result = exporter.push(event)
            click.echo(f"Pushed to MISP: event_id={result.get('event_id', 'unknown')}", err=True)
        except (ImportError, ValueError, RuntimeError) as e:
            click.echo(f"Push failed: {e}", err=True)
    elif output:
        exporter.to_file(event, Path(output))
        click.echo(f"MISP event written to {output}", err=True)
        click.echo(f"  Attributes: {len(event.get('Event', {}).get('Attribute', []))}", err=True)
    else:
        click.echo(json_mod.dumps(event, indent=2, default=str))

    store.close()


@export_cti.command("opencti")
@click.option("--entity", default=None, help="Seed entity for attack path export")
@click.option("--query", "query_text", default=None, help="Query text to select triplets")
@click.option("--since", default=None, help="Filter triplets after this date")
@click.option("--until", default=None, help="Filter triplets before this date")
@click.option("--hops", default=2, type=int, help="Graph traversal hops")
@click.option("--output", "-o", default=None, help="Output file path")
@click.option("--push", "do_push", is_flag=True, help="Push to OpenCTI instance")
@click.pass_context
def export_opencti(ctx, entity, query_text, since, until, hops, output, do_push):
    """Export triplets as an OpenCTI-enriched STIX 2.1 bundle."""
    import json as json_mod

    from .export.opencti_adapter import OpenCTIExporter

    config = ctx.obj["config"]
    triplets, path, store = _select_triplets(ctx, entity, query_text, hops, since, until)
    if triplets is None:
        return

    exporter = OpenCTIExporter(config)

    if path:
        click.echo(f"Exporting attack path for OpenCTI: {len(path.steps)} steps", err=True)
        bundle = exporter.export_attack_path(path)
    else:
        click.echo(f"Exporting {len(triplets)} triplets for OpenCTI", err=True)
        bundle = exporter.export_triplets(triplets)

    if do_push:
        try:
            result = exporter.push(bundle)
            click.echo(f"Pushed to OpenCTI via {result.get('method', 'unknown')}", err=True)
        except (ImportError, ValueError, RuntimeError) as e:
            click.echo(f"Push failed: {e}", err=True)
    elif output:
        exporter.to_file(bundle, Path(output))
        click.echo(f"OpenCTI bundle written to {output}", err=True)
        click.echo(f"  Objects: {len(bundle.get('objects', []))}", err=True)
    else:
        click.echo(json_mod.dumps(bundle, indent=2, default=str))

    store.close()


@export_cti.command("thehive")
@click.option("--entity", default=None, help="Seed entity for attack path export")
@click.option("--query", "query_text", default=None, help="Query text to select triplets")
@click.option("--since", default=None, help="Filter triplets after this date")
@click.option("--until", default=None, help="Filter triplets before this date")
@click.option("--hops", default=2, type=int, help="Graph traversal hops")
@click.option("--alert-title", default=None, help="TheHive alert title")
@click.option("--output", "-o", default=None, help="Output file path")
@click.option("--push", "do_push", is_flag=True, help="Push to TheHive instance")
@click.pass_context
def export_thehive(ctx, entity, query_text, since, until, hops, alert_title, output, do_push):
    """Export triplets as a TheHive alert."""
    import json as json_mod

    from .export.thehive_adapter import TheHiveExporter

    config = ctx.obj["config"]
    triplets, path, store = _select_triplets(ctx, entity, query_text, hops, since, until)
    if triplets is None:
        return

    exporter = TheHiveExporter(config)
    kwargs = {}
    if alert_title:
        kwargs["title"] = alert_title

    if path:
        click.echo(f"Exporting attack path as TheHive alert: {len(path.steps)} steps", err=True)
        alert = exporter.export_attack_path(path, **kwargs)
    else:
        click.echo(f"Exporting {len(triplets)} triplets as TheHive alert", err=True)
        alert = exporter.export_triplets(triplets, **kwargs)

    if do_push:
        try:
            result = exporter.push(alert)
            if result.get("error"):
                click.echo(f"Push failed: {result.get('message', 'unknown error')}", err=True)
            else:
                click.echo("Alert created in TheHive", err=True)
        except (ImportError, ValueError) as e:
            click.echo(f"Push failed: {e}", err=True)
    elif output:
        exporter.to_file(alert, Path(output))
        click.echo(f"TheHive alert written to {output}", err=True)
        click.echo(f"  Observables: {len(alert.get('observables', []))}", err=True)
    else:
        click.echo(json_mod.dumps(alert, indent=2, default=str))

    store.close()


@cli.command("serve-taxii")
@click.option("--host", default=None, help="Bind address (default: 127.0.0.1)")
@click.option("--port", default=None, type=int, help="Port (default: 9500)")
@click.pass_context
def serve_taxii(ctx, host, port):
    """Start a read-only TAXII 2.1 server for STIX bundle distribution."""
    from .server.taxii import run_server

    config = ctx.obj["config"]
    taxii_config = config.get("cti", {}).get("taxii", {})
    host = host or taxii_config.get("host", "127.0.0.1")
    port = port or taxii_config.get("port", 9500)

    run_server(config=config, host=host, port=port)


def main():
    cli()


if __name__ == "__main__":
    main()
