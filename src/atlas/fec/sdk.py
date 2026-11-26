"""Python SDK for building canonical Atlas models.

The builder emits ``atlas.model.v1`` specifications. Those specifications are identical
in shape to equation-compiled and visual models, so all three authoring paths execute
through the same compiler and runtime.
"""

from __future__ import annotations

from typing import Any

from ..storage.db import Database
from .compiler import compile_model
from .runtime import ExecutionEngine


class ModelBuilder:
    def __init__(self, name: str, *, version: str = "1.0.0", as_of: str | None = None,
                 mode: str = "public_available", evidence_ids: list[str] | None = None,
                 assumptions: list[dict[str, Any]] | None = None):
        self.name = name
        self.version = version
        self.as_of = as_of
        self.mode = mode
        self.evidence_ids = list(evidence_ids or [])
        self.assumptions = list(assumptions or [])
        self.inputs: list[dict[str, Any]] = []
        self.nodes: list[dict[str, Any]] = []
        self.outputs: dict[str, str] = {}

    def input(self, name: str, type_: str, *, default: Any = None,
              required: bool = True) -> "ModelBuilder":
        declaration: dict[str, Any] = {"name": name, "type": type_, "required": required}
        if default is not None:
            declaration["default"] = default
        self.inputs.append(declaration)
        return self

    def constant(self, node_id: str, value: Any, type_: str = "Scalar") -> "ModelBuilder":
        self.nodes.append({"id": node_id, "op": "constant",
                           "params": {"value": str(value), "type": type_}})
        return self

    def node(self, node_id: str, op: str, inputs: list[str] | None = None,
             **params: Any) -> "ModelBuilder":
        self.nodes.append({"id": node_id, "op": op, "inputs": inputs or [], "params": params})
        return self

    def output(self, name: str, node_id: str) -> "ModelBuilder":
        self.outputs[name] = node_id
        return self

    def spec(self) -> dict[str, Any]:
        return {
            "schema_version": "atlas.model.v1",
            "name": self.name,
            "version": self.version,
            "interface": "graph",
            "as_of": self.as_of,
            "mode": self.mode,
            "inputs": self.inputs,
            "nodes": self.nodes,
            "outputs": self.outputs,
            "evidence_ids": self.evidence_ids,
            "assumptions": self.assumptions,
        }

    def compile(self):
        return compile_model(self.spec())

    def run(self, inputs: dict[str, Any] | None = None, *, db: Database | None = None,
            use_cache: bool = True) -> dict[str, Any]:
        return ExecutionEngine(db, use_cache=use_cache).execute(self.compile(), inputs)


def price_times_shares(name: str = "Market capitalisation") -> ModelBuilder:
    return (
        ModelBuilder(name)
        .input("price", "Price[USD]")
        .input("shares", "Shares")
        .node("market_cap", "mul", ["price", "shares"])
        .output("market_cap", "market_cap")
    )
