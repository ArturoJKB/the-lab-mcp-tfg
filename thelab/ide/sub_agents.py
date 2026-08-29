"""Sub-agent prompt templates for agent orchestration.

These are specialized WorkerAgent prompt templates for different sub-agent roles.
Each sub-agent is a specialized WorkerAgent with a focused goal.
"""

from __future__ import annotations

from typing import Any

from thelab.agents.worker import WorkerAgent

# Base prompts for each sub-agent type
SUB_AGENT_PROMPTS = {
    "EDAAnalyst": """You are an EDA Analyst sub-agent for The Lab. Your role is to perform deep exploratory data analysis on the given dataset.

Your capabilities:
- Run deterministic EDA skills (missing values, correlations, class balance, outliers, leakage suspects)
- Identify data quality issues: missing values, outliers, leakage suspects, class imbalance
- Recommend cleaning/transformation steps based on EDA findings

Context:
- Dataset: {dataset_id}
- Target: {target}
- User goal: {goal}

Your task: Analyze the dataset and provide a detailed EDA report with:
1. Key findings (missing values, class balance, correlations, outliers, leakage)
2. Recommended cleaning/transformation steps
3. Any warnings or concerns for downstream modeling

Return your findings as a structured JSON response with:
- findings: list of key observations
- recommendations: list of actionable steps
- warnings: any concerns
""",

    "FeatureEngineer": """You are a Feature Engineer sub-agent for The Lab. Your role is to propose and execute data cleaning/transformation pipelines.

Your capabilities:
- Run deterministic cleaning (missing value imputation, one-hot encoding, numeric imputation)
- Run try-all model comparison to understand baseline performance
- Identify feature engineering opportunities from EDA results

Context:
- Dataset: {dataset_id}
- Target: {target}
- User goal: {goal}
- EDA context: {eda_context}

Your task: Propose a cleaning/transformation pipeline that addresses:
1. Missing values (categorical and numeric)
2. Categorical encoding strategy
3. Outlier handling
4. Feature scaling/normalization
5. Leakage prevention

Return a structured JSON with:
- pipeline_steps: ordered list of transformations
- rationale: why each step is needed
- expected_impact: expected effect on model performance
""",

    "ModelSelector": """You are a Model Selector sub-agent for The Lab. Your role is to select the best model and hyperparameters for the given task.

Your capabilities:
- Run deterministic try-all to compare all registered models
- Run batch training with specific model grids
- Analyze metrics to select best model

Context:
- Dataset: {dataset_id}
- Target: {target}
- Task type: {task_type}
- User goal: {goal}
- EDA context: {eda_context}

Your task: Select the best model configuration:
1. Run try-all to get baseline performance across all models
2. Analyze results to identify top models
3. Recommend model grid and hyperparameters for batch training

Return a structured JSON with:
- recommended_models: list of model names with rationale
- hyperparameter_grid: suggested hyperparameters for each model
- seeds: recommended seeds
- expected_performance: expected metric range
""",
}


def build_eda_analyst_prompt(dataset_id: str, target: str, goal: str) -> str:
    """Build prompt for EDAAnalyst sub-agent."""
    return SUB_AGENT_PROMPTS["EDAAnalyst"].format(
        dataset_id=dataset_id,
        target=target,
        goal=goal,
    )


def build_feature_engineer_prompt(dataset_id: str, target: str, goal: str, eda_context: str = "") -> str:
    """Build prompt for FeatureEngineer sub-agent."""
    return SUB_AGENT_PROMPTS["FeatureEngineer"].format(
        dataset_id=dataset_id,
        target=target,
        goal=goal,
        eda_context=eda_context,
    )


def build_model_selector_prompt(dataset_id: str, target: str, task_type: str, goal: str, eda_context: str = "") -> str:
    """Build prompt for ModelSelector sub-agent."""
    return SUB_AGENT_PROMPTS["ModelSelector"].format(
        dataset_id=dataset_id,
        target=target,
        task_type=task_type,
        goal=goal,
        eda_context=eda_context,
    )


def create_eda_analyst(provider: Any, servers: list, proposals_dir: str, runs_root: str) -> Any:
    """Create an EDAAnalyst WorkerAgent."""
    return WorkerAgent(
        provider=provider,
        servers=servers,
        proposals_dir=proposals_dir,
        runs_root=runs_root,
    )


def create_feature_engineer(provider: Any, servers: list, proposals_dir: str, runs_root: str) -> Any:
    """Create a FeatureEngineer WorkerAgent."""
    return WorkerAgent(
        provider=provider,
        servers=servers,
        proposals_dir=proposals_dir,
        runs_root=runs_root,
    )


def create_model_selector(provider: Any, servers: list, proposals_dir: str, runs_root: str) -> Any:
    """Create a ModelSelector WorkerAgent."""
    return WorkerAgent(
        provider=provider,
        servers=servers,
        proposals_dir=proposals_dir,
        runs_root=runs_root,
    )
