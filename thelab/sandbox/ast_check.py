"""AST visitor that enforces the sandbox policy before execution."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .policy import SandboxPolicy


class SandboxAstError(ValueError):
    """Raised when the AST violates the sandbox policy."""


@dataclass(frozen=True)
class AstCheckResult:
    """Result of an AST policy check."""

    ok: bool
    reason: str | None = None


class AstChecker(ast.NodeVisitor):
    """Reject AST constructs that are unsafe for the sandbox."""

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()
        self.errors: list[str] = []

    def check(self, tree: ast.AST) -> AstCheckResult:
        self.errors = []
        self.visit(tree)
        if self.errors:
            return AstCheckResult(ok=False, reason="; ".join(self.errors))
        return AstCheckResult(ok=True)

    def generic_visit(self, node: ast.AST) -> None:
        if type(node) in self.policy.blocked_ast_nodes:
            self.errors.append(f"blocked syntax: {type(node).__name__}")
            return
        super().generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            if not self.policy.is_import_allowed(alias.name):
                self.errors.append(f"import not allowed: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        if not self.policy.is_import_allowed(module):
            self.errors.append(f"import not allowed: {module}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id in self.policy.blocked_names:
            self.errors.append(f"blocked name: {node.id}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Block type(...) calls that could create dynamic classes.
        if isinstance(node.func, ast.Name) and node.func.id == "type" and node.args:
            self.errors.append("dynamic type() classes are not allowed")
        # Block direct calls to blocked builtins by name.
        if isinstance(node.func, ast.Name) and node.func.id in self.policy.blocked_builtins:
            self.errors.append(f"blocked builtin call: {node.func.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        # Block dunder attribute access that could escape the sandbox.
        if node.attr.startswith("__") and node.attr.endswith("__"):
            if node.attr not in {"__name__", "__doc__", "__file__"}:
                self.errors.append(f"blocked dunder access: {node.attr}")
        self.generic_visit(node)


def check_code(code: str, policy: SandboxPolicy | None = None) -> AstCheckResult:
    """Parse *code* and return an AST policy check result."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return AstCheckResult(ok=False, reason=f"syntax error: {exc}")
    return AstChecker(policy).check(tree)
