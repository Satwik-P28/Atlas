"""`atlas data` command implementations.

Kept out of ``atlas.cli`` so the open-data engine can be tested and used without the
evidence database. The parent CLI dispatches here for ``atlas data ...``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .benchmark import benchmark_all, benchmark_dataset
from .dashboard import write_dashboard
from .durable import DEFAULT_MANIFESTS, inventory, release_candidates, restore_package, write_release_index
from .engine import AcquisitionEngine
from . import market as market_layer
from . import research as research_layer
from .integration import integrate_companyfacts, integrate_sec_metadata
from .registry import DEFAULT_REGISTRY, Registry, audit_rights, summarize
from .rights import review_is_stale
from .store import SnapshotStore
from .transport import HttpTransport, RateLimit, TransportConfig

DEFAULT_OPEN_ROOT = "var/open_data"
DEFAULT_OPEN_INDEX = "var/open_data/atlas_open_data.db"
PROVIDER_GROUPS = {
    "sec": ["SEC"],
    "treasury": ["US Treasury"],
    "macro": ["BLS", "US Treasury", "World Bank", "IMF", "ECB", "Eurostat", "BEA", "US Census Bureau"],
    "banking": ["FDIC", "FFIEC", "Federal Reserve Board"],
    "energy": ["EIA", "NOAA"],
    "cftc": ["CFTC"],
    "identifiers": ["GLEIF", "USASpending", "USPTO"],
}


def _engine(args) -> AcquisitionEngine:
    registry_path = Path(args.registry or DEFAULT_REGISTRY)
    registry = Registry.load(registry_path)
    hosts: set[str] = set()
    limits: dict[str, RateLimit] = {}
    for dataset in registry:
        acquisition = dataset.get("acquisition") or {}
        hosts.update(acquisition.get("allowed_redirect_hosts") or [])
        if dataset.provider == "SEC":
            limits["www.sec.gov"] = RateLimit(5.0, 5)
        elif dataset.provider == "BLS":
            limits["download.bls.gov"] = RateLimit(2.0, 2)
    config = TransportConfig(
        allowed_redirect_hosts=frozenset(hosts),
        rate_limits=limits,
        default_rate_limit=RateLimit(2.0, 2),
        user_agent=os.environ.get(
            "ATLAS_USER_AGENT",
            "Atlas-Data-Engine/1.0 (public financial data; contact: admin@example.org)",
        ),
    )
    return AcquisitionEngine(
        registry=registry,
        store=SnapshotStore(args.open_root or os.environ.get("ATLAS_OPEN_DATA_ROOT", DEFAULT_OPEN_ROOT)),
        index_path=args.open_db or os.environ.get("ATLAS_OPEN_DATA_DB", DEFAULT_OPEN_INDEX),
        transport=HttpTransport(config),
    )


def _emit(args, payload, table: str | None = None) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, default=str))
    elif table:
        print(table)
    else:
        print(json.dumps(payload, indent=2, default=str))


def _resolve_targets(registry: Registry, args) -> list[str]:
    if getattr(args, "all_open", False):
        return [dataset.id for dataset in registry.public_job_targets()]
    targets: list[str] = list(getattr(args, "targets", []) or [])
    if getattr(args, "provider", None):
        targets.append(args.provider)
    if not targets:
        raise SystemExit("select dataset ids, a provider group, or --all-open")
    selected: list[str] = []
    for target in targets:
        if target in registry.ids():
            selected.append(target)
            continue
        group = PROVIDER_GROUPS.get(target.lower())
        providers = group or [target]
        matches = [d.id for d in registry if any(
            p.lower() in d.provider.lower() or p.lower() in d.id for p in providers)]
        if not matches:
            raise SystemExit(f"no approved registry entries matched {target!r}")
        selected.extend(matches)
    return list(dict.fromkeys(selected))


def cmd_list(args) -> int:
    engine = _engine(args)
    try:
        rows = []
        for dataset in engine.registry.select(provider=args.provider, rights=args.rights,
                                              status=args.status):
            rows.append({
                "id": dataset.id,
                "provider": dataset.provider,
                "title": dataset["title"],
                "rights_class": dataset.rights_class.value,
                "redistribution": dataset["redistribution"],
                "status": dataset["ingestion_status"],
                "adapter": dataset["adapter"],
                "update_frequency": dataset["update_frequency"],
            })
        table = "\n".join(
            f"{r['id']:<42} {r['provider']:<22} {r['rights_class']:<28} "
            f"{'yes' if r['redistribution'] else 'no':<4} {r['status']}" for r in rows)
        _emit(args, {"datasets": rows, "count": len(rows)}, table or "(none)")
        return 0
    finally:
        engine.close()


def cmd_search(args) -> int:
    engine = _engine(args)
    try:
        rows = [{"id": d.id, "provider": d.provider, "title": d["title"],
                 "rights_class": d.rights_class.value} for d in engine.registry.search(args.query)]
        table = "\n".join(f"{r['id']:<42} {r['provider']:<22} {r['rights_class']:<28} {r['title']}"
                          for r in rows)
        _emit(args, {"query": args.query, "results": rows}, table or "(no matches)")
        return 0
    finally:
        engine.close()


def cmd_sync(args) -> int:
    engine = _engine(args)
    try:
        targets = _resolve_targets(engine.registry, args)
        if args.dry_run:
            _emit(args, {"selection": targets, "count": len(targets), "dry_run": True},
                  "\n".join(targets))
            return 0
        results = []
        for dataset_id in targets:
            dataset = engine.registry.get(dataset_id)
            if dataset.rights_class.value == "unverified" and args.automated:
                results.append({"dataset_id": dataset_id, "status": "skipped",
                                "error": "unverified rights in an automated job"})
                print(f"SKIP {dataset_id}: unverified rights", file=sys.stderr)
                continue
            print(f"acquire {dataset_id} ...", file=sys.stderr, flush=True)
            result = engine.acquire(
                dataset_id,
                automated=args.automated,
                public_distribution=args.public_distribution,
                force=args.force,
                max_bytes=args.max_bytes,
            )
            results.append(result.to_dict())
            stats = result.stats or {}
            print(
                f"{result.status:<12} {dataset_id:<40} bytes={stats.get('downloaded_bytes', 0):>12} "
                f"records={stats.get('record_count', 0):>10} entities={stats.get('entity_count', 0):>8} "
                f"elapsed={stats.get('elapsed_seconds', 0)}s",
                file=sys.stderr, flush=True,
            )
            if result.error:
                print(f"  error: {result.error}", file=sys.stderr)
        _emit(args, {"results": results, "selection": targets})
        failed = [r for r in results if r["status"] == "failed"]
        return 1 if failed else 0
    finally:
        engine.close()


def cmd_verify(args) -> int:
    engine = _engine(args)
    try:
        report = engine.verify(args.dataset)
        for item in report["reports"]:
            state = "ok" if item["ok"] else "FAILED"
            print(f"{state:<7} {item['dataset_id']:<40} {item['snapshot_id']} {len(item['files'])} files",
                  file=sys.stderr)
            for error in item["errors"]:
                print(f"  {error}", file=sys.stderr)
        _emit(args, report)
        return 0 if report["ok"] else 1
    finally:
        engine.close()


def cmd_audit_rights(args) -> int:
    engine = _engine(args)
    try:
        rows = audit_rights(engine.registry.payload)
        engine.index.record_rights_audit(rows)
        denied = [row for row in rows if not row["distribution_allowed"]]
        stale = [row for row in rows if row["review_stale"]]
        table = "\n".join(
            f"{row['id']:<42} {row['rights_class']:<30} "
            f"{'ALLOW' if row['distribution_allowed'] else 'DENY':<5} {row['reason'][:80]}"
            for row in rows)
        _emit(args, {"summary": summarize(engine.registry.payload), "decisions": rows,
                     "denied": len(denied), "stale_reviews": len(stale)}, table)
        if args.strict and (denied or stale):
            print(f"rights audit is not clean: {len(denied)} denied, {len(stale)} stale",
                  file=sys.stderr)
            return 1
        return 0
    finally:
        engine.close()


def cmd_storage(args) -> int:
    engine = _engine(args)
    try:
        report = {"store": engine.store.storage_report(), "index": engine.index.dashboard()}
        _emit(args, report, json.dumps(report["store"], indent=2))
        return 0
    finally:
        engine.close()


def cmd_benchmark(args) -> int:
    engine = _engine(args)
    try:
        payload = benchmark_dataset(engine, args.dataset, queries=args.queries) if args.dataset \
            else benchmark_all(engine, queries=args.queries)
        _emit(args, payload)
        return 0
    finally:
        engine.close()


def cmd_adopt(args) -> int:
    engine = _engine(args)
    try:
        payload = engine.adopt_snapshot(args.dataset, args.snapshot)
        _emit(args, payload, f"adopted {payload['dataset']} {payload['snapshot']} "
                             f"observations={payload['ingest']['inserted']}")
        return 0
    finally:
        engine.close()


def cmd_status(args) -> int:
    engine = _engine(args)
    try:
        payload = engine.index.dashboard()
        rows = engine.index.status_rows()
        table = "\n".join(
            f"{r['dataset_id']:<40} {r['rights_class']:<28} snapshots={r['snapshots']:<3} "
            f"acquired={r['acquired_records'] or 0:<10} observations={r['observations'] or 0:<10} "
            f"coverage={r['obs_start'] or '-'}..{r['obs_end'] or '-'}"
            for r in rows)
        _emit(args, {"metrics": payload, "datasets": rows}, table or "(no datasets registered)")
        return 0
    finally:
        engine.close()


def cmd_coverage(args) -> int:
    engine = _engine(args)
    try:
        rows = [row for row in engine.index.status_rows() if row["snapshots"]]
        if args.dataset:
            rows = [row for row in rows if row["dataset_id"] == args.dataset]
        table = "\n".join(
            f"{r['dataset_id']:<40} {str(r['obs_start']):<12}..{str(r['obs_end']):<12} "
            f"obs={r['observations'] or 0:<10} acquired={r['acquired_records'] or 0:<10} "
            f"entities={r['entities'] or 0:<8} series={r['series'] or 0}"
            for r in rows)
        _emit(args, {"coverage": rows}, table or "(nothing acquired yet)")
        return 0
    finally:
        engine.close()


def cmd_query(args) -> int:
    engine = _engine(args)
    try:
        rows = engine.index.observations(
            args.dataset, series_key=args.series, start=args.start, end=args.end,
            as_of=args.as_of, limit=args.limit, latest_only=not args.all_revisions,
        )
        _emit(args, {"dataset": args.dataset, "rows": rows, "count": len(rows)})
        return 0
    finally:
        engine.close()


def cmd_integrate(args) -> int:
    engine = _engine(args)
    try:
        result = integrate_companyfacts(
            engine, args.atlas_db, snapshot_id=args.snapshot, ciks=args.cik or None,
            limit=None if args.all_eligible else args.limit,
            batch_size=args.batch_size, checkpoint_dir=args.checkpoint_dir,
            restart=args.restart, max_seconds=args.max_seconds,
        )
        _emit(args, result)
        return 0
    finally:
        engine.close()


def cmd_inventory(args) -> int:
    engine = _engine(args)
    try:
        report = inventory(engine.store, engine.registry, manifests_root=args.manifests,
                           dataset_ids=args.dataset or None)
        rows = report["items"]
        table = "\n".join(
            f"{row['status']:<10} {row['dataset_id']:<40} {row['snapshot_id']:<26} "
            f"bytes={row['source_bytes']:>13} scope={row['acquisition_scope']:<9} "
            f"publish={'yes' if row['redistributable'] else 'no':<3} {row['reason'][:60]}"
            for row in sorted(rows, key=lambda r: (r['status'], r['dataset_id'])))
        _emit(args, report, table or "(no registered datasets)")
        if args.strict and report["verified_snapshots"] != report["snapshots"]:
            print(f"durability is incomplete: {report['by_status']}", file=sys.stderr)
            return 1
        return 0
    finally:
        engine.close()


def cmd_restore(args) -> int:
    engine = _engine(args)
    try:
        result = restore_package(engine.store, args.package, expected_sha256=args.expect_sha256)
        _emit(args, result, f"restored {result['restored']} snapshot(s), "
                             f"{result['already_present']} already present")
        return 0
    finally:
        engine.close()


def cmd_release_plan(args) -> int:
    engine = _engine(args)
    try:
        if args.out:
            path = write_release_index(engine.store, engine.registry, args.out,
                                      manifests_root=args.manifests, max_bytes=args.max_bytes)
            plan = json.loads(path.read_text(encoding="utf-8"))
            plan["index"] = str(path)
        else:
            plan = release_candidates(engine.store, engine.registry, manifests_root=args.manifests,
                                      max_bytes=args.max_bytes)
        table = "\n".join(
            f"{item['dataset_id']:<40} {item['snapshot_id']:<26} {item['source_bytes']:>13} bytes"
            for item in plan["selected"])
        _emit(args, plan, table or "(nothing verified and rights-approved is present)")
        return 0
    finally:
        engine.close()


def cmd_counts(args) -> int:
    """Keep the four counts separate instead of collapsing them into one number."""
    engine = _engine(args)
    try:
        rows = engine.index.status_rows()
        atlas: dict[str, Any] = {}
        if args.atlas_db and Path(args.atlas_db).exists():
            import sqlite3
            connection = sqlite3.connect(f"file:{args.atlas_db}?mode=ro", uri=True)
            try:
                atlas = {
                    "issuers": connection.execute("SELECT COUNT(*) FROM issuer").fetchone()[0],
                    "evidence_facts": connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
                    "evidence_issuers": connection.execute(
                        "SELECT COUNT(DISTINCT entity_id) FROM evidence").fetchone()[0],
                    "securities": connection.execute("SELECT COUNT(*) FROM security").fetchone()[0],
                }
            finally:
                connection.close()
        payload = {
            "schema": "atlas.open_data.counts.v1",
            "definitions": {
                "source_records": "rows or facts counted inside the provider archive",
                "unique_entities": "distinct CIKs, countries or institutions in the archive",
                "typed_observations": "rows indexed in the open-data observation table",
                "canonical_evidence_facts": "rows in the Atlas evidence kernel via the SEC bridge",
            },
            "source_records": sum(int(row["acquired_records"] or 0) for row in rows),
            "unique_entities": sum(int(row["entities"] or 0) for row in rows),
            "typed_observations": sum(int(row["observations"] or 0) for row in rows),
            "canonical_evidence_facts": atlas.get("evidence_facts", 0),
            "atlas": atlas,
            "datasets": rows,
        }
        _emit(args, payload, json.dumps({key: payload[key] for key in (
            "source_records", "unique_entities", "typed_observations",
            "canonical_evidence_facts", "atlas")}, indent=2))
        return 0
    finally:
        engine.close()


def cmd_anomalies(args) -> int:
    engine = _engine(args)
    try:
        items = []
        for snapshot in engine.store.list_snapshots(args.dataset):
            issues = (snapshot.manifest.get("stats") or {}).get("issues") or []
            for issue in issues:
                code = str(issue.get("code") or "")
                if "date" in code or code in {"obs_end_future", "timezone_drift"}:
                    items.append({
                        "dataset_id": snapshot.dataset_id,
                        "snapshot_id": snapshot.snapshot_id,
                        "code": code,
                        "severity": issue.get("severity"),
                        "detail": issue.get("detail"),
                        "obs_end": (snapshot.manifest.get("stats") or {}).get("obs_end"),
                    })
        payload = {
            "schema": "atlas.open_data.date_anomalies.v1",
            "datasets": len({item["dataset_id"] for item in items}),
            "issues": len(items),
            "policy": (
                "Future or implausible provider dates are retained in the raw snapshot, excluded "
                "from advertised coverage, and reported here. Atlas never shifts a date to make it "
                "plausible and never infers that a future period was observed."
            ),
            "items": items,
        }
        _emit(args, payload, json.dumps(payload["items"], indent=2))
        if args.strict and items:
            return 1
        return 0
    finally:
        engine.close()


def cmd_market(args) -> int:
    if args.market_command == "providers":
        payload = market_layer.provider_catalog()
        table = "\n".join(
            f"{item['id']:<18} {item['rights_class']:<24} "
            f"redistribute={'yes' if item['redistribution'] else 'no':<3} {item['status']:<18} {item['notes'][:60]}"
            for item in payload["providers"])
        _emit(args, payload, table)
        return 0
    if args.market_command == "import":
        payload = market_layer.import_local(
            args.atlas_db, args.file, security_id=args.security_id, mic=args.mic,
            currency=args.currency, source_name=args.source_name, licence=args.licence,
            allow_synthetic=args.allow_synthetic,
        )
        _emit(args, payload, json.dumps(payload, indent=2))
        return 0
    raise SystemExit("select a market subcommand")


def cmd_research(args) -> int:
    workflow = args.research_command
    kwargs = {}
    if workflow == "company":
        payload = research_layer.company_search(args.atlas_db, args.query, limit=args.limit)
    elif workflow == "statements":
        payload = research_layer.financials(args.atlas_db, args.identifier, as_of=args.as_of,
                                            period=args.period, limit=args.limit)
    elif workflow == "valuation":
        payload = research_layer.valuation(args.atlas_db, args.identifier, as_of=args.as_of)
    elif workflow == "models":
        payload = research_layer.run_models(args.atlas_db, limit=args.limit, as_of=args.as_of)
    elif workflow == "comps":
        payload = research_layer.comparables(args.atlas_db, args.identifier, limit=args.limit)
    elif workflow == "screen":
        payload = research_layer.screen(args.atlas_db, min_revenue=args.min_revenue,
                                        min_net_margin=args.min_net_margin,
                                        min_roe=args.min_roe, limit=args.limit)
    else:
        raise SystemExit("select a research subcommand")
    _emit(args, payload, json.dumps(payload, indent=2, default=str))
    return 0


def cmd_integrate_metadata(args) -> int:
    engine = _engine(args)
    try:
        result = integrate_sec_metadata(engine, args.atlas_db)
        _emit(args, result, json.dumps(result, indent=2, default=str))
        return 0
    finally:
        engine.close()


def cmd_dashboard(args) -> int:
    engine = _engine(args)
    try:
        result = write_dashboard(engine, args.out)
        print(f"wrote {result['html']} and {result['json']}", file=sys.stderr)
        _emit(args, {key: result[key] for key in (
            "html", "json", "datasets_discovered", "datasets_rights_approved",
            "datasets_downloaded", "datasets_integrated", "datasets_publicly_distributable",
            "entities", "observations", "raw_bytes")})
        return 0
    finally:
        engine.close()


def cmd_export_manifest(args) -> int:
    engine = _engine(args)
    try:
        if getattr(args, "all", False):
            exported = []
            for dataset_id in sorted({s.dataset_id for s in engine.store.list_snapshots()}):
                snapshot = engine.store.latest(dataset_id)
                if snapshot is None:
                    continue
                target = (Path(args.out) if args.out else Path("data/open_data/manifests")) / dataset_id / f"{snapshot.snapshot_id}.json"
                path = engine.export_manifest(snapshot, target)
                exported.append({"dataset": dataset_id, "snapshot": snapshot.snapshot_id,
                                 "manifest": str(path), "manifest_sha256": snapshot.manifest_sha256})
            _emit(args, {"exported": exported, "count": len(exported)},
                  "\n".join(f"{row['dataset']:<40} {row['snapshot']}" for row in exported))
            return 0
        if args.dataset is None:
            raise ValueError("dataset is required unless --all is used")
        if args.snapshot:
            snapshot = next((s for s in engine.store.list_snapshots(args.dataset)
                             if s.snapshot_id == args.snapshot), None)
        else:
            snapshot = engine.store.latest(args.dataset)
        if snapshot is None:
            raise FileNotFoundError(f"no snapshot for {args.dataset}")
        target = Path(args.out) if args.out else (
            Path("data/open_data/manifests") / args.dataset / f"{snapshot.snapshot_id}.json")
        path = engine.export_manifest(snapshot, target)
        _emit(args, {"dataset": args.dataset, "snapshot": snapshot.snapshot_id,
                     "manifest": str(path), "manifest_sha256": snapshot.manifest_sha256})
        return 0
    finally:
        engine.close()


def _release_index(args) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Read the release index and, when asked, the published GitHub release.

    The index in Git records what was packaged. Only the API response proves an
    asset was uploaded, so availability is merged, never assumed.
    """
    from .release import (
        DEFAULT_REPO, fetch_github_release, published_assets, read_release_index,
    )

    index = read_release_index(args.index)
    release = None
    if getattr(args, "online", False):
        try:
            release = fetch_github_release(
                getattr(args, "repo", DEFAULT_REPO),
                getattr(args, "tag", None) or index.get("release_tag"),
            )
        except Exception as exc:  # noqa: BLE001 - availability stays unknown
            print(f"release lookup failed: {exc}", file=sys.stderr)
            return index, None
        published = {item["asset"]: item for item in published_assets(release)}
        for asset in index.get("assets") or []:
            match = published.get(asset.get("asset"))
            if match:
                asset["url"] = match["url"]
                asset["published_bytes"] = match["bytes"]
            # Multipart parts are the published assets; a dataset entry has no single
            # filename. Without this merge an online install had no URL for any part
            # and could not download a multipart dataset at all.
            detail = (index.get("multipart") or {}).get(str(asset.get("dataset_id"))) or {}
            for part in detail.get("parts") or []:
                members = (part.get("split") or {}).get("parts") or [part]
                for member in members:
                    found = published.get(member.get("name"))
                    if found:
                        member["url"] = found["url"]
                        member["published_bytes"] = found["bytes"]
        index["release"] = {"tag": release.get("tag_name"),
                            "url": release.get("html_url")}
    base = getattr(args, "asset_base", None)
    if base:
        index["asset_base_url"] = base
    return index, release


