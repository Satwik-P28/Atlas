"""HTTP surface for the cross-company comparison workspace.

The route resolves each company's figure through the same registered concept resolver the
single-answer surface uses, so a comparison cell carries the same evidence identity as an
answer certificate. Incompatibilities come back as findings with the cells that produced
them; a blocking finding is reported, never repaired by scaling or by picking another period.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

from fastapi import Depends
from pydantic import BaseModel, Field

from ..research.comparison import CompanyComparisonService


class ComparisonRequest(BaseModel):
    issuers: list[str] = Field(min_length=2, max_length=6)
    concepts: list[str] = Field(min_length=1, max_length=8)
    period: str = Field(min_length=4, max_length=20)
    as_of: str | None = Field(default=None, max_length=40)
    scope: Literal["consolidated", "any"] = "consolidated"


def register_comparison_routes(app: Any, get_db: Callable[..., Any]) -> None:
    @app.post("/api/research/comparison", tags=["research"])
    def research_comparison(body: ComparisonRequest,
                            db: Any = Depends(get_db)) -> dict[str, Any]:
        # A comparison that cannot be made is a domain refusal; the application error handler
        # already turns that into 422 with the reason and the supported concept list.
        return CompanyComparisonService(db).compare(
            body.issuers, concepts=body.concepts, period=body.period,
            cutoff=body.as_of, scope=body.scope,
        )
