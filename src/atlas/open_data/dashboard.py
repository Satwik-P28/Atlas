"""Static coverage dashboard generated from measured index state.

The counters are intentionally separate: discovered, rights-approved, downloaded,
integrated, publicly distributable. A dataset can be downloaded without being
integrated, and can be integrated without being redistributable.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .engine import AcquisitionEngine
from .registry import summarize


def collect(engine: AcquisitionEngine) -> dict[str, Any]:
    metrics = engine.index.dashboard()
    metrics["registry"] = summarize(engine.registry.payload)
    metrics["storage"] = engine.store.storage_report()
    metrics["status"] = engine.index.status_rows()
    return metrics


def _rows(items: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    head = "".join(f"<th>{html.escape(title)}</th>" for _, title in columns)
    body = []
    for item in items:
        cells = "".join(f"<td>{html.escape('' if item.get(key) is None else str(item.get(key)))}</td>"
                        for key, _ in columns)
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append(f"<tr><td colspan='{len(columns)}'>None recorded</td></tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _cards(metrics: dict[str, Any]) -> str:
    cards = [
        ("Datasets discovered", metrics["datasets_discovered"]),
        ("Rights approved", metrics["datasets_rights_approved"]),
        ("Downloaded", metrics["datasets_downloaded"]),
        ("With typed observations", metrics["datasets_with_observations"]),
        ("Bridged to Atlas evidence", metrics["datasets_integrated"]),
        ("Publicly distributable", metrics["datasets_publicly_distributable"]),
        ("Snapshots", metrics["snapshots"]),
        ("Entities", metrics["entities"]),
        ("Observations", metrics["observations"]),
        ("Raw bytes", f"{metrics['raw_bytes'] / 1e9:.2f} GB"),
        ("Failed runs", metrics["failed_runs"]),
    ]
    return "".join(
        f"<div class='card'><div class='value'>{html.escape(str(value))}</div>"
        f"<div class='label'>{html.escape(label)}</div></div>" for label, value in cards
    )


def render_html(metrics: dict[str, Any]) -> str:
    status = metrics.get("status") or []
    licensing = metrics.get("licensing") or []
    coverage = metrics.get("coverage") or []
    failures = metrics.get("failures") or []
    freshness = metrics.get("freshness") or []
    storage = metrics.get("storage") or {}
    payload = html.escape(json.dumps(metrics, indent=2, default=str))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atlas Open Data Coverage</title>
<style>
:root{{color-scheme:dark}}
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:0;background:#0d1117;color:#e6edf3}}
header{{padding:2rem;border-bottom:1px solid #30363d}}
h1{{margin:0 0 .4rem;font-size:1.6rem}} .sub{{color:#8b949e}}
main{{padding:2rem;max-width:1400px;margin:0 auto}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem;margin-bottom:2rem}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:1rem}}
.value{{font-size:1.5rem;font-weight:650}} .label{{color:#8b949e;font-size:.82rem;margin-top:.2rem}}
h2{{font-size:1.05rem;margin:2rem 0 .7rem;border-bottom:1px solid #21262d;padding-bottom:.4rem}}
table{{width:100%;border-collapse:collapse;font-size:.8rem;background:#161b22;border:1px solid #30363d}}
th,td{{text-align:left;padding:.42rem .55rem;border-bottom:1px solid #21262d;vertical-align:top}}
th{{color:#8b949e;font-weight:600;position:sticky;top:0;background:#161b22}}
.warn{{color:#d29922}} .bad{{color:#f85149}} .good{{color:#3fb950}}
details{{margin-top:2.5rem}} pre{{background:#161b22;padding:1rem;overflow:auto;border:1px solid #30363d;border-radius:8px}}
</style></head><body>
<header><h1>Atlas Open Data Coverage</h1>
<div class="sub">Separate counters for discovery, rights approval, acquisition and integration. Generated from the measured index, not from registry intent.</div></header>
<main>
<section class="cards">{_cards(metrics)}</section>
<h2>Dataset status</h2>
{_rows(status, [("dataset_id","Dataset"),("provider","Provider"),("rights_class","Rights"),("snapshots","Snapshots"),("acquired_records","Acquired records"),("observations","Observations"),("obs_start","Coverage start"),("obs_end","Coverage end"),("failures","Failures"),("last_success","Last success")])}
<h2>Licensing</h2>
{_rows(licensing, [("rights_class","Rights class"),("datasets","Datasets")])}
<h2>Coverage and missing periods</h2>
{_rows(coverage, [("dataset_id","Dataset"),("obs_start","Start"),("obs_end","End"),("records","Observations"),("acquired_records","Acquired records"),("entities","Entities"),("series","Series"),("missing_json","Missing periods")])}
<h2>Source freshness</h2>
{_rows(freshness, [("dataset_id","Dataset"),("last_snapshot","Last snapshot"),("last_validated","Last validated")])}
<h2>Provider failures</h2>
{_rows(failures, [("dataset_id","Dataset"),("started_at","When"),("status","Status"),("http_status","HTTP"),("error","Error")])}
<h2>Storage</h2>
{_rows([storage], [("snapshots","Snapshots"),("datasets_with_snapshots","Datasets"),("logical_bytes","Logical bytes"),("deduplicated_blob_bytes","Blob bytes"),("unique_blobs","Unique blobs"),("quarantined_staging","Quarantined"),("checkpoints","Checkpoints"),("root","Store root")])}
<details><summary>Raw metrics JSON</summary><pre>{payload}</pre></details>
</main></body></html>
"""


def write_dashboard(engine: AcquisitionEngine, path: str | Path = "artifacts/open_data_dashboard.html") -> dict[str, Any]:
    metrics = collect(engine)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html(metrics), encoding="utf-8")
    json_path = target.with_suffix(".json")
    json_path.write_text(json.dumps(metrics, indent=2, default=str) + "\n", encoding="utf-8")
    return {"html": str(target), "json": str(json_path), **metrics}
