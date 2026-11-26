"""Deterministic dependency-aware execution runtime.

The runtime executes only a compiled, typed plan. Results are cached per node under a
key covering the compiled fingerprint, operator version, node parameters and canonical
input values. Historical cutoffs are part of the model definition and input snapshot,
never ambient process state.
"""

from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal, localcontext
from typing import Any, Callable

from ..core.errors import ValidationError
from ..core.temporal import iso, utcnow
from ..storage.db import Database
from .ir import CompiledModel, canonical_json
from .operators import DECIMAL_PRECISION, REGISTRY, operator_versions


def encode_value(value: Any) -> dict[str, Any]:
    if isinstance(value, (list, tuple)):
        return {"kind": "series", "values": [str(item) for item in value]}
    return {"kind": "decimal", "value": str(value)}


def decode_value(payload: dict[str, Any]) -> Any:
    if payload.get("kind") == "series":
        return tuple(Decimal(str(item)) for item in payload["values"])
    return Decimal(str(payload["value"]))


def json_number(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    return float(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(encode_value(value)).encode("utf-8")).hexdigest()[:16]


class ExecutionEngine:
    def __init__(
        self,
        db: Database | None = None,
        *,
        use_cache: bool = True,
        timeout_seconds: float = 10.0,
        max_operations: int = 5000,
    ):
        self.db = db
        self.use_cache = use_cache
        self.timeout_seconds = timeout_seconds
        self.max_operations = max_operations
        self._memory: dict[str, Any] = {}

    def _coerce_input(self, name: str, type_: Any, value: Any) -> Any:
        if type_.kind == "series" or type_.kind == "forecast":
            if not isinstance(value, (list, tuple)):
                raise ValidationError("series input must be a list", input=name, type=type_.label())
            result = []
            for item in value:
                if isinstance(item, bool):
                    raise ValidationError("boolean is not a financial number", input=name)
                try:
                    number = Decimal(str(item))
                except Exception as exc:  # noqa: BLE001
                    raise ValidationError("input is not numeric", input=name, value=item) from exc
                if not number.is_finite():
                    raise ValidationError("input is not finite", input=name)
                result.append(number)
            return tuple(result)
        if isinstance(value, bool):
            raise ValidationError("boolean is not a financial number", input=name)
        try:
            number = Decimal(str(value))
        except Exception as exc:  # noqa: BLE001
            raise ValidationError("input is not numeric", input=name, value=value) from exc
        if not number.is_finite():
            raise ValidationError("input is not finite", input=name)
        return number

    def _cache_key(self, model: CompiledModel, node_id: str, args: list[Any]) -> str:
        node = model.nodes[node_id]
        payload = {
            "fingerprint": model.fingerprint,
            "node": node_id,
            "op": node.op,
            "operator_version": REGISTRY[node.op].version,
            "params": node.params,
            "inputs": [encode_value(value) for value in args],
            "precision": DECIMAL_PRECISION,
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def _lookup(self, key: str) -> Any | None:
        if not self.use_cache:
            return None
        if key in self._memory:
            return self._memory[key]
        if self.db is not None:
            row = self.db.query_one(
                "SELECT value_json FROM model_node_cache WHERE cache_key = ?", (key,)
            )
            if row:
                try:
                    value = decode_value(json.loads(row["value_json"]))
                except (ValueError, KeyError, TypeError):
                    return None
                self._memory[key] = value
                self.db.execute(
                    "UPDATE model_node_cache SET hits = hits + 1, last_hit_at = ? WHERE cache_key = ?",
                    (iso(utcnow()), key),
                )
                return value
        return None

    def _store(self, key: str, model: CompiledModel, node_id: str, value: Any) -> None:
        if not self.use_cache:
            return
        self._memory[key] = value
        if self.db is not None:
            node = model.nodes[node_id]
            now = iso(utcnow())
            self.db.execute(
                "INSERT INTO model_node_cache (cache_key, fingerprint, node_id, operator_key, "
                "operator_version, value_json, created_at, last_hit_at, hits) "
                "VALUES (?,?,?,?,?,?,?,?,0) ON CONFLICT(cache_key) DO UPDATE SET "
                "value_json = excluded.value_json",
                (key, model.fingerprint, node_id, node.op, REGISTRY[node.op].version,
                 canonical_json(encode_value(value)), now, now),
            )

    def execute(
        self,
        model: CompiledModel,
        inputs: dict[str, Any] | None = None,
        *,
        persist: bool = True,
        run_id: str | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        if len(model.order) > self.max_operations:
            raise ValidationError("model exceeds operation limit", limit=self.max_operations,
                                  operations=len(model.order))
        provided = dict(inputs or {})
        snapshot: dict[str, Any] = {}
        declarations = {item["name"]: item for item in model.spec.get("inputs", [])}
        for name, type_ in model.inputs.items():
            if name in provided:
                snapshot[name] = self._coerce_input(name, type_, provided[name])
                continue
            default = declarations.get(name, {}).get("default")
            if default is not None:
                snapshot[name] = self._coerce_input(name, type_, default)
                continue
            if declarations.get(name, {}).get("required", True):
                raise ValidationError("required model input is missing", input=name,
                                      type=type_.label())
            snapshot[name] = tuple() if type_.kind == "series" else Decimal(0)
        unknown = sorted(set(provided) - set(model.inputs))
        if unknown:
            raise ValidationError("unknown model inputs", inputs=unknown,
                                  declared=sorted(model.inputs))

        started = time.perf_counter()
        values: dict[str, Any] = {}
        trace: list[dict[str, Any]] = []
        hits = 0
        misses = 0
        with localcontext() as ctx:
            ctx.prec = DECIMAL_PRECISION
            for position, node_id in enumerate(model.order):
                if cancel is not None and cancel():
                    raise ValidationError("model execution cancelled", node=node_id)
                if time.perf_counter() - started > self.timeout_seconds:
                    raise ValidationError("model execution exceeded its time limit",
                                          limit_seconds=self.timeout_seconds, node=node_id)
                node = model.nodes[node_id]
                args = [values[dependency] for dependency in node.inputs]
                node_started = time.perf_counter()
                if node.op == "input":
                    name = str(node.params.get("name", node.id))
                    value = snapshot[name]
                    status = "input"
                    key = None
                elif node.op == "constant":
                    value = Decimal(str(node.params.get("value", 0)))
                    status = "computed"
                    key = None
                else:
                    operator = REGISTRY[node.op]
                    key = self._cache_key(model, node_id, args)
                    cached = self._lookup(key)
                    if cached is not None:
                        value = cached
                        status = "cached"
                        hits += 1
                    else:
                        try:
                            value = operator.execute(args, node.params)
                        except (ArithmeticError, ValueError, TypeError, OverflowError) as exc:
                            raise ValidationError(
                                "model node failed", node=node_id, operator=node.op,
                                detail=str(exc), formula=operator.formula,
                            ) from exc
                        if isinstance(value, Decimal) and not value.is_finite():
                            raise ValidationError("non-finite result", node=node_id)
                        if isinstance(value, (list, tuple)) and any(
                            not item.is_finite() for item in value
                        ):
                            raise ValidationError("non-finite result", node=node_id)
                        self._store(key, model, node_id, value)
                        status = "computed"
                        misses += 1
                values[node_id] = value
                trace.append({
                    "position": position,
                    "node": node_id,
                    "op": node.op,
                    "type": node.type.label() if node.type else None,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - node_started) * 1000, 4),
                    "value_digest": _digest(value),
                })

        elapsed = (time.perf_counter() - started) * 1000
        outputs = {name: json_number(values[node_id]) for name, node_id in model.outputs.items()}
        exact_outputs = {name: encode_value(values[node_id]) for name, node_id in model.outputs.items()}
        if run_id is None:
            identity = canonical_json({
                "fingerprint": model.fingerprint,
                "inputs": {name: encode_value(value) for name, value in sorted(snapshot.items())},
                "as_of": model.metadata.get("as_of"),
                "mode": model.metadata.get("mode"),
            })
            run_id = "RUN-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        manifest = {
            "run_id": run_id,
            "fingerprint": model.fingerprint,
            "model": model.name,
            "model_version": model.version,
            "compiler_version": model.compiler_version,
            "ir_version": model.ir_version,
            "operator_versions": operator_versions(),
            "as_of": model.metadata.get("as_of"),
            "mode": model.metadata.get("mode"),
            "inputs_sha256": hashlib.sha256(
                canonical_json({k: encode_value(v) for k, v in sorted(snapshot.items())}).encode()
            ).hexdigest(),
            "inputs": {name: encode_value(value) for name, value in sorted(snapshot.items())},
            "evidence_ids": model.metadata.get("evidence_ids", []),
            "assumptions": model.metadata.get("assumptions", []),
            "node_count": len(model.order),
            "cache_hits": hits,
            "cache_misses": misses,
            "duration_ms": round(elapsed, 3),
            "created_at": iso(utcnow()),
        }
        result = {
            "run_id": run_id,
            "model": model.name,
            "version": model.version,
            "fingerprint": model.fingerprint,
            "outputs": outputs,
            "exact_outputs": exact_outputs,
            "trace": trace,
            "manifest": manifest,
            "status": "succeeded",
        }
        if persist and self.db is not None:
            self.db.execute(
                "INSERT INTO model_run (run_id, model_name, model_version, fingerprint, as_of, mode, "
                "inputs_json, result_json, trace_json, status, duration_ms, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO NOTHING",
                (run_id, model.name, model.version, model.fingerprint, manifest["as_of"],
                 manifest["mode"], canonical_json(manifest["inputs"]), canonical_json(result),
                 canonical_json(trace), "succeeded", elapsed, manifest["created_at"]),
            )
        return result
