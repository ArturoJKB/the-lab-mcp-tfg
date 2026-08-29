"""Model registry: one source of truth for estimators and their defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge, SGDClassifier
from sklearn.svm import SVC

TaskType = Literal["classification", "regression"]


@dataclass(frozen=True)
class ModelEntry:
    """Metadata for a registered model."""

    name: str
    estimator_class: type[Any]
    default_params: dict[str, Any]
    supports_probability: bool = False
    task_type: TaskType = "classification"
    # Rows above which the model is rejected as impractical (e.g. O(n^2)
    # kernel methods). ``None`` means no limit.
    max_train_rows: int | None = None


class ModelRegistry:
    """Maps model names to estimator classes, defaults, and capability flags."""

    def __init__(self) -> None:
        self._entries: dict[str, ModelEntry] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        # Classification models
        self.register(
            ModelEntry(
                name="logistic_regression",
                estimator_class=LogisticRegression,
                default_params={"max_iter": 200, "solver": "lbfgs"},
                supports_probability=True,
                task_type="classification",
            )
        )
        self.register(
            ModelEntry(
                name="random_forest",
                estimator_class=RandomForestClassifier,
                default_params={"n_estimators": 100},
                supports_probability=True,
                task_type="classification",
            )
        )
        self.register(
            ModelEntry(
                name="svc",
                estimator_class=SVC,
                default_params={"kernel": "rbf"},
                supports_probability=True,
                task_type="classification",
                # SVC training is super-linear in samples; reject impractical
                # sizes instead of hanging a run for hours.
                max_train_rows=50_000,
            )
        )
        self.register(
            ModelEntry(
                name="sgd_classifier",
                estimator_class=SGDClassifier,
                default_params={"loss": "log_loss", "max_iter": 1000, "tol": 1e-3},
                supports_probability=True,
                task_type="classification",
            )
        )
        self.register(
            ModelEntry(
                name="hist_gradient_boosting",
                estimator_class=HistGradientBoostingClassifier,
                default_params={},
                supports_probability=True,
                task_type="classification",
            )
        )

        # Regression models
        self.register(
            ModelEntry(
                name="linear_regression",
                estimator_class=LinearRegression,
                default_params={},
                task_type="regression",
            )
        )
        self.register(
            ModelEntry(
                name="ridge",
                estimator_class=Ridge,
                default_params={"alpha": 1.0},
                task_type="regression",
            )
        )
        self.register(
            ModelEntry(
                name="random_forest_regressor",
                estimator_class=RandomForestRegressor,
                default_params={"n_estimators": 100},
                task_type="regression",
            )
        )
        self.register(
            ModelEntry(
                name="hist_gradient_boosting_regressor",
                estimator_class=HistGradientBoostingRegressor,
                default_params={},
                task_type="regression",
            )
        )

    def register(self, entry: ModelEntry) -> None:
        """Register a new model entry."""
        self._entries[entry.name] = entry

    def list_models(self) -> list[str]:
        """Return all registered model names."""
        return sorted(self._entries.keys())

    def get(self, name: str) -> ModelEntry:
        """Return the entry for *name* or raise ValueError.

        Supports a ``*_probability`` suffix for models that can enable
        probability estimates (e.g. ``svc_probability``).
        """
        probability = False
        base_name = name
        if name.endswith("_probability"):
            base_name = name[: -len("_probability")]
            probability = True

        if base_name not in self._entries:
            supported = ", ".join(self.list_models())
            raise ValueError(f"unsupported model '{name}'. Supported models: {supported}")

        entry = self._entries[base_name]
        if probability and not entry.supports_probability:
            raise ValueError(f"model '{base_name}' does not support probability estimates")

        return entry

    def supports_probability(self, name: str) -> bool:
        """Return True if the model can produce probability estimates."""
        return self.get(name).supports_probability

    def build_estimator(
        self,
        name: str,
        seed: int,
        hyperparameters: dict[str, Any] | None = None,
    ) -> Any:
        """Return a configured sklearn estimator instance.

        Probability is enabled when *name* ends with ``_probability`` and the
        base model supports it. Optional *hyperparameters* override defaults.
        """
        probability = False
        base_name = name
        if name.endswith("_probability"):
            base_name = name[: -len("_probability")]
            probability = True

        entry = self.get(base_name)
        params = dict(entry.default_params)
        if hyperparameters:
            params.update(hyperparameters)
        if "random_state" in entry.estimator_class._get_param_names():
            params["random_state"] = seed
        if probability and entry.supports_probability:
            if "probability" in entry.estimator_class._get_param_names():
                params["probability"] = True
        return entry.estimator_class(**params)


# Global registry used by the runner, CLI, and MCP servers.
MODEL_REGISTRY = ModelRegistry()
