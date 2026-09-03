"""Sandbox execution policy: allowed imports, blocked AST nodes, and builtins."""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxPolicy:
    """Static policy for the restricted subprocess sandbox."""

    # Packages/modules that may be imported inside the sandbox. Submodules are
    # allowed if the parent package is in the whitelist (e.g. numpy.linalg).
    import_whitelist: frozenset[str] = frozenset({
        # Data / ML
        "numpy",
        "pandas",
        "sklearn",
        # Plotting
        "matplotlib",
        "matplotlib.pyplot",
        "seaborn",
        # Project EDA
        "thelab.eda",
        # Safe stdlib. ``inspect`` is deliberately excluded: it exposes
        # ``currentframe()`` whose ``f_builtins`` recovers the unfiltered
        # builtins dict, defeating the builtins filter.
        "collections",
        "csv",
        "datetime",
        "functools",
        "io",
        "itertools",
        "json",
        "math",
        "operator",
        "pathlib",
        "random",
        "re",
        "statistics",
        "string",
        "typing",
    })

    # Builtins that are removed from the child globals.
    blocked_builtins: frozenset[str] = frozenset({
        "open",
        "eval",
        "exec",
        "compile",
        "breakpoint",
        "input",
        "quit",
        "exit",
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "locals",
        "globals",
        "__import__",
    })

    # AST node types that are rejected outright.
    # NOTE: ast.Lambda is deliberately ALLOWED — groupby().transform(lambda ...),
    # df.apply(lambda ...) and df.assign(lambda ...) are core pandas idioms that
    # the FeatureEngineer sub-agent must use. Lambdas cannot import, access
    # blocked builtins, or escape scope (no global/nonlocal — separately blocked).
    blocked_ast_nodes: frozenset[type[ast.AST]] = frozenset({
        ast.AsyncFor,
        ast.AsyncFunctionDef,
        ast.AsyncWith,
        ast.Await,
        ast.ClassDef,
        ast.Delete,
        ast.Global,
        ast.Match,
        ast.NamedExpr,
        ast.Nonlocal,
        ast.TryStar,
        ast.Yield,
        ast.YieldFrom,
    })

    # Names that may not appear in Name nodes (loads or stores).
    blocked_names: frozenset[str] = frozenset({
        "__import__",
        "__builtins__",
        "__class__",
        "__subclasses__",
        "__globals__",
        "__code__",
    })

    # File extensions that may be copied out as artifacts.
    artifact_extensions: frozenset[str] = frozenset({
        ".csv",
        ".json",
        ".md",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
        ".txt",
    })

    def is_import_allowed(self, module: str) -> bool:
        """Return True if *module* or one of its parents is whitelisted."""
        parts = module.split(".")
        for i in range(len(parts), 0, -1):
            if ".".join(parts[:i]) in self.import_whitelist:
                return True
        return False

    def is_artifact_extension_allowed(self, ext: str) -> bool:
        return ext.lower() in self.artifact_extensions


DEFAULT_POLICY = SandboxPolicy()