def cmd_releases(args) -> int:
    from .release import catalog_table, release_catalog

    engine = _engine(args)
    try:
        index, release = _release_index(args)
        catalog = release_catalog(
            engine.registry, engine.store, index_path=args.index,
            downloads_path=args.downloads, release=release,
            open_data_db=args.atlas_db or args.open_db,
        )
        _emit(args, catalog, catalog_table(catalog))
        return 0
    finally:
        engine.close()


def cmd_install(args) -> int:
    from .distribution import DEFAULT_CACHE, install
    from .release import allowed_dataset_ids

    engine = _engine(args)
    try:
        index, _ = _release_index(args)
        if args.all_open:
            targets = sorted(dataset_id for dataset_id in allowed_dataset_ids(engine.registry)
                             if any(asset.get("dataset_id") == dataset_id
                                    for asset in index.get("assets") or []))
            if not targets:
                raise SystemExit("no rights-approved dataset has a published asset")
        else:
            from .release import validate_dataset_ids
            targets = validate_dataset_ids(args.targets, engine.registry)
        payload = install(
            engine.registry, engine.store, index, targets,
            cache_dir=args.cache_dir or DEFAULT_CACHE, output_dir=args.out,
            periods=args.period or None, dry_run=args.dry_run,
            downloads_path=args.downloads,
        )
        entries = payload.get("items") if isinstance(payload.get("items"), list) \
            else payload.get("assets") or []
        table = "\n".join(
            f"{item.get('kind', 'package'):<8} {item['dataset_id']:<24} "
            f"{str(item.get('asset') or ','.join(item.get('assets') or [])):<48} "
            f"{int(item.get('bytes') or item.get('download', {}).get('bytes') or 0):>13} bytes"
            for item in entries)
        table += ("\n\nrequired download bytes: "
                  + str(payload["space"]["download_bytes"]))
        _emit(args, payload, table or json.dumps(payload, indent=2))
        return 1 if payload.get("failures") else 0
    finally:
        engine.close()


