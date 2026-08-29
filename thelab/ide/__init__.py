"""Interactive IDE backend for The Lab model service."""

from .cleaning import clean_dataset
from .datasets import (
    DatasetNotFoundError,
    UploadError,
    get_fixtures_root,
    get_uploads_root,
    list_datasets,
    resolve_dataset_path,
    save_upload,
)
from .eda_api import EdaError, run_eda
from .experiment import Experiment, ExperimentState, ExperimentStore
from .experiment_api import (
    add_experiment_feedback,
    get_experiment_results,
    get_experiment_status,
    list_experiments,
    start_experiment,
)
from .orchestrator import ExperimentOrchestrator, create_orchestrator
from .proposals_api import (
    approve_and_run_proposal,
    approve_proposal,
    reject_proposal,
    run_proposal,
)
from .train_api import train_model
from .viewer_api import compare_runs, preview_dataset
from .worker_api import generate_proposal

__all__ = [
    "DatasetNotFoundError",
    "UploadError",
    "add_experiment_feedback",
    "clean_dataset",
    "compare_runs",
    "create_orchestrator",
    "EdaError",
    "Experiment",
    "ExperimentState",
    "ExperimentStore",
    "ExperimentOrchestrator",
    "approve_and_run_proposal",
    "approve_proposal",
    "generate_proposal",
    "get_experiment_results",
    "get_experiment_status",
    "get_fixtures_root",
    "get_uploads_root",
    "list_datasets",
    "list_experiments",
    "preview_dataset",
    "resolve_dataset_path",
    "reject_proposal",
    "run_eda",
    "run_proposal",
    "save_upload",
    "start_experiment",
    "train_model",
]
