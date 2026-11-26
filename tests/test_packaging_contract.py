"""Declared-dependency contract for the source tree.

Phase 9.2.4 found a clean-runner defect: the ``database-integrity`` job installed
``.[dev]`` and the ``research-integrity`` job installed ``.[dev,terminal]``, yet both
failed during collection because ``atlas.economic.model`` imports NumPy at module
scope and NumPy was declared only in the optional ``learning`` extra. The tests below
keep optional dependencies optional and make an eagerly imported one a declared,
installable dependency instead of an incidental transitive one.
"""

from __future__ import annotations

import ast
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SOURCE = ROOT / "src" / "atlas"

# distribution name -> the declaration site that must provide it at import time
CORE = "core"
EXTRA = {
    "fastapi": "terminal",
    "uvicorn": "terminal",
    "pyarrow": "columnar",
    "scipy": "learning",
    "sklearn": "learning",
}


def _distribution(name: str) -> str:
    return "scikit-learn" if name == "sklearn" else name


def _declarations() -> tuple[dict[str, str], dict[str, str]]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    core = {
        requirement.split(">")[0].split("<")[0].split("=")[0].strip().lower()
        for requirement in project.get("dependencies", [])
    }
    extras = {
        extra: {
            requirement.split(">")[0].split("<")[0].split("=")[0].strip().lower()
            for requirement in requirements
        }
        for extra, requirements in project.get("optional-dependencies", {}).items()
    }
    return {name: name for name in core}, extras


def _module_scope_imports() -> dict[str, set[str]]:
    """Return ``{distribution: {files}}`` for imports executed on module import."""
    eager: dict[str, set[str]] = {}

    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        depth = 0

        def visit(node: ast.AST, depth: int) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                depth += 1
            if isinstance(node, ast.Import) and depth == 0:
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in EXTRA or _distribution(top) == "numpy":
                        eager.setdefault(_distribution(top), set()).add(path.name)
            elif isinstance(node, ast.ImportFrom) and depth == 0 and node.level == 0 and node.module:
                top = node.module.split(".")[0]
                if top in EXTRA or _distribution(top) == "numpy":
                    eager.setdefault(_distribution(top), set()).add(path.name)
            for child in ast.iter_child_nodes(node):
                visit(child, depth)

        visit(tree, 0)
    return eager


def test_numpy_is_a_core_dependency() -> None:
    core, extras = _declarations()
    assert "numpy" in core, (
        "numpy is imported at module scope by atlas.economic.model; it must be a core "
        "dependency, not part of the optional learning extra"
    )
    assert "numpy" not in extras.get("learning", set()), (
        "numpy is declared twice; the core declaration already satisfies the learning extra"
    )


def test_module_scope_imports_are_declared_where_they_are_needed() -> None:
    core, extras = _declarations()
    undeclared = []
    for distribution, files in sorted(_module_scope_imports().items()):
        if distribution == "numpy":
            if distribution not in core:
                undeclared.append(f"{distribution} (core) imported by {sorted(files)}")
            continue
        extra = EXTRA.get(distribution)
        if extra is None or distribution not in extras.get(extra, set()):
            undeclared.append(f"{distribution} (extra {extra!r}) imported by {sorted(files)}")
    assert not undeclared, (
        "these packages are imported when the module loads but are not declared in the "
        f"installation set that needs them: {undeclared}"
    )


def test_tzdata_is_a_core_dependency() -> None:
    """The Windows install matrix found this the hard way.

    ``atlas.market.calendar`` resolves ``America/New_York`` when it is imported, and Windows
    ships no IANA time zone database, so every packaged command died with
    ``ZoneInfoNotFoundError`` before printing anything. The fix is a declared dependency, not
    a fallback time zone: an exchange calendar with the wrong DST rules mis-dates sessions.
    """
    core, _ = _declarations()
    assert "tzdata" in core, (
        "atlas.market.calendar imports zoneinfo at module scope; tzdata must be a core "
        "dependency or the packaged application cannot start on Windows"
    )
    calendar = (SOURCE / "market" / "calendar.py").read_text(encoding="utf-8")
    assert 'ZoneInfo("America/New_York")' in calendar


def test_optional_extras_do_not_require_the_learning_stack() -> None:
    _, extras = _declarations()
    assert "numpy" not in extras.get("terminal", set())
    assert "scipy" not in extras.get("dev", set())
    assert "scikit-learn" not in extras.get("terminal", set())


# Reference solvers are test-time verification dependencies: the decision tests import
# them lazily and must not skip a cross-check because a working environment forgot one.
REFERENCE_SOLVERS = ("osqp", "clarabel")


def test_reference_solvers_are_declared_in_the_optimization_extra() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    extras = {
        extra: {
            requirement.split(">")[0].split("<")[0].split("=")[0].strip().lower()
            for requirement in requirements
        }
        for extra, requirements in project.get("optional-dependencies", {}).items()
    }
    declared = extras.get("optimization", set())
    for solver in REFERENCE_SOLVERS:
        assert solver in declared, (
            f"{solver} is used by the decision verification tests but is not declared in the "
            "optimization extra"
        )


def test_ci_installs_the_optimization_extra_for_the_backend_suite() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    backend = workflow.split("backend:", 1)[1].split("frontend:", 1)[0]
    assert "optimization" in backend, (
        "the backend CI job runs the full suite, which includes the decision tests; it must "
        "install the optimization extra so the reference solvers are present"
    )
