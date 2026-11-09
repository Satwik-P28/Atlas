"""Atlas command line interface.

The CLI is a thin, honest veneer over the Python API: every command maps to one
kernel operation, prints machine-readable JSON with ``--json``, and returns a
non-zero exit status on failure. There is no hidden state beyond the database file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Sequence

from .core.concepts import CONCEPTS, DERIVATIONS, concept_metadata
from .core.errors import AtlasError, MissingDataError, ValidationError
from .core.ids import normalize_cik
from .dependencies import DependencyIndex
from .core.temporal import AsOfMode, Availability, availability_from_date, availability_from_instant, iso, iso_date, utcnow
from .entities.master import SecurityMaster
from .evidence.kernel import EvidenceKernel
from .ingestion.market_csv import import_csv_bars, import_parquet_bars
from .ingestion.sec_client import SecClient
from .ingestion.sec_history import SubmissionsHistoryStore, load_fixture_history
from .ingestion.sec_submissions import PERIODIC_FORMS, FilingRepository
from .reconcile import reconcile_companyfacts
from .ingestion.sec_sync import SecIngestor, load_fixture_payloads, register_fixture_documents
from .market.actions import ActionStore, ActionType, CorporateAction
from .market.adjust import split_adjust, total_return
from .market.bars import BarStore
from .market.calendar import TradingCalendar
from .storage.db import Database, open_database
from .storage.quality import list_issues
from .storage.sources import SourceRegistry
from .validation import run_validation, summarize

DEFAULT_DB = os.environ.get("ATLAS_DB", "var/atlas.db")


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
def _render_table(rows: Sequence[dict[str, Any]], columns: Sequence[tuple[str, str]]) -> str:
    if not rows:
        return "(no rows)"
    widths: list[int] = []
    for key, title in columns:
        widest = len(title)
        for row in rows:
            value = row.get(key)
            widest = max(widest, len("" if value is None else str(value)))
        widths.append(min(widest, 44))
    header = "  ".join(title.ljust(width) for (_, title), width in zip(columns, widths))
    separator = "  ".join("-" * width for width in widths)
    lines = [header, separator]
    for row in rows:
        cells = []
        for (key, _), width in zip(columns, widths):
            value = row.get(key)
            text = "" if value is None else str(value)
            if len(text) > width:
                text = text[: width - 1] + "…"
            cells.append(text.ljust(width))
        lines.append("  ".join(cells))
    return "\n".join(lines)


def _emit(args: argparse.Namespace, payload: dict[str, Any], table: str | None = None) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    elif table is not None:
        print(table)
        summary = payload.get("summary")
        if summary:
            print()
            print(summary)
    else:
        print(json.dumps(payload, indent=2, default=str))


def _log_run(db: Database, command: str, status: str, stats: dict[str, Any] | None, error: str | None = None) -> None:
    from .core.ids import ingestion_run_id

    now = iso(utcnow())
    run_id = ingestion_run_id(command, now)
    db.execute(
        "INSERT INTO ingestion_run (run_id, command, started_at, finished_at, status, stats_json, error) "
        "VALUES (?,?,?,?,?,?,?)",
        (run_id, command, now, now, status, json.dumps(stats or {}, default=str), error),
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_init(db: Database, args: argparse.Namespace) -> int:
    applied = db.migrate()
    _emit(
        args,
        {
            "database": str(db.path),
            "schema_version": db.schema_version(),
            "migrations_applied": applied,
            "tables": db.tables(),
        },
        table=f"initialised {db.path} (schema v{db.schema_version()}, {len(applied)} migration(s) applied)",
    )
    return 0


def cmd_concepts(db: Database, args: argparse.Namespace) -> int:
    rows = []
    for key, meta in concept_metadata().items():
        rows.append(
            {
                "concept": key,
                "statement": meta["statement"],
                "unit": meta["unit_kind"],
                "period": meta["period_type"],
                "source_tags": ", ".join(meta["source_tags"][:3]),
            }
        )
    for key, derivation in DERIVATIONS.items():
        rows.append(
            {
                "concept": key,
                "statement": derivation.statement,
                "unit": derivation.unit_kind.value,
                "period": derivation.period_type,
                "source_tags": "derived: " + derivation.rule_id,
            }
        )
    table = _render_table(rows, [("concept", "CONCEPT"), ("statement", "STMT"), ("unit", "UNIT"),
                                 ("period", "PERIOD"), ("source_tags", "SOURCE TAGS")])
    _emit(args, {"concepts": concept_metadata(), "derivations": {
        k: {"rule": v.rule_id, "requires": list(v.requires), "description": v.description}
        for k, v in DERIVATIONS.items()
    }}, table=table)
    return 0


def cmd_sec_sync(db: Database, args: argparse.Namespace) -> int:
    master = SecurityMaster(db)
    ingestor = SecIngestor(db, master=master)
    if args.offline:
        submissions, facts, _, _ = load_fixture_payloads(args.offline, args.cik)
        submissions_doc, facts_doc = register_fixture_documents(db, args.offline, args.cik)
        report = ingestor.sync_payloads(
            args.cik,
            submissions_payload=submissions,
            companyfacts_payload=facts,
            submissions_doc_id=submissions_doc,
            companyfacts_doc_id=facts_doc,
            submissions_url=f"fixture://{args.cik}/submissions.json",
            companyfacts_url=f"fixture://{args.cik}/companyfacts.json",
            history_documents=None if args.no_history else load_fixture_history(args.offline, args.cik),
        )
    else:
        user_agent = args.user_agent or os.environ.get("ATLAS_SEC_USER_AGENT")
        client = SecClient(user_agent=user_agent, db=db, requests_per_second=args.rate)
        report = SecIngestor(db, client=client, master=master).sync(
            args.cik, fetch_history=not args.no_history, history_limit=args.history_limit
        )
    payload = report.to_dict()
    _log_run(db, f"sec sync {args.cik}", "completed", payload.get("evidence"))
    evidence = payload.get("evidence", {})
    payload["summary"] = (
        f"issuer {report.issuer_id} ({report.legal_name}); {report.filings_written} filings; "
        f"evidence inserted={evidence.get('inserted', 0)} duplicates={evidence.get('duplicates', 0)} "
        f"superseding={evidence.get('superseding', 0)}; securities={len(report.securities)}"
    )
    table_rows = [
        {"metric": "issuer_id", "value": report.issuer_id},
        {"metric": "legal_name", "value": report.legal_name},
        {"metric": "filings", "value": report.filings_written},
        {"metric": "filing archives fetched", "value": report.history.get("files_fetched")},
        {"metric": "filing history complete", "value": report.history.get("coverage", {}).get("complete")},
        {"metric": "concepts covered", "value": len(report.companyfacts.get("stats", {}).get("concepts_covered", []))},
        {"metric": "facts used", "value": report.companyfacts.get("stats", {}).get("observations_used")},
        {"metric": "facts deduplicated", "value": report.companyfacts.get("stats", {}).get("observations_deduplicated")},
        {"metric": "evidence inserted", "value": evidence.get("inserted")},
        {"metric": "evidence duplicates", "value": evidence.get("duplicates")},
        {"metric": "availability exact", "value": report.companyfacts.get("stats", {}).get("availability_exact")},
        {"metric": "availability date-only", "value": report.companyfacts.get("stats", {}).get("availability_date")},
        {"metric": "unmapped XBRL tags", "value": report.companyfacts.get("stats", {}).get("unmapped_tags")},
        {"metric": "raw documents", "value": len(report.documents)},
    ]
    _emit(args, payload, table=_render_table(table_rows, [("metric", "METRIC"), ("value", "VALUE")]))
    return 0


def cmd_sec_filings(db: Database, args: argparse.Namespace) -> int:
    repository = FilingRepository(db)
    rows = repository.for_cik(args.cik, form_types=args.form or None, limit=args.limit)
    if not rows:
        _emit(args, {"cik": args.cik, "filings": [], "summary": "no filings stored for this CIK"})
        return 0
    table = _render_table(
        rows,
        [("accession_number", "ACCESSION"), ("form_type", "FORM"), ("filed_date", "FILED"),
         ("acceptance_datetime", "ACCEPTED"), ("period_of_report", "PERIOD"), ("is_amendment", "AMEND")],
    )
    _emit(args, {"cik": args.cik, "filings": rows, "summary": f"{len(rows)} filing(s)"}, table=table)
    return 0


def cmd_entity_show(db: Database, args: argparse.Namespace) -> int:
    master = SecurityMaster(db)
    if args.cik:
        profile = master.issuer_profile(cik=args.cik)
        rows = [
            {
                "security_id": entry["security"]["security_id"],
                "class": entry["security"]["class_designation"],
                "type": entry["security"]["security_type"],
                "tickers": ", ".join(
                    f"{t['ticker']}@{t['mic']} ({t['valid_from']}..{t['valid_to'] or 'present'}, {t['status']})"
                    for t in entry["tickers"]
                ),
            }
            for entry in profile["securities"]
        ]
        table = _render_table(rows, [("security_id", "SECURITY"), ("class", "CLASS"), ("type", "TYPE"),
                                     ("tickers", "TICKERS")])
        summary = (
            f"{profile['issuer']['issuer_id']} {profile['issuer']['legal_name']} "
            f"(CIK {profile['issuer']['cik']}); {len(profile['securities'])} security(ies)"
        )
        _emit(args, {"profile": profile, "summary": summary}, table=table + "\n\n" + summary)
        return 0
    if args.ticker:
        resolution = master.resolve_ticker(args.ticker, as_of=args.as_of)
        payload = resolution.to_dict()
        payload["reasoning_text"] = "\n".join(resolution.reasoning)
        rows = [
            {"security_id": c.security_id, "name": c.legal_name, "class": c.class_designation,
             "mic": c.mic, "ticker": c.ticker, "from": c.valid_from, "to": c.valid_to,
             "confidence": c.confidence, "status": c.status}
            for c in resolution.candidates
        ]
        table = _render_table(rows, [("security_id", "SECURITY"), ("name", "NAME"), ("class", "CLASS"),
                                     ("mic", "MIC"), ("ticker", "TICKER"), ("from", "FROM"), ("to", "TO"),
                                     ("confidence", "CONF"), ("status", "STATUS")])
        text = table + "\n\nconfidence: " + resolution.confidence + "\n" + payload["reasoning_text"]
        _emit(args, payload, table=text)
        return 0
    if args.security_id:
        profile = master.security_profile(args.security_id)
        _emit(args, {"profile": profile, "summary": json.dumps(profile["security"])}, table=None)
        return 0
    raise ValidationError("entity show requires --cik, --ticker or --security-id")


def _resolve_entity_id(db: Database, args: argparse.Namespace) -> str:
    master = SecurityMaster(db)
    if getattr(args, "cik", None):
        issuer = master.require_issuer_by_cik(args.cik)
        return issuer["issuer_id"]
    if getattr(args, "security_id", None):
        return args.security_id
    raise ValidationError("provide --cik or --security-id")


def _facts_rows(result) -> list[dict[str, Any]]:
    rows = []
    for fact in result.facts:
        rows.append(
            {
                "concept": fact.concept,
                "period_end": fact.period_end,
                "value": fact.value if fact.value is not None else fact.value_text,
                "unit": fact.unit,
                "accession": fact.accession_number,
                "form": fact.form_type,
                "available": fact.availability_time,
                "source_concept": fact.source_concept,
                "derivation": fact.derivation_kind,
            }
        )
    return rows


def cmd_facts(db: Database, args: argparse.Namespace) -> int:
    entity_id = _resolve_entity_id(db, args)
    kernel = EvidenceKernel(db)
    as_of = args.as_of or iso(utcnow())
    result = kernel.as_of(
        entity_id,
        as_of,
        mode=args.mode,
        concepts=args.concept or None,
        statement=args.statement,
        include_unknown=args.include_unknown,
        engine=args.engine,
    )
    rows = _facts_rows(result)
    table = _render_table(
        rows,
        [("concept", "CONCEPT"), ("period_end", "PERIOD END"), ("value", "VALUE"), ("unit", "UNIT"),
         ("accession", "ACCESSION"), ("form", "FORM"), ("available", "AVAILABLE"),
         ("source_concept", "SOURCE TAG"), ("derivation", "DERIVATION")],
    )
    payload = result.to_dict()
    payload["summary"] = (
        f"{len(result.facts)} fact(s) as of {result.as_of} under {result.mode}; completeness: {result.completeness}"
    )
    if result.contradictions:
        payload["summary"] += f"; {len(result.contradictions)} contradiction(s)"
    note_text = ""
    if result.notes:
        note_text = "\n\nnotes:\n  " + "\n  ".join(result.notes)
    _emit(args, payload, table=table + "\n\n" + payload["summary"] + note_text)
    return 0


def cmd_asof(db: Database, args: argparse.Namespace) -> int:
    return cmd_facts(db, args)


def cmd_explain(db: Database, args: argparse.Namespace) -> int:
    kernel = EvidenceKernel(db)
    report = kernel.provenance(args.evidence_id, include_raw_body=False)
    payload = report.to_dict()
    header = [
        {"field": "evidence_id", "value": report.evidence_id},
        {"field": "concept", "value": report.record.concept},
        {"field": "value", "value": f"{report.record.value_numeric} {report.record.unit}"},
        {"field": "period", "value": f"{report.record.period_start or '(instant)'}..{report.record.period_end or ''}"},
        {"field": "derivation", "value": report.record.derivation_kind},
        {"field": "quality", "value": f"{report.record.quality}/{report.record.verification}"},
        {"field": "availability", "value": f"{report.record.availability_time} ({report.record.availability_precision})"},
        {"field": "observed_at", "value": report.record.observed_at},
        {"field": "accession", "value": report.record.accession_number},
        {"field": "source", "value": (report.source or {}).get("name")},
        {"field": "raw document", "value": (report.raw_document or {}).get("doc_id")},
    ]
    chain_rows = [
        {"evidence_id": entry["evidence_id"], "value": entry["value"], "revision": entry["revision_kind"],
         "available": entry["availability_time"], "accession": entry["accession_number"],
         "superseded_by": ", ".join(entry["superseded_by"])}
        for entry in report.revision_chain
    ]
    text = _render_table(header, [("field", "FIELD"), ("value", "VALUE")])
    text += "\n\nrevision chain:\n" + _render_table(
        chain_rows,
        [("evidence_id", "EVIDENCE"), ("value", "VALUE"), ("revision", "REVISION"),
         ("available", "AVAILABLE"), ("accession", "ACCESSION"), ("superseded_by", "SUPERSEDED BY")],
    )
    text += "\n\nnarrative:\n  " + "\n  ".join(report.narrative)
    if report.limitations:
        text += "\n\nlimitations:\n  " + "\n  ".join(report.limitations)
    _emit(args, payload, table=text)
    return 0


def cmd_bars_import(db: Database, args: argparse.Namespace) -> int:
    master = SecurityMaster(db)
    if master.security(args.security_id) is None:
        raise MissingDataError("unknown security", security_id=args.security_id)
    source_id = SourceRegistry(db).ensure_custom(
        args.source_name,
        kind="csv_import",
        licence=args.licence,
        redistribution="user_responsibility",
        notes="imported by atlas bars import",
    )
    calendar = TradingCalendar(db)
    try:
        calendar.ensure_venue(args.mic)
    except ValidationError:
        calendar = None
    result = (
        import_parquet_bars(args.file, security_id=args.security_id, mic=args.mic, source_id=source_id,
                            currency=args.currency, calendar=calendar)
        if str(args.file).lower().endswith(".parquet")
        else import_csv_bars(args.file, security_id=args.security_id, mic=args.mic, source_id=source_id,
                             currency=args.currency, calendar=calendar)
    )
    store = BarStore(db)
    summary = store.ingest(result.bars)
    if calendar is not None and result.bars:
        dates = sorted(bar.session_date for bar in result.bars)
        calendar.ensure_range(args.mic, dates[0], dates[-1])
    payload = {
        "file": str(args.file),
        "security_id": args.security_id,
        "mic": args.mic.upper(),
        "source_id": source_id,
        "import": result.to_dict(),
        "stored": summary.to_dict(),
    }
    payload["summary"] = (
        f"read {result.rows_read} row(s), imported {len(result.bars)}, "
        f"stored inserted={summary.inserted} duplicates={summary.duplicates} revisions={summary.revisions}; "
        f"{len(result.issues)} import issue(s)"
    )
    table_rows = [{"metric": key, "value": value} for key, value in payload["stored"].items()]
    table_rows += [{"metric": "import issues", "value": len(result.issues)}]
    _emit(args, payload, table=_render_table(table_rows, [("metric", "METRIC"), ("value", "VALUE")]))
    return 0


def cmd_bars_show(db: Database, args: argparse.Namespace) -> int:
    store = BarStore(db)
    bars = store.query(args.security_id, args.mic, args.start, args.end)
    if not bars:
        _emit(args, {"bars": [], "summary": "no bars in range"})
        return 0
    actions = ActionStore(db).list(args.security_id, knowledge_as_of=args.knowledge_as_of)
    if args.adjustment == "raw":
        payload = {"security_id": args.security_id, "adjustment": "raw", "bars": [b.to_dict() for b in bars]}
        rows = [
            {"session": b.session_date, "open": b.open, "high": b.high, "low": b.low, "close": b.close,
             "volume": b.volume, "revision": b.revision_seq}
            for b in bars
        ]
        table = _render_table(rows, [("session", "SESSION"), ("open", "OPEN"), ("high", "HIGH"),
                                     ("low", "LOW"), ("close", "CLOSE"), ("volume", "VOLUME"),
                                     ("revision", "REV")])
    else:
        series = (
            split_adjust(bars, actions, knowledge_as_of=args.knowledge_as_of)
            if args.adjustment == "split"
            else total_return(bars, actions, knowledge_as_of=args.knowledge_as_of)
        )
        payload = series.to_dict()
        index = dict(series.total_return_index)
        rows = [
            {"session": bar.session_date, "close": bar.close, "factor": bar.split_factor,
             "dividend": bar.dividend, "tr_index": index.get(bar.session_date, ""), "volume": bar.volume}
            for bar in series.bars
        ]
        table = _render_table(rows, [("session", "SESSION"), ("close", "ADJ CLOSE"), ("factor", "SPLIT FCTR"),
                                     ("dividend", "DIVIDEND"), ("tr_index", "TR INDEX"), ("volume", "VOLUME")])
        if series.warnings:
            table += "\n\nwarnings:\n  " + "\n  ".join(series.warnings)
    payload["adjustment_status"] = payload.get("adjustment_status", args.adjustment)
    payload["summary"] = (
        f"{len(bars)} bar(s), adjustment={args.adjustment}, status={payload['adjustment_status']}"
    )
    _emit(args, payload, table=table + "\n\n" + payload["summary"])
    return 0


def cmd_bars_validate(db: Database, args: argparse.Namespace) -> int:
    store = BarStore(db)
    calendar = TradingCalendar(db)
    try:
        calendar.ensure_venue(args.mic)
    except ValidationError:
        calendar = None
    action_dates = {
        row["ex_date"]
        for row in db.query(
            "SELECT ex_date FROM corporate_action WHERE security_id = ? AND ex_date IS NOT NULL",
            (args.security_id,),
        )
    }
    findings = store.validate(
        args.security_id,
        args.mic,
        start=args.start,
        end=args.end,
        calendar=calendar,
        known_action_dates=action_dates,
    )
    errors = [f for f in findings if f["severity"] == "error"]
    payload = {
        "security_id": args.security_id,
        "mic": args.mic.upper(),
        "findings": findings,
        "errors": len(errors),
        "warnings": len([f for f in findings if f["severity"] == "warning"]),
        "summary": f"{len(errors)} error(s), {len(findings) - len(errors)} other finding(s)",
    }
    table = _render_table(findings, [("severity", "SEVERITY"), ("code", "CODE"), ("detail", "DETAIL")])
    _emit(args, payload, table=table + "\n\n" + payload["summary"])
    return 1 if errors else 0


def cmd_actions_list(db: Database, args: argparse.Namespace) -> int:
    store = ActionStore(db)
    actions = store.list(
        args.security_id,
        knowledge_as_of=args.knowledge_as_of,
        action_types=args.type or None,
        include_superseded=args.include_superseded,
    )
    rows = [
        {
            "action_id": a.action_id, "type": a.action_type, "ex_date": a.ex_date,
            "terms": f"{a.ratio_to}:{a.ratio_from}" if a.ratio_from and a.ratio_to else
                     (f"{a.cash_amount} {a.currency}" if a.cash_amount is not None else (a.terms or "")),
            "status": a.status, "available": a.availability_time, "computable": a.action_type in
            {"split", "reverse_split", "cash_dividend"},
        }
        for a in actions
    ]
    table = _render_table(rows, [("action_id", "ACTION"), ("type", "TYPE"), ("ex_date", "EX DATE"),
                                 ("terms", "TERMS"), ("status", "STATUS"), ("available", "AVAILABLE"),
                                 ("computable", "COMPUTED")])
    _emit(
        args,
        {"security_id": args.security_id, "actions": [a.to_dict() for a in actions],
         "coverage": store.coverage(args.security_id), "summary": f"{len(actions)} action(s)"},
        table=table + f"\n\n{len(actions)} action(s)",
    )
    return 0


def cmd_actions_add(db: Database, args: argparse.Namespace) -> int:
    master = SecurityMaster(db)
    if master.security(args.security_id) is None:
        raise MissingDataError("unknown security", security_id=args.security_id)
    source_id = SourceRegistry(db).ensure_custom(
        args.source_name, kind="manual", licence=args.licence,
        redistribution="user_responsibility", notes="corporate action entered via CLI",
    )
    ratio_from = ratio_to = None
    if args.ratio:
        parts = str(args.ratio).replace("-", ":").split(":")
        if len(parts) != 2:
            raise ValidationError("ratio must be 'to:from' or 'a-for-b'", ratio=args.ratio)
        ratio_to, ratio_from = Decimal(parts[0]), Decimal(parts[1])
    if args.ratio_from is not None:
        ratio_from = Decimal(str(args.ratio_from))
    if args.ratio_to is not None:
        ratio_to = Decimal(str(args.ratio_to))
    terms: dict[str, Any] = {}
    if args.new_ticker:
        terms["new_ticker"] = args.new_ticker
    action = CorporateAction(
        security_id=args.security_id,
        action_type=args.type,
        source_id=source_id,
        ex_date=args.ex_date,
        effective_date=args.effective_date,
        record_date=args.record_date,
        payable_date=args.payable_date,
        ratio_from=ratio_from,
        ratio_to=ratio_to,
        cash_amount=Decimal(str(args.cash)) if args.cash is not None else None,
        currency=args.currency if args.cash is not None else None,
        terms=terms,
        status=args.status,
        notes=args.notes,
    )
    availability = None
    if args.available_at:
        availability = (
            availability_from_instant(args.available_at, "cli.manual.available_at")
            if "T" in str(args.available_at)
            else availability_from_date(args.available_at, "cli.manual.available_date")
        )
    action_id = ActionStore(db).add(action, availability=availability)
    payload = {"action_id": action_id, "action": action.to_dict()}
    payload["summary"] = f"recorded {args.type} action {action_id}"
    _emit(args, payload, table=payload["summary"])
    return 0


def cmd_validate(db: Database, args: argparse.Namespace) -> int:
    report = run_validation(db, issuer_id=args.issuer_id, security_id=args.security_id)
    payload = report.to_dict()
    payload["summary"] = f"{len(report.errors)} error(s), {len(report.warnings)} warning(s), {len(report.findings)} finding(s)"
    rows = [
        {"severity": f["severity"], "code": f["code"], "subject": f["subject"], "detail": f["detail"]}
        for f in report.findings
    ]
    table = _render_table(rows, [("severity", "SEVERITY"), ("code", "CODE"), ("subject", "SUBJECT"),
                                 ("detail", "DETAIL")])
    if not rows:
        table = "no findings"
    _emit(args, payload, table=table + "\n\n" + payload["summary"])
    return 0 if report.ok else 1


def cmd_stats(db: Database, args: argparse.Namespace) -> int:
    stats = summarize(db)
    stats["issues_log"] = list_issues(db, limit=args.issue_limit)
    rows = [{"metric": f"table:{name}", "value": count} for name, count in stats["tables"].items()]
    for key, value in stats["evidence"].items():
        if key in {"entity_id", "by_concept", "by_quality", "by_derivation"}:
            continue
        rows.append({"metric": f"evidence:{key}", "value": value})
    for severity, count in stats["issues"].items():
        rows.append({"metric": f"issues:{severity}", "value": count})
    rows.append({"metric": "integrity_check", "value": stats["integrity_check"]})
    _emit(args, stats, table=_render_table(rows, [("metric", "METRIC"), ("value", "VALUE")]))
    return 0


def cmd_serve(db: Database, args: argparse.Namespace) -> int:
    """Serve the terminal API locally.

    The default bind address is loopback: the terminal exposes company research data and
    write access to watchlists/workspaces, so it must not be reachable from the network
    unless the operator explicitly asks for it.
    """
    import uvicorn

    from .terminal.api import create_app

    from .terminal.exposure import assess_bind

    decision = assess_bind(
        args.host, allow_non_loopback=bool(getattr(args, "allow_non_loopback", False))
    )
    if not decision["permitted"]:
        print(str(decision["reason"]), file=sys.stderr)
        return 2
    if decision["warning"]:
        print(str(decision["warning"]), file=sys.stderr)
    app = create_app(db.path, web_dist=args.web_dist)
    if not args.json:
        print(f"Atlas terminal on http://{args.host}:{args.port} (database: {db.path})", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_demo(db: Database, args: argparse.Namespace) -> int:
    from .demo import run_demo

    result = run_demo(
        db_path=str(args.db_path) if getattr(args, "db_path", None) else "var/demo/atlas-demo.db",
        fixture_dir=args.fixtures,
        reset=not args.keep,
        stream=print,
    )
    _emit(args, result)
    return 0


def cmd_sec_history(db: Database, args: argparse.Namespace) -> int:
    """Report which submissions archives have been ingested for a registrant."""
    store = SubmissionsHistoryStore(db)
    normalized = normalize_cik(args.cik)
    expected = _expected_history_descriptors(db, normalized)
    coverage = store.coverage(normalized, expected)
    state = store.state(normalized)
    rows = [
        {
            "file": item["name"],
            "rows": item["filing_rows"],
            "advertised": item["advertised_count"],
            "from": item["advertised_from"],
            "to": item["advertised_to"],
            "fetched": item["fetched_at"],
        }
        for item in state
    ]
    table = _render_table(
        rows,
        [("file", "ARCHIVE"), ("rows", "ROWS"), ("advertised", "ADVERTISED"),
         ("from", "FROM"), ("to", "TO"), ("fetched", "FETCHED")],
    )
    payload = {
        "cik": normalized,
        "coverage": coverage.to_dict(),
        "archives": state,
    }
    payload["summary"] = (
        f"{len(coverage.recorded_files)}/{len(coverage.expected_files)} archive(s) ingested; "
        f"{coverage.recorded_rows}/{coverage.advertised_filings} advertised filing(s); "
        f"history complete={coverage.complete}"
    )
    _emit(args, payload, table=table + "\n\n" + payload["summary"])
    return 0


def _expected_history_descriptors(db: Database, cik: str) -> list[dict[str, Any]]:
    """Read advertised archive descriptors from the stored submissions document."""
    rows = db.query(
        "SELECT body FROM raw_document WHERE url LIKE ? ORDER BY retrieved_at DESC LIMIT 5",
        ("%submissions%",),
    )
    for row in rows:
        try:
            payload = json.loads(row["body"])
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or normalize_cik(payload.get("cik", "0")) != cik:
            continue
        descriptors = ((payload.get("filings") or {}).get("files") or [])
        return [entry for entry in descriptors if entry.get("name")]
    return []


def cmd_reconcile(db: Database, args: argparse.Namespace) -> int:
    """Independently verify stored facts against the original SEC payload."""
    normalized = normalize_cik(args.cik)
    if args.offline:
        _, payload, _, _ = load_fixture_payloads(args.offline, args.cik)
    else:
        user_agent = args.user_agent or os.environ.get("ATLAS_SEC_USER_AGENT")
        client = SecClient(user_agent=user_agent, db=db, requests_per_second=args.rate)
        payload, _ = client.get_json(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{normalized}.json"
        )
    report = reconcile_companyfacts(db, payload, cik=normalized)
    findings = report.errors if args.errors_only else report.findings
    rows = [finding.to_dict() for finding in findings]
    table = _render_table(
        rows,
        [("severity", "SEVERITY"), ("code", "CODE"), ("concept", "CONCEPT"),
         ("period_end", "PERIOD"), ("accession", "ACCESSION"), ("detail", "DETAIL")],
    )
    result = report.to_dict()
    result["summary"] = (
        f"{report.coverage}; {len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    )
    _emit(args, result, table=(table if rows else "no findings") + "\n\n" + result["summary"])
    _log_run(db, f"reconcile {normalized}", "completed" if report.ok else "failed", result)
    return 0 if report.ok else 1


def cmd_deps(db: Database, args: argparse.Namespace) -> int:
    """Inspect the reverse dependency index over derived computations."""
    index = DependencyIndex(db)
    if args.backfill:
        recorded = index.backfill()
        summary = index.summary()
        payload = {"backfilled": recorded, **summary}
        payload["summary"] = (
            f"indexed {recorded} derived computation(s); {summary['computations']} total"
        )
        _emit(args, payload, table=payload["summary"])
        return 0
    if args.evidence_id:
        impact = index.impact(args.evidence_id)
        rows = [
            {
                "depth": 0,
                "computation": computation.computation_id,
                "rule": computation.rule_id,
                "output": computation.output_evidence_id,
                "stale": any(item["computation_id"] == computation.computation_id for item in impact.stale),
            }
            for computation in impact.direct
        ]
        rows += [
            {
                "depth": depth,
                "computation": computation.computation_id,
                "rule": computation.rule_id,
                "output": computation.output_evidence_id,
                "stale": any(item["computation_id"] == computation.computation_id for item in impact.stale),
            }
            for depth, computation in impact.transitive
        ]
        payload = impact.to_dict()
        payload["summary"] = (
            f"{len(impact.direct)} direct, {len(impact.transitive)} transitive, "
            f"{len(impact.stale)} stale computation(s)"
        )
        table = _render_table(
            rows,
            [("depth", "DEPTH"), ("computation", "COMPUTATION"), ("rule", "RULE"),
             ("output", "OUTPUT"), ("stale", "STALE")],
        )
        _emit(args, payload, table=table + "\n\n" + payload["summary"])
        return 0
    summary = index.summary()
    rows = [{"rule": rule, "computations": count} for rule, count in summary["by_rule"].items()]
    payload = {**summary}
    payload["summary"] = (
        f"{summary['computations']} computation(s), {summary['inputs']} input edge(s), "
        f"{len(summary['findings'])} integrity finding(s)"
    )
    table = _render_table(rows, [("rule", "RULE"), ("computations", "N")])
    _emit(args, payload, table=table + "\n\n" + payload["summary"])
    return 0 if summary["ok"] else 1


def cmd_app(db: Database, args: argparse.Namespace) -> int:
    from .applications.cli import run as run_app

    return run_app(db, args)


def cmd_migrate(db: Database, args: argparse.Namespace) -> int:
    from .storage.safety import migrate_safely

    payload = migrate_safely(db, backup_dir=args.backup_dir)
    table = (f"schema {payload['from_version']} -> {payload['to_version']}\n"
             f"status {payload['status']}\n"
             f"backup {payload['backup_path'] or 'none'}")
    _emit(args, payload, table=table)
    return 0


def cmd_doctor(db: Database, args: argparse.Namespace) -> int:
    from .storage.migrations import LATEST_VERSION

    schema = db.schema_version()
    integrity = db.integrity_check()
    foreign = db.foreign_key_violations()
    counts = {"evidence": db.row_count("evidence"), "economic_observations": db.row_count(
        "economic_observation"
    )}
    if schema >= 10:
        counts.update({
            "application_installations": db.row_count("application_installation"),
            "application_executions": db.row_count("application_execution"),
            "domain_packs": db.row_count("domain_pack_installation"),
        })
    migrations = [dict(row) for row in db.applied_migrations()]
    ok = integrity == "ok" and not foreign and schema == LATEST_VERSION
    payload = {
        "schema": "atlas.doctor.v1",
        "status": "ok" if ok else "attention_required",
        "database": db.path,
        "schema_version": schema,
        "supported_schema": LATEST_VERSION,
        "integrity": integrity,
        "foreign_key_violations": len(foreign),
        "counts": counts,
        "migrations": migrations,
        "package_schema": "atlas.application_package.v1",
        "signature_support": "unsupported: unsigned packages are integrity-checked, publisher identity is not verified",
        "untrusted_executable_support": "unsupported: no Python, JavaScript, shell or native extensions are executed",
    }
    _emit(args, payload, table=f"status {payload['status']} · schema {schema}/{LATEST_VERSION} · "
                                f"integrity {integrity} · foreign keys {len(foreign)}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas",
        description="Atlas Quant - Phase 1 financial data and temporal evidence engine",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite database path (default: {DEFAULT_DB})")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_db_path_options(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--db-path", default=None, help="database file for this command (overrides --db)")

    init = subparsers.add_parser("init", help="create or migrate the database")
    init.set_defaults(func=cmd_init)

    migrate = subparsers.add_parser("migrate", help="back up, migrate and verify the database")
    migrate.add_argument("--backup-dir", default=None, help="directory for the pre-migration backup")
    migrate.set_defaults(func=cmd_migrate)

    doctor = subparsers.add_parser("doctor", help="diagnose schema, integrity and package support")
    doctor.set_defaults(func=cmd_doctor)

    app = subparsers.add_parser("app", help="portable application SDK, packages and domain packs")
    app_sub = app.add_subparsers(dest="app_command", required=True)
    app_init = app_sub.add_parser("init", help="scaffold a declarative application project")
    app_init.add_argument("directory")
    app_init.add_argument("--name", required=True)
    app_init.add_argument("--application-id", default=None)
    app_init.add_argument("--version", default="1.0.0")
    app_init.set_defaults(func=cmd_app)
    for name in ("validate", "test"):
        item = app_sub.add_parser(name, help=f"{name} an application source project")
        item.add_argument("--file", required=True)
        item.set_defaults(func=cmd_app)
    app_build = app_sub.add_parser("build", help="build a deterministic .atlas package")
    app_build.add_argument("--file", required=True)
    app_build.add_argument("--out", required=True)
    app_build.set_defaults(func=cmd_app)
    app_inspect = app_sub.add_parser("inspect", help="inspect a package without installing it")
    app_inspect.add_argument("--package", required=True)
    app_inspect.set_defaults(func=cmd_app)
    app_verify = app_sub.add_parser("verify", help="verify package integrity")
    app_verify.add_argument("--package", required=True)
    app_verify.set_defaults(func=cmd_app)
    app_install = app_sub.add_parser("install", help="install a package transactionally")
    app_install.add_argument("--package", required=True)
    app_install.set_defaults(func=cmd_app)
    app_list = app_sub.add_parser("list", help="list locally installed applications")
    app_list.set_defaults(func=cmd_app)
    app_gallery = app_sub.add_parser("gallery", help="alias for list")
    app_gallery.set_defaults(func=cmd_app)
    app_open = app_sub.add_parser("open", help="open an installed application")
    app_open.add_argument("--install-id", required=True)
    app_open.set_defaults(func=cmd_app)
    app_execute = app_sub.add_parser("execute", help="execute through the installed Atlas runtime")
    app_execute.add_argument("--install-id", required=True)
    app_execute.add_argument("--inputs", default=None, help="JSON input overrides")
    app_execute.set_defaults(func=cmd_app)
    app_export = app_sub.add_parser("export", help="export a package or a saved economic run")
    app_export.add_argument("--install-id", default=None)
    app_export.add_argument("--object-id", default=None)
    app_export.add_argument("--run-id", default=None)
    app_export.add_argument("--scenario-id", default=None)
    app_export.add_argument("--version", default="1.0.0")
    app_export.add_argument("--out", required=True)
    app_export.set_defaults(func=cmd_app)
    app_fork = app_sub.add_parser("fork", help="fork an installed application locally")
    app_fork.add_argument("--install-id", required=True)
    app_fork.add_argument("--name", required=True)
    app_fork.add_argument("--version", required=True)
    app_fork.set_defaults(func=cmd_app)
    app_compare = app_sub.add_parser("compare", help="compare two installed applications")
    app_compare.add_argument("--left", required=True)
    app_compare.add_argument("--right", required=True)
    app_compare.set_defaults(func=cmd_app)
    app_uninstall = app_sub.add_parser("uninstall", help="remove an installation, retaining research")
    app_uninstall.add_argument("--install-id", required=True)
    app_uninstall.set_defaults(func=cmd_app)
    app_pack = app_sub.add_parser("pack", help="declarative domain packs")
    pack_sub = app_pack.add_subparsers(dest="pack_command", required=True)
    pack_install = pack_sub.add_parser("install", help="install a domain pack and its packages")
    pack_install.add_argument("--file", required=True)
    pack_install.set_defaults(func=cmd_app)
    pack_list = pack_sub.add_parser("list", help="list installed domain packs")
    pack_list.set_defaults(func=cmd_app)
    pack_inspect = pack_sub.add_parser("inspect", help="inspect an installed domain pack")
    pack_inspect.add_argument("--pack-id", required=True)
    pack_inspect.add_argument("--version", required=True)
    pack_inspect.set_defaults(func=cmd_app)
    pack_uninstall = pack_sub.add_parser("uninstall", help="remove pack metadata")
    pack_uninstall.add_argument("--pack-id", required=True)
    pack_uninstall.add_argument("--version", required=True)
    pack_uninstall.set_defaults(func=cmd_app)

    concepts = subparsers.add_parser("concepts", help="list the canonical concept registry")
    concepts.set_defaults(func=cmd_concepts)

    sec = subparsers.add_parser("sec", help="SEC EDGAR ingestion")
    sec_sub = sec.add_subparsers(dest="sec_command", required=True)
    sync = sec_sub.add_parser("sync", help="sync a company's SEC filings and XBRL facts")
    sync.add_argument("--cik", required=True, help="SEC CIK, e.g. 320193")
    sync.add_argument("--offline", default=None, help="directory of archived SEC payloads (no network)")
    sync.add_argument("--user-agent", default=None, help="SEC User-Agent with contact email")
    sync.add_argument("--rate", type=float, default=5.0, help="max requests per second (SEC allows 10)")
    sync.add_argument("--no-history", dest="no_history", action="store_true",
                      help="skip the filings.files history archives (filing list stays incomplete)")
    sync.add_argument("--history-limit", dest="history_limit", type=int, default=None,
                      help="fetch at most N history archives (coverage is reported as incomplete)")
    sync.set_defaults(func=cmd_sec_sync, no_history=False, history_limit=None)
    history = sec_sub.add_parser("history", help="report submissions-archive coverage")
    history.add_argument("--cik", required=True)
    history.set_defaults(func=cmd_sec_history)
    filings = sec_sub.add_parser("filings", help="list stored filings")
    filings.add_argument("--cik", required=True)
    filings.add_argument("--form", action="append", help="filter by form type (repeatable)")
    filings.add_argument("--limit", type=int, default=25)
    filings.set_defaults(func=cmd_sec_filings)

    entity = subparsers.add_parser("entity", help="inspect identity records")
    entity_sub = entity.add_subparsers(dest="entity_command", required=True)
    show = entity_sub.add_parser("show", help="show issuer or security identity")
    show.add_argument("--cik", default=None)
    show.add_argument("--ticker", default=None)
    show.add_argument("--security-id", default=None)
    show.add_argument("--as-of", default=None, help="resolve a ticker as of this date")
    show.set_defaults(func=cmd_entity_show)

    facts = subparsers.add_parser("facts", help="retrieve financial facts (point-in-time)")
    facts.add_argument("--cik", default=None)
    facts.add_argument("--security-id", default=None)
    facts.add_argument("--statement", default=None, choices=["income", "balance", "cashflow"])
    facts.add_argument("--concept", action="append", help="restrict to a canonical concept (repeatable)")
    facts.add_argument("--as-of", default=None, help="ISO timestamp or date")
    facts.add_argument("--mode", default=AsOfMode.PUBLIC_AVAILABLE.value,
                       choices=[m.value for m in AsOfMode])
    facts.add_argument("--include-unknown", action="store_true",
                       help="include records whose public availability is unevidenced (never treated as available)")
    facts.add_argument("--engine", default="python", choices=["python", "sql"],
                       help="selection implementation (both are differentially tested)")
    facts.set_defaults(func=cmd_facts)

    asof = subparsers.add_parser("asof", help="alias for facts --as-of with explicit time semantics")
    asof.add_argument("--cik", default=None)
    asof.add_argument("--security-id", default=None)
    asof.add_argument("--date", dest="as_of", required=True)
    asof.add_argument("--statement", default=None, choices=["income", "balance", "cashflow"])
    asof.add_argument("--concept", action="append")
    asof.add_argument("--mode", default=AsOfMode.PUBLIC_AVAILABLE.value, choices=[m.value for m in AsOfMode])
    asof.add_argument("--include-unknown", action="store_true")
    asof.add_argument("--engine", default="python", choices=["python", "sql"])
    asof.set_defaults(func=cmd_asof)

    explain = subparsers.add_parser("explain", help="explain the provenance of an evidence record")
    explain.add_argument("--evidence-id", required=True)
    explain.set_defaults(func=cmd_explain)

    bars = subparsers.add_parser("bars", help="market bar import, display and validation")
    bars_sub = bars.add_subparsers(dest="bars_command", required=True)
    bars_import = bars_sub.add_parser("import", help="import OHLCV bars from CSV or Parquet")
    bars_import.add_argument("--file", required=True)
    bars_import.add_argument("--security-id", required=True)
    bars_import.add_argument("--mic", required=True)
    bars_import.add_argument("--currency", default="USD")
    bars_import.add_argument("--source-name", default="user csv import")
    bars_import.add_argument("--licence", default=None)
    bars_import.set_defaults(func=cmd_bars_import)
    bars_show = bars_sub.add_parser("show", help="show raw or adjusted bars")
    bars_show.add_argument("--security-id", required=True)
    bars_show.add_argument("--mic", required=True)
    bars_show.add_argument("--start", required=True)
    bars_show.add_argument("--end", required=True)
    bars_show.add_argument("--adjustment", default="raw", choices=["raw", "split", "total_return"])
    bars_show.add_argument("--knowledge-as-of", default=None,
                           help="only apply corporate actions publicly available by this date")
    bars_show.set_defaults(func=cmd_bars_show)
    bars_validate = bars_sub.add_parser("validate", help="validate a stored bar series")
    bars_validate.add_argument("--security-id", required=True)
    bars_validate.add_argument("--mic", required=True)
    bars_validate.add_argument("--start", default=None)
    bars_validate.add_argument("--end", default=None)
    bars_validate.set_defaults(func=cmd_bars_validate)

    actions = subparsers.add_parser("actions", help="corporate action records")
    actions_sub = actions.add_subparsers(dest="actions_command", required=True)
    actions_list = actions_sub.add_parser("list", help="list corporate actions")
    actions_list.add_argument("--security-id", required=True)
    actions_list.add_argument("--knowledge-as-of", default=None)
    actions_list.add_argument("--type", action="append", choices=[t.value for t in ActionType])
    actions_list.add_argument("--include-superseded", action="store_true")
    actions_list.set_defaults(func=cmd_actions_list)
    actions_add = actions_sub.add_parser("add", help="record a corporate action")
    actions_add.add_argument("--security-id", required=True)
    actions_add.add_argument("--type", required=True, choices=[t.value for t in ActionType])
    actions_add.add_argument("--ex-date", dest="ex_date", default=None)
    actions_add.add_argument("--effective-date", dest="effective_date", default=None)
    actions_add.add_argument("--record-date", dest="record_date", default=None)
    actions_add.add_argument("--payable-date", dest="payable_date", default=None)
    actions_add.add_argument("--ratio", default=None, help="e.g. 4:1 for a four-for-one split")
    actions_add.add_argument("--ratio-from", dest="ratio_from", default=None)
    actions_add.add_argument("--ratio-to", dest="ratio_to", default=None)
    actions_add.add_argument("--cash", default=None, help="cash amount per share")
    actions_add.add_argument("--currency", default="USD")
    actions_add.add_argument("--new-ticker", default=None)
    actions_add.add_argument("--status", default="confirmed",
                             choices=["announced", "confirmed", "corrected", "cancelled", "provisional"])
    actions_add.add_argument("--available-at", default=None, help="when the action became public")
    actions_add.add_argument("--source-name", default="manual corporate action entry")
    actions_add.add_argument("--licence", default=None)
    actions_add.add_argument("--notes", default=None)
    actions_add.set_defaults(func=cmd_actions_add)

    reconcile = subparsers.add_parser(
        "reconcile", help="verify stored facts independently against the original SEC payload"
    )
    reconcile.add_argument("--cik", required=True)
    reconcile.add_argument("--offline", default=None, help="directory of archived SEC payloads")
    reconcile.add_argument("--user-agent", default=None)
    reconcile.add_argument("--rate", type=float, default=5.0)
    reconcile.add_argument("--errors-only", dest="errors_only", action="store_true")
    reconcile.set_defaults(func=cmd_reconcile, errors_only=False)

    deps = subparsers.add_parser("deps", help="inspect the derived-computation dependency index")
    deps.add_argument("--evidence-id", default=None, help="report everything that depends on this evidence")
    deps.add_argument("--backfill", action="store_true", help="index derived records stored before schema v2")
    deps.set_defaults(func=cmd_deps)

    validate = subparsers.add_parser("validate", help="run dataset integrity checks")
    validate.add_argument("--issuer-id", default=None)
    validate.add_argument("--security-id", default=None)
    validate.set_defaults(func=cmd_validate)

    stats = subparsers.add_parser("stats", help="dataset and ingestion statistics")
    stats.add_argument("--issue-limit", type=int, default=10)
    stats.set_defaults(func=cmd_stats)

    demo = subparsers.add_parser("demo", help="run the offline end-to-end demonstration")
    add_db_path_options(demo)
    demo.add_argument("--fixtures", default=None, help="fixture root (default: ./fixtures)")
    demo.add_argument("--keep", action="store_true", help="reuse an existing demo database")
    demo.set_defaults(func=cmd_demo)

    serve = subparsers.add_parser(
        "serve", help="run the Phase 2 terminal API (and the built UI when web/dist exists)"
    )
    add_db_path_options(serve)
    serve.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    serve.add_argument("--web-dist", default=None, help="built frontend directory (default web/dist)")
    serve.add_argument(
        "--allow-non-loopback", action="store_true",
        help=(
            "acknowledge that the unauthenticated API will be reachable beyond loopback; "
            "an acknowledgement is not authentication (env: ATLAS_ALLOW_NON_LOOPBACK=1)"
        ),
    )
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        db = Database(args.db) if getattr(args, "command", None) == "migrate" else open_database(args.db)
    except AtlasError as exc:
        print(json.dumps(exc.to_dict()) if args.json else f"error: {exc}", file=sys.stderr)
        return 2
    try:
        if getattr(args, "command", None) != "migrate":
            from .storage.sources import ensure_default_sources

            ensure_default_sources(db)
        return args.func(db, args)
    except BrokenPipeError:  # pragma: no cover - downstream closed the pipe (e.g. | head)
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except AtlasError as exc:
        _log_run(db, getattr(args, "command", "unknown"), "failed", None, str(exc))
        if args.json:
            print(json.dumps(exc.to_dict(), indent=2), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
