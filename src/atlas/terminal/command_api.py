"""The command index behind the global command palette.

One request returns every entity class the palette can act on, each with the route or
command that performs the action. The index is built from the database at request time, so
a result can never point at functionality that does not exist: an issuer that is not in
this database is absent, and a saved workspace that was deleted disappears.

The surface is read-only and bounded. It does not accept a query or a path from the client;
filtering happens in the browser over an already-bounded index.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends

from ..core.temporal import iso, utcnow
from ..fec.operators import REGISTRY
from ..research.financial_concepts import CONCEPTS
from ..terminal import read_models

SCHEMA = "atlas.command_index.v1"

#: Per-category ceilings. The palette is a launcher, not a bulk export.
LIMITS = {
    "companies": 400,
    "filings": 150,
    "questions": 60,
    "filings_per_issuer": 12,
    "objects": 100,
    "experiments": 60,
    "workspaces": 50,
    "packages": 50,
}

#: Concepts used to propose answerable questions. A question is a *lead*: the resolver may
#: still refuse it, and the palette says so rather than promising an answer.
QUESTION_CONCEPTS = ("revenue", "net_income", "operating_income", "total_assets",
                     "operating_cash_flow")


def _has_table(db: Any, name: str) -> bool:
    return bool(db.scalar(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name = ?", (name,), default=0
    ))


def build_index(db: Any) -> dict[str, Any]:
    companies = read_models.list_companies(db, limit=LIMITS["companies"])
    company_items = [
        {
            "id": item["issuer_id"],
            "label": item["securities"][0]["tickers"][0]["ticker"]
            if item.get("securities") and item["securities"][0].get("tickers")
            else item["legal_name"],
            "description": item["legal_name"],
            "category": "companies",
            "action": {"kind": "navigate", "path": f"/companies/{item['issuer_id']}"},
            "metadata": {"cik": item.get("cik"),
                         "security_ids": [s["security_id"] for s in item.get("securities", [])]},
        }
        for item in companies
    ]

    concept_items = [
        {
            "id": concept.key,
            "label": concept.aliases[0] if concept.aliases else concept.key,
            "description": f"{concept.statement} {concept.kind}",
            "category": "concepts",
            "action": {"kind": "concept", "concept": concept.key,
                       "statement": concept.statement},
            "metadata": {"aliases": list(concept.aliases)},
        }
        for concept in sorted(CONCEPTS.values(), key=lambda item: item.key)
    ]

    filing_items: list[dict[str, Any]] = []
    question_items: list[dict[str, Any]] = []
    if _has_table(db, "knowledge_document"):
        rows = db.query(
            "SELECT document_id, issuer_id, accession, form_type, filed_date, availability_time, "
            "availability_precision, status FROM knowledge_document "
            "ORDER BY COALESCE(filed_date, '') DESC LIMIT ?",
            (LIMITS["filings"],),
        )
        for row in rows:
            filing_items.append({
                "id": row["document_id"],
                "label": f"{row['form_type']} {row['accession']}",
                "description": f"{row['issuer_id']} · filed {row['filed_date'] or 'unknown'}",
                "category": "filings",
                "action": {"kind": "navigate",
                           "path": f"/filings?accession={row['accession']}"},
                "metadata": {
                    "issuer_id": row["issuer_id"],
                    "accession": row["accession"],
                    "availability_time": row["availability_time"],
                    "availability_precision": row["availability_precision"],
                    # An estimated availability is flagged here so the palette cannot
                    # present a modelled bound as a verified release instant.
                    "availability_is_estimated": row["availability_precision"]
                    not in {"exact", "date"},
                    "status": row["status"],
                },
            })
        latest = db.query(
            "SELECT issuer_id, MAX(period_of_report) AS period FROM knowledge_document "
            "WHERE form_type = '10-K' GROUP BY issuer_id ORDER BY issuer_id LIMIT 20"
        )
        for row in latest:
            period = str(row["period"] or "")[:4]
            if len(period) != 4 or not period.isdigit():
                continue
            for key in QUESTION_CONCEPTS:
                concept = CONCEPTS[key]
                question_items.append({
                    "id": f"{row['issuer_id']}:{key}:{period}",
                    "label": f"{concept.aliases[0].title()} · {row['issuer_id']} FY{period}",
                    "description": "Ask Atlas; it may refuse if the cell is not unique",
                    "category": "questions",
                    "action": {"kind": "question", "issuer_id": row["issuer_id"],
                               "concept": key, "period": period},
                    "metadata": {"statement": concept.statement},
                })
        question_items = question_items[:LIMITS["questions"]]

    model_items = [
        {
            "id": key,
            "label": key,
            "description": spec.description,
            "category": "models",
            "action": {"kind": "model", "model": key},
            "metadata": {"version": spec.version, "arity": spec.arity, "formula": spec.formula},
        }
        for key, spec in sorted(REGISTRY.items())
    ]

    object_items: list[dict[str, Any]] = []
    strategy_items: list[dict[str, Any]] = []
    experiment_items: list[dict[str, Any]] = []
    if _has_table(db, "research_object"):
        for row in db.query(
            "SELECT object_id, kind, name, version, status, updated_at FROM research_object "
            "ORDER BY updated_at DESC LIMIT ?", (LIMITS["objects"],)
        ):
            entry = {
                "id": row["object_id"],
                "label": f"{row['name']} v{row['version']}",
                "description": f"{row['kind']} · {row['status']}",
                "category": "research",
                "action": {"kind": "navigate", "path": f"/research?object={row['object_id']}"},
                "metadata": {"kind": row["kind"], "version": row["version"],
                             "status": row["status"], "updated_at": row["updated_at"]},
            }
            object_items.append(entry)
            if row["kind"] == "strategy":
                strategy_items.append({**entry, "category": "strategies",
                                       "action": {"kind": "strategy",
                                                  "object_id": row["object_id"]}})
    if _has_table(db, "quant_run"):
        for row in db.query(
            "SELECT run_id, status, created_at, duration_ms FROM quant_run "
            "ORDER BY created_at DESC LIMIT ?", (LIMITS["experiments"],)
        ):
            experiment_items.append({
                "id": row["run_id"],
                "label": f"Backtest {row['run_id']}",
                "description": f"{row['status']} · {row['duration_ms']:.0f} ms",
                "category": "experiments",
                "action": {"kind": "navigate", "path": f"/lab?run={row['run_id']}"},
                "metadata": {"kind": "quant_run", "created_at": row["created_at"]},
            })
    if _has_table(db, "learning_run"):
        for row in db.query(
            "SELECT run_id, kind, target, status, created_at FROM learning_run "
            "ORDER BY created_at DESC LIMIT ?", (LIMITS["experiments"],)
        ):
            experiment_items.append({
                "id": row["run_id"],
                "label": f"{row['kind']} · {row['target']}",
                "description": f"learning run · {row['status']}",
                "category": "experiments",
                "action": {"kind": "navigate", "path": f"/lab/learning?run={row['run_id']}"},
                "metadata": {"kind": "learning_run", "created_at": row["created_at"]},
            })
        experiment_items = experiment_items[:LIMITS["experiments"]]

    workspace_items: list[dict[str, Any]] = []
    if _has_table(db, "workspace"):
        for row in db.query(
            "SELECT workspace_id, name, updated_at FROM workspace ORDER BY updated_at DESC LIMIT ?",
            (LIMITS["workspaces"],),
        ):
            workspace_items.append({
                "id": row["workspace_id"],
                "label": row["name"],
                "description": "Saved workstation layout",
                "category": "workspaces",
                "action": {"kind": "navigate", "path": f"/workstation/{row['workspace_id']}"},
                "metadata": {"updated_at": row["updated_at"]},
            })

    package_items: list[dict[str, Any]] = []
    if _has_table(db, "application_installation"):
        for row in db.query(
            "SELECT install_id, application_id, version, status FROM application_installation "
            "ORDER BY installed_at DESC LIMIT ?", (LIMITS["packages"],)
        ):
            package_items.append({
                "id": row["install_id"],
                "label": f"{row['application_id']} v{row['version']}",
                "description": f"installed application · {row['status']}",
                "category": "packages",
                "action": {"kind": "navigate", "path": "/applications"},
                "metadata": {"status": row["status"]},
            })

    categories = {
        "companies": company_items,
        "concepts": concept_items,
        "filings": filing_items,
        "questions": question_items,
        "models": model_items,
        "strategies": strategy_items,
        "research": object_items,
        "experiments": experiment_items,
        "workspaces": workspace_items,
        "packages": package_items,
    }
    return {
        "schema": SCHEMA,
        "generated_at": iso(utcnow()),
        "categories": categories,
        "counts": {name: len(items) for name, items in categories.items()},
        "policy": "every entry points at a real route or command; an entity absent from this "
                  "database is absent from the index rather than being offered as a demo",
    }


def register_command_routes(app: Any, get_db: Callable[..., Any]) -> None:
    @app.get("/api/command/index", tags=["system"])
    def command_index(db: Any = Depends(get_db)) -> dict[str, Any]:
        return build_index(db)

    return None


__all__ = ["build_index", "register_command_routes", "LIMITS", "SCHEMA"]
