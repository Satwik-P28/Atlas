"""Typed intermediate representation and dependency graph."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core.errors import ValidationError
from .types import FinType


@dataclass(slots=True)
class Node:
    id: str
    op: str
    inputs: tuple[str, ...]
    params: dict[str, Any]
    type: FinType | None = None
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "op": self.op,
            "inputs": list(self.inputs),
            "params": self.params,
            "type": self.type.to_dict() if self.type else None,
            "label": self.label,
        }


@dataclass(slots=True)
class CompiledModel:
    name: str
    version: str
    spec: dict[str, Any]
    nodes: dict[str, Node]
    order: list[str]
    outputs: dict[str, str]
    inputs: dict[str, FinType]
    fingerprint: str
    plan: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    compiler_version: str = "atlas.fec.compiler.v1"
    ir_version: str = "atlas.fec.ir.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "ir_version": self.ir_version,
            "compiler_version": self.compiler_version,
            "nodes": [self.nodes[node_id].to_dict() for node_id in self.order],
            "outputs": self.outputs,
            "inputs": {name: type_.to_dict() for name, type_ in self.inputs.items()},
            "plan": self.plan,
            "diagnostics": self.diagnostics,
            "metadata": self.metadata,
            "schema": self.spec.get("schema_version"),
        }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fingerprint(spec: dict[str, Any], compiler_version: str, operators: dict[str, str]) -> str:
    payload = {"spec": spec, "compiler": compiler_version, "operators": operators}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def topological_order(nodes: dict[str, Node], outputs: Iterable[str]) -> list[str]:
    """Deterministic Kahn topological ordering, including every output ancestor."""
    needed: set[str] = set()
    stack = [outputs_id for outputs_id in outputs]
    while stack:
        node_id = stack.pop()
        if node_id in needed:
            continue
        needed.add(node_id)
        stack.extend(nodes[node_id].inputs)
    indegree = {
        node_id: len({dep for dep in nodes[node_id].inputs if dep in needed})
        for node_id in needed
    }
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for other in sorted(needed):
            if node_id in set(nodes[other].inputs):
                indegree[other] -= 1
                if indegree[other] == 0:
                    ready.append(other)
        ready.sort()
    if len(order) != len(needed):
        remaining = sorted(needed - set(order))
        raise ValidationError("model dependency graph contains a cycle", nodes=remaining)
    return order