def cmd_update(args) -> int:
    from .distribution import update

    engine = _engine(args)
    try:
        index, _ = _release_index(args)
        payload = update(engine.registry, engine.store, index,
                         dataset_ids=args.targets or None)
        table = "\n".join(
            f"{row['dataset_id']:<24} local={row['local_snapshot'] or '-':<26} "
            f"published={row['published_snapshot'] or '-':<26} "
            f"{'UPDATE' if row['update_available'] else 'current'}"
            for row in payload["items"])
        _emit(args, payload, table or "(no published assets)")
        return 0
    finally:
        engine.close()


def cmd_repair(args) -> int:
    from .distribution import repair

    engine = _engine(args)
    try:
        index, _ = _release_index(args)
        payload = repair(engine.registry, engine.store, index,
                         manifests_root=args.manifests, apply=args.apply,
                         cache_dir=args.cache_dir, downloads_path=args.downloads)
        table = "\n".join(
            f"{item['status']:<10} {item['dataset_id']:<24} {item['action']:<10} "
            f"{item.get('asset') or item.get('command') or ''}"
            for item in payload["items"])
        _emit(args, payload, table or "every committed snapshot verifies")
        return 0
    finally:
        engine.close()


def cmd_columnar(args) -> int:
    """Query a built columnar evidence dataset without importing it into SQLite."""
    from .columnar import (
        ColumnarEvidence, IncomparableScreen, ScreenSpec, load_manifest, totals,
    )

    action = args.columnar_command
    root = Path(args.root)
    if action == "summary":
        manifest = load_manifest(root)
        payload = {
            "root": str(root),
            "schema": manifest.get("schema"),
            "snapshot_id": manifest.get("snapshot_id"),
            "companies": manifest.get("companies"),
            "records": manifest.get("records"),
            "scope": manifest.get("scope"),
            "availability": manifest.get("availability"),
            "archive": manifest.get("archive"),
            "stored": totals(root),
        }
        _emit(args, payload, "\n".join(f"{key:<14} {value}" for key, value in payload.items()
                                        if key != "stored"))
        return 0

    evidence = ColumnarEvidence(root)
    try:
        if action == "companies":
            rows = evidence.search_companies(args.query, limit=args.limit)
            table = "\n".join(f"{row['cik']:<12} {row['entity_name'][:44]:<44} "
                               f"obs={row['observations']:<8} {row['first_period_end']}..{row['last_period_end']}"
                               for row in rows)
            _emit(args, {"companies": rows, "count": len(rows)}, table or "(no match)")
            return 0
        if action == "company":
            rows = evidence.company(args.cik, as_of=args.as_of,
                                    include_unknown=args.include_unknown)
            truncated = rows[: args.limit]
            _emit(args, {"cik": args.cik, "rows": truncated, "count": len(rows),
                         "truncated": len(rows) > len(truncated)})
            return 0
        if action == "statement":
            payload = evidence.statement(args.cik, period_end=args.period_end, as_of=args.as_of)
            _emit(args, payload, "\n".join(f"{name:<28} {value}"
                                           for name, value in payload["concepts"].items()))
            return 0
        if action == "screen":
            spec = ScreenSpec(concept=args.concept, fiscal_year=args.fiscal_year,
                              period=args.period, currency=args.currency, unit=args.unit,
                              as_of=args.as_of, fiscal_period=args.fiscal_period)
            try:
                payload = evidence.screen_report(spec, minimum=args.minimum, limit=args.limit)
            except IncomparableScreen as exc:
                payload = {"error": "incomparable", "message": str(exc), "groups": exc.groups}
                _emit(args, payload, f"refused: {exc}")
                return 2
            table = "\n".join(f"{row['cik']:<12} {row['value']:>20} {row['currency'] or '':<4} "
                               f"{row['period_end']} {row['availability_class']}"
                               for row in payload["selected"])
            _emit(args, payload, table or "(nothing comparable)")
            return 0
        if action == "restatements":
            payload = evidence.restatement_report(args.cik)
            table = "\n".join(f"{item['concept']:<24} {item['period_kind']:<8} "
                               f"{str(item['period_end']):<12} {','.join(item['values'])} {item['category']}"
                               for item in payload["findings"])
            _emit(args, payload, table or "(no value revision)")
            return 0
        if action == "availability":
            payload = evidence.availability(args.cik)
            _emit(args, payload)
            return 0
        if action == "materialize":
            payload = evidence.materialize(args.cik, args.atlas_db)
            _emit(args, payload)
            return 0
        if action == "verify":
            payload = evidence.verify_sources(sample=args.sample)
            _emit(args, payload)
            return 0 if payload["ok"] else 1
        raise SystemExit("select a columnar subcommand")
    finally:
        evidence.close()


