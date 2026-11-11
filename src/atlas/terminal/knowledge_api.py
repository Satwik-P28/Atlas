"""HTTP surface for the Financial Knowledge Engine.

Every route is read-only over archived documents except ``/search`` and ``/claims``, which
write only a query log. No route accepts a filesystem path, SQL or a document body from the
client: ingestion happens through the offline driver, so the API cannot be used to place
unvetted bytes into the corpus.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.errors import ValidationError
from ..research.knowledge import KnowledgeEngine, POLICY_NOTE, POLICIES
from ..research.knowledge_claims import EPISTEMIC_STATUSES, build_document_claim, revision_report


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=400)
    issuer_id: str | None = Field(default=None, max_length=80)
    cutoff: str | None = Field(default=None, max_length=40)
    policy: str = Field(default="public_available", max_length=40)
    limit: int = Field(default=8, ge=1, le=30)
    forms: list[str] = Field(default_factory=list, max_length=10)
    section: str | None = Field(default=None, max_length=120)
    include_amendments: bool = True


class ClaimRequest(BaseModel):
    issuer_id: str = Field(min_length=3, max_length=80)
    cutoff: str = Field(min_length=8, max_length=40)
    key: str = Field(min_length=2, max_length=80)
    question: str = Field(min_length=2, max_length=400)
    epistemic_status: str = Field(default="observed_fact", max_length=40)
    policy: str = Field(default="public_available", max_length=40)
    forms: list[str] = Field(default_factory=list, max_length=10)


def register_knowledge_routes(app: Any, get_db: Callable[..., Any]) -> None:
    def _engine(db: Any) -> KnowledgeEngine:
        try:
            return KnowledgeEngine(db)
        except Exception as exc:  # noqa: BLE001 - schema may predate migration 014
            raise HTTPException(status_code=503, detail={
                "code": "knowledge_schema_missing",
                "message": "the Financial Knowledge Engine tables are not present; run `atlas migrate`",
                "context": {"error": str(exc)},
            }) from exc

    @app.get("/api/knowledge/stats", tags=["knowledge"])
    def knowledge_stats(db: Any = Depends(get_db)) -> dict[str, Any]:
        return _engine(db).stats()

    @app.get("/api/knowledge/documents", tags=["knowledge"])
    def knowledge_documents(
        issuer_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        db: Any = Depends(get_db),
    ) -> dict[str, Any]:
        items = _engine(db).list_documents(issuer_id=issuer_id, limit=limit)
        return {"items": items, "count": len(items), "schema": "atlas.knowledge.engine.v1"}

    @app.get("/api/knowledge/documents/{document_id}", tags=["knowledge"])
    def knowledge_document(document_id: str, db: Any = Depends(get_db)) -> dict[str, Any]:
        return _engine(db).document(document_id)

    @app.get("/api/knowledge/units/{unit_id}", tags=["knowledge"])
    def knowledge_unit(unit_id: str, db: Any = Depends(get_db)) -> dict[str, Any]:
        return _engine(db).unit(unit_id)

    @app.get("/api/knowledge/documents/{document_id}/tables", tags=["knowledge"])
    def knowledge_tables(
        document_id: str, section: str | None = None,
        limit: int = Query(default=20, ge=1, le=50), db: Any = Depends(get_db),
    ) -> dict[str, Any]:
        engine = _engine(db)
        engine.document(document_id)
        items = engine.tables(document_id=document_id, section=section, limit=limit)
        return {"items": items, "count": len(items)}

    @app.post("/api/knowledge/search", tags=["knowledge"])
    def knowledge_search(body: SearchRequest, db: Any = Depends(get_db)) -> dict[str, Any]:
        if body.policy not in POLICIES:
            raise HTTPException(status_code=422, detail={
                "code": "invalid_policy", "message": "unknown retrieval policy",
                "context": {"supported": list(POLICIES), "note": POLICY_NOTE},
            })
        return _engine(db).search(
            body.query, issuer_id=body.issuer_id, cutoff=body.cutoff, policy=body.policy,
            limit=body.limit, forms=body.forms, section=body.section,
            include_amendments=body.include_amendments,
        )

    @app.post("/api/knowledge/claims", tags=["knowledge"])
    def knowledge_claim(body: ClaimRequest, db: Any = Depends(get_db)) -> dict[str, Any]:
        if body.epistemic_status not in EPISTEMIC_STATUSES:
            raise HTTPException(status_code=422, detail={
                "code": "invalid_epistemic_status", "message": "unknown epistemic status",
                "context": {"supported": list(EPISTEMIC_STATUSES)},
            })
        return build_document_claim(
            _engine(db), issuer_id=body.issuer_id, cutoff=body.cutoff, key=body.key,
            question=body.question, epistemic_status=body.epistemic_status,
            policy=body.policy, forms=body.forms,
        )

    @app.get("/api/knowledge/compare", tags=["knowledge"])
    def knowledge_compare(
        left: str, right: str, db: Any = Depends(get_db)
    ) -> dict[str, Any]:
        return _engine(db).compare(left, right)

    @app.get("/api/knowledge/revisions", tags=["knowledge"])
    def knowledge_revisions(
        left: str,
        right: str,
        issuer_id: str | None = None,
        cutoff: str | None = None,
        db: Any = Depends(get_db),
    ) -> dict[str, Any]:
        engine = _engine(db)
        claims: list[dict[str, Any]] = []
        if issuer_id and cutoff:
            claims = [
                build_document_claim(engine, issuer_id=issuer_id, cutoff=cutoff,
                                     key="revision-check", question="risk factors",
                                     epistemic_status="observed_fact")
            ]
        return revision_report(engine, earlier_document_id=left, later_document_id=right,
                               claims=claims)

    return None


__all__ = ["register_knowledge_routes", "SearchRequest", "ClaimRequest"]
