"""Allowlisted equation parser.

Expressions are parsed with Python's AST, then translated node-by-node. Nothing is passed
to ``eval``/``exec``, and only arithmetic, numeric literals, declared names and a small
operator whitelist are accepted. The output is the same IR used by visual graphs and the
Python SDK.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from typing import Any

from ..core.errors import ValidationError

BINARY = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div", ast.Pow: "pow"}
UNARY = {ast.USub: "neg", ast.UAdd: None}
FUNCTIONS = {
    "abs": ("abs", 1),
    "min": ("min", 2),
    "max": ("max", 2),
    "sum": ("sum", 1),
    "mean": ("mean", 1),
    "growth": ("growth", 1),
    "npv": ("npv", 2),
}
_FORBIDDEN = (
    ast.Attribute, ast.Subscript, ast.Lambda, ast.Call.__class__, ast.ListComp,
    ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.NamedExpr, ast.Await, ast.Yield,
)


def _reject(node: ast.AST) -> None:
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise ValidationError(
                "model functions are allowlisted", function=getattr(node.func, "id", None),
                supported=sorted(FUNCTIONS),
            )
        if node.keywords:
            raise ValidationError("keyword arguments are not supported in equations")
        return
    if isinstance(node, (ast.Attribute, ast.Subscript, ast.Lambda, ast.ListComp, ast.DictComp,
                         ast.SetComp, ast.GeneratorExp, ast.NamedExpr, ast.Await, ast.Yield,
                         ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
        raise ValidationError(
            "this expression is not allowed in a financial model", node=type(node).__name__
        )


class EquationParser:
    def __init__(self, declared: set[str]):
        self.declared = set(declared)
        self.nodes: list[dict[str, Any]] = []
        self.counter = 0

    def _node(self, op: str, inputs: list[str], params: dict[str, Any] | None = None,
              label: str | None = None) -> str:
        node_id = f"e{self.counter}"
        self.counter += 1
        self.nodes.append({"id": node_id, "op": op, "inputs": inputs,
                           "params": params or {}, "label": label})
        return node_id

    def expression(self, tree: ast.AST) -> str:
        if isinstance(tree, ast.Expression):
            return self.expression(tree.body)
        _reject(tree)
        if isinstance(tree, ast.Constant):
            if isinstance(tree.value, bool) or not isinstance(tree.value, (int, float)):
                raise ValidationError("only numeric constants are allowed in equations")
            return self._node("constant", [], {"value": str(Decimal(str(tree.value))), "type": "Scalar"})
        if isinstance(tree, ast.Name):
            if tree.id not in self.declared:
                raise ValidationError("undefined model input", name=tree.id,
                                      hint="declare it under inputs or in an earlier equation")
            return tree.id
        if isinstance(tree, ast.BinOp):
            op = BINARY.get(type(tree.op))
            if op is None:
                raise ValidationError("unsupported binary operator", operator=type(tree.op).__name__)
            return self._node(op, [self.expression(tree.left), self.expression(tree.right)])
        if isinstance(tree, ast.UnaryOp):
            op = UNARY.get(type(tree.op))
            value = self.expression(tree.operand)
            return value if op is None else self._node(op, [value])
        if isinstance(tree, ast.Call):
            _reject(tree)
            name = tree.func.id
            op, arity = FUNCTIONS[name]
            if len(tree.args) != arity:
                raise ValidationError(f"{name} expects {arity} argument(s)", function=name,
                                      received=len(tree.args))
            return self._node(op, [self.expression(arg) for arg in tree.args])
        raise ValidationError("unsupported equation expression", node=type(tree).__name__)


def parse_equations(equations: list[dict[str, str]], inputs: list[str],
                    outputs: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    declared = set(inputs)
    parser = EquationParser(declared)
    mapping: dict[str, str] = {}
    for equation in equations:
        name = str(equation.get("name", "")).strip()
        expression = equation.get("expr")
        if not name or not isinstance(expression, str):
            raise ValidationError("each equation needs a name and expression")
        if name in declared or name in mapping:
            raise ValidationError("duplicate equation name", name=name)
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ValidationError("equation syntax error", name=name, detail=str(exc),
                                  line=exc.lineno) from exc
        node_id = parser.expression(tree)
        mapping[name] = node_id
        declared.add(name)
    names = outputs or list(mapping)
    missing = [name for name in names if name not in mapping and name not in inputs]
    if missing:
        raise ValidationError("unknown model output", outputs=missing)
    resolved = {name: mapping.get(name, name) for name in names}
    return parser.nodes, resolved