def add_data_parser(subparsers) -> None:
    data = subparsers.add_parser("data", help="rights-aware open-data acquisition and queries")
    data.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    data.set_defaults(command="data", func=lambda args: (data.print_help(), 0)[1])
    common = data.add_argument_group("open-data storage")
    common.add_argument("--registry", help="path to registry.json")
    common.add_argument("--open-root", help="snapshot store root (default var/open_data)")
    common.add_argument("--open-db", help="open-data index path")
    sub = data.add_subparsers(dest="data_command", metavar="COMMAND")

    def register(name, func, **kwargs):
        parser = sub.add_parser(name, **kwargs)
        parser.set_defaults(func=func)
        # SUPPRESS so a subcommand does not overwrite `atlas data --json` from the parent.
        parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                            help="emit machine-readable JSON")
        return parser

    listing = register("list", cmd_list, help="list registered datasets")
    listing.add_argument("--provider")
    listing.add_argument("--rights", nargs="*")
    listing.add_argument("--status")

    search = register("search", cmd_search, help="search the registry")
    search.add_argument("query")

    sync = register("sync", cmd_sync, help="acquire datasets into the immutable store")
    sync.add_argument("targets", nargs="*", help="dataset ids or provider groups (sec, treasury, macro, banking, energy)")
    sync.add_argument("--provider")
    sync.add_argument("--all-open", action="store_true", help="all distributable datasets")
    sync.add_argument("--force", action="store_true", help="ignore ETag/Last-Modified")
    sync.add_argument("--max-bytes", type=int)
    sync.add_argument("--automated", action="store_true", help="apply automated-job rights policy")
    sync.add_argument("--public-distribution", action="store_true")
    sync.add_argument("--dry-run", action="store_true")

    verify = register("verify", cmd_verify, help="verify snapshot hashes")
    verify.add_argument("dataset", nargs="?")

    audit = register("audit-rights", cmd_audit_rights, help="audit licensing and distribution decisions")
    audit.add_argument("--strict", action="store_true")

    register("storage", cmd_storage, help="content-addressed storage report")
    register("status", cmd_status, help="measured acquisition/integration status")

    inventory_parser = register("inventory", cmd_inventory,
                                help="verify committed manifests against the local store")
    inventory_parser.add_argument("dataset", nargs="?")
    inventory_parser.add_argument("--manifests", default=str(DEFAULT_MANIFESTS))
    inventory_parser.add_argument("--strict", action="store_true")

    restore = register("restore", cmd_restore, help="restore a verified distribution package")
    restore.add_argument("package")
    restore.add_argument("--expect-sha256")

    release = register("release-plan", cmd_release_plan,
                       help="list verified, rights-approved snapshots eligible for a release")
    release.add_argument("--manifests", default=str(DEFAULT_MANIFESTS))
    release.add_argument("--max-bytes", type=int, default=2_000_000_000)
    release.add_argument("--out")

    columnar = register("columnar", cmd_columnar,
                        help="query a built columnar evidence dataset (no import)")
    columnar.add_argument("--root", required=True, help="columnar dataset root (contains manifest.json)")
    columnar_sub = columnar.add_subparsers(dest="columnar_command", metavar="COMMAND")

    def register_columnar(name, **kwargs):
        parser = columnar_sub.add_parser(name, **kwargs)
        parser.set_defaults(func=cmd_columnar)
        parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        return parser

    register_columnar("summary", help="manifest, scope, availability policy and stored bytes")
    col_companies = register_columnar("companies", help="search issuers in the build by name")
    col_companies.add_argument("query")
    col_companies.add_argument("--limit", type=int, default=25)
    col_company = register_columnar("company", help="raw observations for one issuer")
    col_company.add_argument("cik")
    col_company.add_argument("--as-of")
    col_company.add_argument("--include-unknown", action="store_true",
                             help="include observations with unknown availability (never valid historically)")
    col_company.add_argument("--limit", type=int, default=500)
    col_statement = register_columnar("statement", help="one period's facts, kernel-parity selection")
    col_statement.add_argument("cik")
    col_statement.add_argument("--period-end")
    col_statement.add_argument("--as-of")
    col_screen = register_columnar("screen", help="comparable cross-company ranking")
    col_screen.add_argument("--concept", required=True)
    col_screen.add_argument("--fiscal-year", type=int)
    col_screen.add_argument("--period", default="auto", choices=["auto", "annual", "quarter", "instant"])
    col_screen.add_argument("--fiscal-period")
    col_screen.add_argument("--currency")
    col_screen.add_argument("--unit")
    col_screen.add_argument("--as-of")
    col_screen.add_argument("--minimum")
    col_screen.add_argument("--limit", type=int, default=100)
    col_restated = register_columnar("restatements", help="value revisions by full observation identity")
    col_restated.add_argument("cik")
    col_avail = register_columnar("availability", help="availability evidence for one issuer")
    col_avail.add_argument("cik")
    col_materialize = register_columnar("materialize", help="import one issuer into the SQLite kernel")
    col_materialize.add_argument("cik")
    col_materialize.add_argument("--atlas-db", required=True)
    col_verify = register_columnar("verify", help="reconstruct archived members and compare hashes")
    col_verify.add_argument("--sample", type=int)

    counts = register("counts", cmd_counts, help="separate source, entity, observation and evidence counts")
    counts.add_argument("--atlas-db", default="var/atlas.db")

    anomalies = register("anomalies", cmd_anomalies, help="report future and implausible provider dates")
    anomalies.add_argument("dataset", nargs="?")
    anomalies.add_argument("--strict", action="store_true")

    market = register("market", cmd_market, help="provider-independent market data layer")
    market_sub = market.add_subparsers(dest="market_command", metavar="COMMAND")
    providers = market_sub.add_parser("providers", help="provider rights and availability")
    providers.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    providers.set_defaults(func=cmd_market)
    market_import = market_sub.add_parser("import", help="import user-authorised OHLCV bars")
    market_import.add_argument("--atlas-db", default="var/atlas.db")
    market_import.add_argument("--file", required=True)
    market_import.add_argument("--security-id", required=True)
    market_import.add_argument("--mic", required=True)
    market_import.add_argument("--currency", default="USD")
    market_import.add_argument("--source-name", default="user-authorised local market import")
    market_import.add_argument("--licence", default=None)
    market_import.add_argument("--allow-synthetic", action="store_true")
    market_import.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    market_import.set_defaults(func=cmd_market)

    research = register("research", cmd_research, help="statements, ratios and models over integrated data")
    research_sub = research.add_subparsers(dest="research_command", metavar="COMMAND")
    search_company = research_sub.add_parser("company", help="search integrated issuers")
    search_company.add_argument("query")
    search_company.add_argument("--atlas-db", default="var/atlas.db")
    search_company.add_argument("--limit", type=int, default=25)
    search_company.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    search_company.set_defaults(func=cmd_research)
    statements = research_sub.add_parser("statements", help="income, balance and cash-flow statements")
    statements.add_argument("identifier")
    statements.add_argument("--atlas-db", default="var/atlas.db")
    statements.add_argument("--as-of")
    statements.add_argument("--period", default="FY", choices=["FY", "Q"])
    statements.add_argument("--limit", type=int, default=6)
    statements.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    statements.set_defaults(func=cmd_research)
    valuation = research_sub.add_parser("valuation", help="run the method-appropriate valuation")
    valuation.add_argument("identifier")
    valuation.add_argument("--atlas-db", default="var/atlas.db")
    valuation.add_argument("--as-of")
    valuation.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    valuation.set_defaults(func=cmd_research)
    models = research_sub.add_parser("models", help="run valuations across integrated issuers")
    models.add_argument("--atlas-db", default="var/atlas.db")
    models.add_argument("--limit", type=int, default=25)
    models.add_argument("--as-of")
    models.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    models.set_defaults(func=cmd_research)
    comps = research_sub.add_parser("comps", help="SIC-based peer comparison")
    comps.add_argument("identifier")
    comps.add_argument("--atlas-db", default="var/atlas.db")
    comps.add_argument("--limit", type=int, default=10)
    comps.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    comps.set_defaults(func=cmd_research)
    screen = research_sub.add_parser("screen", help="historical screening over reported metrics")
    screen.add_argument("--atlas-db", default="var/atlas.db")
    screen.add_argument("--min-revenue", type=float)
    screen.add_argument("--min-net-margin", type=float)
    screen.add_argument("--min-roe", type=float)
    screen.add_argument("--limit", type=int, default=50)
    screen.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    screen.set_defaults(func=cmd_research)

    coverage = register("coverage", cmd_coverage, help="observation coverage per dataset")
    coverage.add_argument("dataset", nargs="?")

    bench = register("benchmark", cmd_benchmark, help="measure compression and query performance")
    bench.add_argument("dataset", nargs="?")
    bench.add_argument("--queries", type=int, default=200)

    query = register("query", cmd_query, help="query indexed observations")
    query.add_argument("--dataset", required=True)
    query.add_argument("--series")
    query.add_argument("--start")
    query.add_argument("--end")
    query.add_argument("--as-of", dest="as_of", help="only observations knowable by this date")
    query.add_argument("--limit", type=int, default=200)
    query.add_argument("--all-revisions", action="store_true")

    integrate = register("integrate", cmd_integrate, help="integrate acquired data with Atlas")
    integrate.set_defaults(atlas_db="var/atlas.db", snapshot=None, cik=None, limit=50)
    integrate_sub = integrate.add_subparsers(dest="integration", metavar="KIND")
    facts = integrate_sub.add_parser("sec-facts", help="write company facts into the evidence kernel")
    facts.set_defaults(func=cmd_integrate)
    facts.add_argument("--atlas-db", default="var/atlas.db")
    facts.add_argument("--snapshot")
    facts.add_argument("--cik", action="append")
    facts.add_argument("--limit", type=int, default=50)
    facts.add_argument("--all-eligible", action="store_true",
                       help="integrate every issuer in the archive, resuming from the checkpoint")
    facts.add_argument("--batch-size", type=int, default=500,
                       help="evidence rows per transaction")
    facts.add_argument("--checkpoint-dir")
    facts.add_argument("--restart", action="store_true", help="ignore the saved checkpoint")
    facts.add_argument("--max-seconds", type=float, default=None,
                       help="stop cleanly after this many seconds; the checkpoint is kept")
    metadata = integrate_sub.add_parser("sec-metadata",
                                        help="integrate SEC tickers and issuer SIC identity")
    metadata.set_defaults(func=cmd_integrate_metadata)
    metadata.add_argument("--atlas-db", default="var/atlas.db")
    metadata.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    dashboard = register("dashboard", cmd_dashboard, help="write the coverage dashboard")
    dashboard.add_argument("--out", default="artifacts/open_data_dashboard.html")

    adopt = register("adopt", cmd_adopt, help="re-index an already stored snapshot after a recovery")
    adopt.add_argument("dataset")
    adopt.add_argument("--snapshot")

    manifest = register("export-manifest", cmd_export_manifest, help="copy a snapshot manifest for versioned evidence")
    manifest.add_argument("dataset", nargs="?")
    manifest.add_argument("--snapshot")
    manifest.add_argument("--out")
    manifest.add_argument("--all", action="store_true", help="export the latest manifest for every dataset")

    from .distribution import DEFAULT_CACHE as _DEFAULT_CACHE
    from .release import DEFAULT_DOWNLOADS as _DEFAULT_DOWNLOADS
    from .release import DEFAULT_INDEX as _DEFAULT_RELEASE_INDEX
    from .release import DEFAULT_REPO as _DEFAULT_REPO

    releases = register("releases", cmd_releases,
                        help="authoritative availability catalogue")
    releases.add_argument("--index", default=str(_DEFAULT_RELEASE_INDEX))
    releases.add_argument("--downloads", default=str(_DEFAULT_DOWNLOADS))
    releases.add_argument("--repo", default=_DEFAULT_REPO)
    releases.add_argument("--tag")
    releases.add_argument("--asset-base", help="URL prefix for an index that has no per-asset URL")
    releases.add_argument("--online", action="store_true",
                         help="read the GitHub Releases API instead of assuming availability")
    releases.add_argument("--atlas-db", default=None, help="open-data index database")

    install = register("install", cmd_install,
                       help="download, verify and restore a published release")
    install.add_argument("targets", nargs="*", help="dataset ids (e.g. sec.companyfacts, treasury)")
    install.add_argument("--all-open", action="store_true",
                         help="every rights-approved dataset with a published asset")
    install.add_argument("--period", action="append", default=[],
                         help="install only these reporting periods (2024q1)")
    install.add_argument("--cache-dir", default=str(_DEFAULT_CACHE))
    install.add_argument("--out", help="directory for reconstructed archives and periods")
    install.add_argument("--index", default=str(_DEFAULT_RELEASE_INDEX))
    install.add_argument("--downloads", default=str(_DEFAULT_DOWNLOADS))
    install.add_argument("--repo", default=_DEFAULT_REPO)
    install.add_argument("--tag")
    install.add_argument("--asset-base")
    install.add_argument("--online", action="store_true")
    install.add_argument("--dry-run", action="store_true")

    update_cmd = register("update", cmd_update, help="report published snapshots newer than local")
    update_cmd.add_argument("targets", nargs="*")
    update_cmd.add_argument("--index", default=str(_DEFAULT_RELEASE_INDEX))
    update_cmd.add_argument("--repo", default=_DEFAULT_REPO)
    update_cmd.add_argument("--tag")
    update_cmd.add_argument("--asset-base")
    update_cmd.add_argument("--online", action="store_true")

    repair_cmd = register("repair", cmd_repair, help="recover staging and reinstall from a release")
    repair_cmd.add_argument("--apply", action="store_true")
    repair_cmd.add_argument("--manifests", default=str(DEFAULT_MANIFESTS))
    repair_cmd.add_argument("--cache-dir", default=str(_DEFAULT_CACHE))
    repair_cmd.add_argument("--downloads", default=str(_DEFAULT_DOWNLOADS))
    repair_cmd.add_argument("--index", default=str(_DEFAULT_RELEASE_INDEX))
    repair_cmd.add_argument("--asset-base")
    repair_cmd.add_argument("--online", action="store_true")
