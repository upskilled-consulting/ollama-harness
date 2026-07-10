"""harness.eval — regression testing and experiment framework."""

from harness.eval.eval_suite import SUITE, check_task, run_task, score_suite
from harness.eval.experiment_panel import (
    ExperimentSpec,
    experiment_panel_decision,
    experiment_panel_issues,
    run_experiment_panel,
)
from harness.eval.experiment_runner import generate_crd_order, run_experiment

__all__ = [
    "SUITE",
    "check_task",
    "run_task",
    "score_suite",
    "ExperimentSpec",
    "run_experiment_panel",
    "experiment_panel_decision",
    "experiment_panel_issues",
    "run_experiment",
    "generate_crd_order",
]
