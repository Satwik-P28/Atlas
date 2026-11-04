"""Financial-Economic Compiler (FEC).

The compiler turns a declarative model into a typed dependency graph, validates financial
semantics, and executes an ordered plan. It never evaluates user Python or SQL.
"""

from .compiler import COMPILER_VERSION, CompileError, compile_model
from .runtime import ExecutionEngine
from .types import FinType, TypeMismatch

__all__ = [
    "COMPILER_VERSION",
    "CompileError",
    "ExecutionEngine",
    "FinType",
    "TypeMismatch",
    "compile_model",
]
