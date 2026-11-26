"""Developer SDK for declarative Atlas applications.

The SDK builds on the existing FEC compiler and PackageBuilder; it does not execute
application-provided code. A project is a JSON source file plus optional approved data
files. ``atlas app init/test/build`` exercise the same functions used by tests.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..core.errors import ValidationError
from ..fec import compile_model
from .contracts import (
    APPLICATION_SCHEMA,
    SOURCE_SCHEMA,
    build_package,
    canonical,
    pretty,
    read_package,
    validate_application,
)


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "application"


def _market_cap_model() -> dict[str, Any]:
    return {
        "schema_version": "atlas.model.v1",
        "name": "Market capitalisation",
        "version": "1.0.0",
        "interface": "graph",
        "inputs": [
            {"name": "price", "type": "Price[USD]", "required": True},
            {"name": "shares", "type": "Shares", "required": True},
        ],
        "nodes": [{"id": "market_cap", "op": "mul", "inputs": ["price", "shares"]}],
        "outputs": {"market_cap": "market_cap"},
        "assumptions": ["Price and share count refer to the same security and date."],
    }


class ApplicationBuilder:
    def __init__(self, application_id: str, name: str, *, version: str = "1.0.0",
                 description: str = "A declarative Atlas research application",
                 publisher_id: str = "local.user",
                 publisher_name: str = "Local Atlas user") -> None:
        self.application: dict[str, Any] = {
            "schema": APPLICATION_SCHEMA,
            "application_id": application_id,
            "name": name,
            "version": version,
            "publisher": {"id": publisher_id, "name": publisher_name},
            "description": description,
            "compatibility": {"minimum": "0.3.0", "maximum_exclusive": "0.4.0"},
            "runtime": {"kind": "fec_model", "model_runtime": "atlas.fec.model.v1"},
            "dependencies": {"compiler": "atlas.fec.compiler.v1", "operators": []},
            "inputs": [],
            "outputs": [],
            "views": [{"id": "report", "type": "report", "title": "Research report"}],
            "sources": [],
            "capabilities": ["execute_fec_operator", "render_declarative_ui"],
            "resources": {"max_package_bytes": 8 * 1024 * 1024, "max_memory_mb": 256,
                          "max_execution_seconds": 30},
            "license": "Apache-2.0",
            "limitations": ["Declarative example; no investment claim is made."],
            "created_at": "2026-11-05T00:00:00Z",
        }

    def input(self, key: str, type_: str, *, default: Any = None, unit: str | None = None) -> "ApplicationBuilder":
        item = {"key": key, "type": type_}
        if default is not None:
            item["default"] = default
        if unit:
            item["unit"] = unit
        self.application["inputs"].append(item)
        return self

    def output(self, key: str, *, unit: str | None = None) -> "ApplicationBuilder":
        item = {"key": key}
        if unit:
            item["unit"] = unit
        self.application["outputs"].append(item)
        return self

    def view(self, view_id: str, type_: str, title: str) -> "ApplicationBuilder":
        self.application["views"].append({"id": view_id, "type": type_, "title": title})
        return self

    def model(self, spec: dict[str, Any]) -> "ApplicationBuilder":
        self._model = spec
        return self

    def document(self) -> dict[str, Any]:
        validate_application(self.application)
        return self.application

    def build(self, destination: str | Path, *, model: dict[str, Any] | None = None,
              expected_outputs: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = model or getattr(self, "_model", None)
        if not spec:
            raise ValidationError("a model specification is required")
        compiled = compile_model(spec)
        app = self.document()
        app["dependencies"]["operators"] = [
            {"name": op, "version": compiled.plan[index]["operator_version"]}
            for index, op in enumerate([item["op"] for item in compiled.plan])
            if op in {"mul", "energy_cost_impact", "after_tax_cost_impact", "margin_impact", "neg"}
        ]
        # Deduplicate exact operator versions while keeping a stable order.
        seen: set[tuple[str, str]] = set()
        operators = []
        for item in app["dependencies"]["operators"]:
            key = (item["name"], item["version"])
            if key not in seen:
                seen.add(key)
                operators.append(item)
        app["dependencies"]["operators"] = operators
        validate_application(app)
        files = {
            "artifacts/model.json": pretty(spec),
            "application.json": pretty(app),
        }
        if expected_outputs is not None:
            files["artifacts/expected_outputs.json"] = pretty(expected_outputs)
        file_meta = [
            {"path": "artifacts/model.json", "role": "model_artifact",
             "rights": "public_domain", "source_ids": [], "media_type": "application/json"},
        ]
        if expected_outputs is not None:
            file_meta.append({"path": "artifacts/expected_outputs.json", "role": "validation_vector",
                              "rights": "public_domain", "source_ids": [],
                              "media_type": "application/json"})
        payload = build_package(app, files, file_metadata=file_meta,
                                built_at=app["created_at"], reproducibility="fully_reproducible")
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        loaded = read_package(payload)
        return {
            "schema": "atlas.application.sdk.build.v1",
            "path": str(path),
            "package_id": loaded["manifest"]["package_id"],
            "package_sha256": loaded["package_sha256"],
            "size_bytes": loaded["size_bytes"],
            "application": app,
        }


def scaffold(directory: str | Path, *, name: str, application_id: str | None = None,
             version: str = "1.0.0") -> dict[str, Any]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    app_id = application_id or f"local.{_slug(name)}"
    builder = (
        ApplicationBuilder(app_id, name, version=version,
                           description="A reusable, declarative financial research application.")
        .input("price", "Price[USD]", default=100.0, unit="USD")
        .input("shares", "Shares", default=1_000_000.0)
        .output("market_cap", unit="USD")
        .view("inputs", "table", "Inputs")
        .view("outputs", "report", "Outputs")
        .view("limitations", "limitations", "Limitations")
    )
    model = _market_cap_model()
    source = {
        "schema": SOURCE_SCHEMA,
        "application": builder.application,
        "model": model,
        "expected_outputs": {"market_cap": 100_000_000.0},
        "files": [],
    }
    path = root / "atlas.app.json"
    path.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "README.md").write_text(
        f"# {name}\n\n"
        "A declarative Atlas application scaffold. No executable plugin code is present.\n\n"
        "```bash\n"
        "atlas app validate --file atlas.app.json\n"
        "atlas app test --file atlas.app.json\n"
        "atlas app build --file atlas.app.json --out dist/example.atlas\n"
        "atlas app install --package dist/example.atlas\n"
        "```\n",
        encoding="utf-8",
    )
    return {"path": str(path), "application_id": app_id, "name": name}


def load_source(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SOURCE_SCHEMA:
        raise ValidationError("application source must use atlas.application_source.v1")
    app = validate_application(payload.get("application", {}))
    model = payload.get("model")
    if not isinstance(model, dict):
        raise ValidationError("application source requires a model specification")
    compile_model(model)
    return {"source": payload, "application": app, "model": model, "root": Path(path).parent}


def test_source(path: str | Path) -> dict[str, Any]:
    loaded = load_source(path)
    app = loaded["application"]
    model = compile_model(loaded["model"])
    # Compile-time dependency check is the SDK test; execution belongs to Atlas's runtime.
    return {
        "schema": "atlas.application.sdk.test.v1",
        "status": "valid",
        "application_id": app["application_id"],
        "version": app["version"],
        "model_fingerprint": model.fingerprint,
        "operators": sorted({node.op for node in model.nodes.values()}),
        "executable_plugin_code": False,
    }


def build_source(path: str | Path, destination: str | Path) -> dict[str, Any]:
    loaded = load_source(path)
    payload = loaded["source"]
    app = loaded["application"]
    model = loaded["model"]
    files = {
        "artifacts/model.json": pretty(model),
        "application.json": pretty(app),
    }
    if payload.get("expected_outputs") is not None:
        files["artifacts/expected_outputs.json"] = pretty(payload["expected_outputs"])
    for relative in payload.get("files", []):
        relative_path = str(relative)
        from .contracts import validate_relative_path
        validate_relative_path(relative_path)
        candidate = (loaded["root"] / relative_path).resolve()
        if loaded["root"].resolve() not in candidate.parents or not candidate.is_file():
            raise ValidationError("SDK data file escapes the project directory", path=relative_path)
        files[relative_path] = candidate.read_bytes()
    builder = ApplicationBuilder(app["application_id"], app["name"], version=app["version"])
    builder.application = app
    result = builder.build(destination, model=model, expected_outputs=payload.get("expected_outputs"))
    result["source_files"] = sorted(payload.get("files", []))
    return result


__all__ = ["ApplicationBuilder", "build_source", "load_source", "scaffold", "test_source"]
