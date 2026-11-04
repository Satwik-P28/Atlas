"""Staged financial model compiler.

parse -> validate -> typed IR -> dependency analysis -> execution plan. Compilation is
pure and deterministic; execution is performed by :mod:`atlas.fec.runtime`.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.errors import ValidationError
from .ir import CompiledModel, Node, canonical_json, fingerprint, topological_order
from .operators import REGISTRY, operator_versions
from .parser import parse_equations
from .types import FinType, TypeMismatch

SPEC_VERSION = "atlas.model.v1"
COMPILER_VERSION = "atlas.fec.compiler.v1"
_MAX_NODES = 2000
_NODE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,95}$")


class CompileError(ValidationError):
    def __init__(self, message: str, diagnostics: list[dict[str, Any]]):
        self.diagnostics = diagnostics
        super().__init__(message, diagnostics=diagnostics)


def _diagnostic(code: str, message: str, *, node: str | None = None, hint: str | None = None,
                **context: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    if node:
        item["node"] = node
    if hint:
        item["hint"] = hint
    item.update(context)
    return item


def _normalise_inputs(raw: Any) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        items = []
        for name, value in raw.items():
            if isinstance(value, str):
                items.append({"name": name, "type": value})
            elif isinstance(value, dict):
                items.append({"name": name, **value})
            else:
                raise ValidationError("input declarations must be strings or objects", input=name)
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValidationError("inputs must be a list or object")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            raise ValidationError("each input needs a name")
        name = str(item["name"])
        if name in result:
            raise ValidationError("duplicate input name", name=name)
        result[name] = dict(item)
    return result


def _normalise_outputs(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        outputs = {str(name): str(node) for name, node in raw.items()}
    elif isinstance(raw, list):
        outputs = {str(name): str(name) for name in raw}
    elif raw is None:
        outputs = {}
    else:
        raise ValidationError("outputs must be a list or object")
    if not outputs:
        raise ValidationError("a model needs at least one output")
    return outputs


def _normalise_nodes(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValidationError("graph interface requires a nodes list")
    nodes = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("each graph node must be an object")
        node_id = str(item.get("id", "")).strip()
        if not _NODE_ID.match(node_id):
            raise ValidationError("invalid node id", node=node_id or None)
        op = str(item.get("op", "")).strip()
        inputs = item.get("inputs", [])
        if not isinstance(inputs, list) or not all(isinstance(value, str) for value in inputs):
            raise ValidationError("node inputs must be a list of node ids", node=node_id)
        params = item.get("params", {})
        if not isinstance(params, dict):
            raise ValidationError("node params must be an object", node=node_id)
        nodes.append({"id": node_id, "op": op, "inputs": inputs, "params": params,
                      "label": item.get("label")})
    if len(nodes) > _MAX_NODES:
        raise ValidationError("model exceeds node limit", limit=_MAX_NODES, received=len(nodes))
    return nodes


def compile_model(spec: dict[str, Any]) -> CompiledModel:
    if not isinstance(spec, dict):
        raise ValidationError("model specification must be an object")
    if spec.get("schema_version", SPEC_VERSION) != SPEC_VERSION:
        raise ValidationError("unsupported model schema", expected=SPEC_VERSION,
                              received=spec.get("schema_version"))
    name = str(spec.get("name", "").strip())
    if not name:
        raise ValidationError("model name is required")
    version = str(spec.get("version", "1.0.0"))
    interface = str(spec.get("interface", "graph"))
    if interface not in {"graph", "equation"}:
        raise ValidationError("unsupported authoring interface", interface=interface)

    diagnostics: list[dict[str, Any]] = []
    try:
        input_defs = _normalise_inputs(spec.get("inputs"))
        outputs = _normalise_outputs(spec.get("outputs"))
        if interface == "equation":
            raw_nodes, outputs = parse_equations(
                spec.get("equations") or [], list(input_defs), list(outputs)
            )
        else:
            raw_nodes = _normalise_nodes(spec.get("nodes"))
    except ValidationError as exc:
        diagnostics.append(_diagnostic(exc.code or "invalid_model", str(exc), **exc.context))
        raise CompileError("model validation failed", diagnostics) from exc

    node_map: dict[str, Node] = {}
    for item in raw_nodes:
        if item["id"] in node_map:
            diagnostics.append(_diagnostic("duplicate_node", "duplicate node id", node=item["id"]))
            continue
        node_map[item["id"]] = Node(
            id=item["id"], op=item["op"], inputs=tuple(item["inputs"]),
            params=item["params"], label=item.get("label"),
        )

    input_types: dict[str, FinType] = {}
    for input_name, declaration in input_defs.items():
        try:
            input_types[input_name] = FinType.from_dict(declaration.get("type", "Scalar"))
        except TypeMismatch as exc:
            diagnostics.append(_diagnostic(exc.code, str(exc), node=input_name))
            continue
        if input_name not in node_map:
            if input_name in node_map:
                diagnostics.append(_diagnostic("duplicate_node", "input collides with node", node=input_name))
            node_map[input_name] = Node(
                id=input_name, op="input", inputs=(), params={"name": input_name},
                type=input_types[input_name], label=declaration.get("label") or input_name,
            )

    if diagnostics:
        raise CompileError("model validation failed", diagnostics)

    for node in node_map.values():
        if node.op == "input":
            input_name = str(node.params.get("name", node.id))
            if input_name not in input_types:
                diagnostics.append(_diagnostic("unknown_input", "input node is not declared",
                                               node=node.id, input=input_name))
            else:
                node.type = input_types[input_name]
        elif node.op == "constant":
            try:
                node.type = FinType.from_dict(node.params.get("type", "Scalar"))
            except TypeMismatch as exc:
                diagnostics.append(_diagnostic(exc.code, str(exc), node=node.id))
        elif node.op not in REGISTRY:
            diagnostics.append(_diagnostic(
                "unsupported_operator", f"operator {node.op!r} is not registered",
                node=node.id, supported=sorted(REGISTRY),
            ))
        for dependency in node.inputs:
            if dependency not in node_map:
                diagnostics.append(_diagnostic("missing_dependency", "dependency is undefined",
                                               node=node.id, dependency=dependency))

    output_ids = list(outputs.values())
    for output_name, node_id in outputs.items():
        if node_id not in node_map:
            diagnostics.append(_diagnostic("unknown_output", "output references an undefined node",
                                           node=node_id, output=output_name))
    if diagnostics:
        raise CompileError("model validation failed", diagnostics)

    try:
        order = topological_order(node_map, output_ids)
    except ValidationError as exc:
        diagnostics.append(_diagnostic("cycle", str(exc), **exc.context))
        raise CompileError("dependency analysis failed", diagnostics) from exc

    for node_id in order:
        node = node_map[node_id]
        if node.type is not None:
            continue
        dependencies = [node_map[dep].type for dep in node.inputs]
        if any(dep is None for dep in dependencies):
            diagnostics.append(_diagnostic("untyped_dependency", "dependency could not be typed",
                                           node=node.id))
            continue
        operator = REGISTRY[node.op]
        if len(dependencies) != operator.arity:
            diagnostics.append(_diagnostic(
                "arity_mismatch", f"{node.op} expects {operator.arity} inputs",
                node=node.id, received=len(dependencies),
            ))
            continue
        try:
            node.type = operator.infer(dependencies, node.params)  # type: ignore[arg-type]
        except TypeMismatch as exc:
            item = _diagnostic(exc.code, str(exc), node=node.id, operator=node.op, **exc.context)
            diagnostics.append(item)
        except (ValueError, TypeError) as exc:
            diagnostics.append(_diagnostic("invalid_operator", str(exc), node=node.id,
                                           operator=node.op))
    if diagnostics:
        raise CompileError("financial type analysis failed", diagnostics)

    # Node dependency check after type assignment ensures every plan entry is executable.
    plan = []
    for position, node_id in enumerate(order):
        node = node_map[node_id]
        plan.append({
            "position": position, "id": node_id, "op": node.op,
            "inputs": list(node.inputs), "type": node.type.to_dict() if node.type else None,
            "operator_version": REGISTRY[node.op].version if node.op in REGISTRY else None,
        })

    normalised = {
        "schema_version": SPEC_VERSION,
        "name": name,
        "version": version,
        "interface": interface,
        "inputs": [
            {"name": key, **{k: v for k, v in input_defs[key].items() if k != "name"},
             "type": input_types[key].to_dict()}
            for key in sorted(input_defs)
        ],
        "nodes": [node_map[node_id].to_dict() for node_id in sorted(node_map)],
        "outputs": dict(sorted(outputs.items())),
        "assumptions": spec.get("assumptions", []),
        "evidence_ids": spec.get("evidence_ids", []),
        "as_of": spec.get("as_of"),
        "mode": spec.get("mode"),
        "metadata": spec.get("metadata", {}),
    }
    model_fingerprint = fingerprint(normalised, COMPILER_VERSION, operator_versions())
    return CompiledModel(
        name=name, version=version, spec=normalised, nodes=node_map, order=order,
        outputs=outputs, inputs=input_types, fingerprint=model_fingerprint, plan=plan,
        metadata={
            "as_of": spec.get("as_of"),
            "mode": spec.get("mode"),
            "assumptions": spec.get("assumptions", []),
            "evidence_ids": spec.get("evidence_ids", []),
            **dict(spec.get("metadata") or {}),
        },
    )


def explain(model: CompiledModel) -> dict[str, Any]:
    return {
        "name": model.name,
        "version": model.version,
        "fingerprint": model.fingerprint,
        "canonical_spec": canonical_json(model.spec),
        "plan": model.plan,
        "outputs": model.outputs,
        "operators": sorted({node.op for node in model.nodes.values() if node.op in REGISTRY}),
    }
