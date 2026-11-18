"""Experiment identity: manifests, dataset hashes and an append-only trial ledger.

A research result that cannot be tied to the exact inputs, code path, parameters and seeds is
an anecdote. This module supplies the minimum machinery to make the decision experiments
auditable:

* ``dataset_digest`` over the exact numeric arrays used, not over a file path;
* ``RunManifest`` capturing the split boundaries, seeds, estimator, solver configuration and
  software versions;
* ``TrialLedger``, an append-only JSONL record that includes failed and abandoned arms.

The ledger's contract is that entries are never edited or deleted. A negative result recorded
there is a result, and the report's multiple-testing disclosure is computed from the ledger
rather than from a hand-written count.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from ..core.errors import ValidationError

MANIFEST_SCHEMA = "atlas.decision.run_manifest.v1"
LEDGER_SCHEMA = "atlas.decision.trial_ledger.v1"


def array_digest(*arrays: Sequence[Sequence[float]] | Sequence[float]) -> str:
    """Order-sensitive SHA-256 over the exact float64 bytes of the supplied arrays."""

    digest = hashlib.sha256()
    for array in arrays:
        values = np.ascontiguousarray(np.asarray(array, dtype="<f8"))
        digest.update(str(values.shape).encode("ascii"))
        digest.update(values.tobytes())
    return digest.hexdigest()


def environment_fingerprint() -> dict[str, Any]:
    import scipy

    fingerprint: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }
    try:
        fingerprint["commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False, timeout=5
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environment dependent
        fingerprint["commit"] = None
    return fingerprint


@dataclass(frozen=True, slots=True)
class RunManifest:
    experiment_id: str
    hypothesis: str
    arm: str
    seed: int
    dataset_digest: str
    parameters: dict[str, Any] = field(default_factory=dict)
    splits: dict[str, Any] = field(default_factory=dict)
    estimator: str = ""
    solver: str = ""
    created_at: str = ""
    environment: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValidationError("a manifest needs an experiment_id")
        if not self.hypothesis:
            raise ValidationError("a manifest must state the hypothesis it tests")

    def with_environment(self) -> "RunManifest":
        return RunManifest(
            experiment_id=self.experiment_id,
            hypothesis=self.hypothesis,
            arm=self.arm,
            seed=self.seed,
            dataset_digest=self.dataset_digest,
            parameters=self.parameters,
            splits=self.splits,
            estimator=self.estimator,
            solver=self.solver,
            created_at=self.created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            environment=self.environment or environment_fingerprint(),
            notes=self.notes,
        )

    def digest(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "experiment_id": self.experiment_id,
            "hypothesis": self.hypothesis,
            "arm": self.arm,
            "seed": self.seed,
            "dataset_digest": self.dataset_digest,
            "parameters": dict(self.parameters),
            "splits": dict(self.splits),
            "estimator": self.estimator,
            "solver": self.solver,
            "created_at": self.created_at,
            "environment": dict(self.environment),
            "notes": list(self.notes),
        }


class TrialLedger:
    """Append-only JSONL ledger of every arm that was run, including the failures."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        if "arm" not in entry or "hypothesis" not in entry:
            raise ValidationError("a ledger entry must name its arm and hypothesis")
        record = {"schema": LEDGER_SCHEMA, "seq": len(self.read()) + 1, **entry}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def summary(self) -> dict[str, Any]:
        entries = self.read()
        arms: dict[str, int] = {}
        for entry in entries:
            arms[entry.get("arm", "unknown")] = arms.get(entry.get("arm", "unknown"), 0) + 1
        return {
            "schema": LEDGER_SCHEMA,
            "entries": len(entries),
            "arms": arms,
            "hypotheses": sorted({entry.get("hypothesis", "") for entry in entries}),
            "failures": sum(1 for entry in entries if entry.get("outcome") == "failed"),
        }


def write_json(path: str | os.PathLike[str], payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=float), encoding="utf-8")
    return target


def deduplicate_arms(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated runs of the same arm, keeping the last recorded one."""

    seen: dict[str, dict[str, Any]] = {}
    for entry in entries:
        seen[str(entry.get("arm", ""))] = entry
    return list(seen.values())


__all__ = [
    "LEDGER_SCHEMA",
    "MANIFEST_SCHEMA",
    "RunManifest",
    "TrialLedger",
    "array_digest",
    "deduplicate_arms",
    "environment_fingerprint",
    "write_json",
]
