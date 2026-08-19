import sys
from importlib.metadata import version

__version__ = "0.1.0"


def dependency_versions() -> dict[str, str]:
    """Return a dictionary of reproducibility-relevant dependency versions."""
    deps = {"python": sys.version.split()[0], "thelab": __version__}
    for package in ("pydantic", "pandas", "scikit-learn", "numpy", "joblib"):
        try:
            deps[package] = version(package)
        except Exception:  # pragma: no cover
            deps[package] = "unknown"
    return deps
