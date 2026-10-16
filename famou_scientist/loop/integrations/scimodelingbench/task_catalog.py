"""Public SciModelingBench task metadata used by the adapter boundary."""
from __future__ import annotations

from dataclasses import dataclass


DEFAULT_HF_REVISION = "d8b9ea3c78ed33edf0869a427940a0651eb49f52"


@dataclass(frozen=True)
class SciModelingBenchTaskSpec:
    """Public contract metadata for one scored SciModelingBench task."""

    task_id: str
    config: str
    domain: str
    task_form: str
    submission_size: int
    primary_metric: str
    direction: str = "higher_is_better"
    exact_submission_size: bool = True
    endpoint: str | None = None
    summary_size: int = 5


TASK_SPECS: dict[str, SciModelingBenchTaskSpec] = {
    "tfbind8": SciModelingBenchTaskSpec(
        task_id="tfbind8",
        config="tfbind8",
        domain="DNA binding / transcription-factor sequence design",
        task_form="black-box optimization",
        submission_size=32,
        primary_metric="best_k_mean",
    ),
    "tfbind10_pho4": SciModelingBenchTaskSpec(
        task_id="tfbind10_pho4",
        config="tfbind10_pho4",
        domain="DNA binding / Pho4 transcription-factor sequence design",
        task_form="black-box optimization",
        submission_size=128,
        primary_metric="normalized_enrichment",
        summary_size=16,
    ),
    "cell_dag_nas": SciModelingBenchTaskSpec(
        task_id="cell_dag_nas",
        config="cell_dag_nas",
        domain="neural architecture search / NASBench-101",
        task_form="black-box optimization",
        submission_size=32,
        primary_metric="best_k_mean",
    ),
    "superconductor": SciModelingBenchTaskSpec(
        task_id="superconductor",
        config="superconductor",
        domain="materials science / superconducting critical temperature",
        task_form="candidate-pool ranking",
        submission_size=32,
        primary_metric="global_ndcg",
        exact_submission_size=False,
    ),
    "hopper_controller": SciModelingBenchTaskSpec(
        task_id="hopper_controller",
        config="hopper_controller",
        domain="reinforcement learning control / Hopper-v5 policy ranking",
        task_form="candidate-pool ranking",
        submission_size=32,
        primary_metric="global_ndcg",
        exact_submission_size=False,
    ),
    "utr_mrl_egfp_unmodified": SciModelingBenchTaskSpec(
        task_id="utr_mrl_egfp_unmodified",
        config="utr_mrl_egfp_unmodified",
        domain="synthetic biology / 5-prime UTR translation design",
        task_form="candidate-pool ranking",
        submission_size=128,
        primary_metric="normalized_enrichment",
        exact_submission_size=False,
        summary_size=16,
    ),
    "gfp": SciModelingBenchTaskSpec(
        task_id="gfp",
        config="gfp",
        domain="protein engineering / GFP brightness",
        task_form="candidate-pool ranking",
        submission_size=128,
        primary_metric="normalized_enrichment",
        exact_submission_size=False,
        summary_size=16,
    ),
}

for _endpoint in ("mchc", "mch", "creatinine", "sodium", "chloride", "phosphorus"):
    TASK_SPECS[f"drugmatrix_{_endpoint}"] = SciModelingBenchTaskSpec(
        task_id=f"drugmatrix_{_endpoint}",
        config="drugmatrix_clinical_pathology",
        domain=f"toxicology / DrugMatrix clinical pathology / {_endpoint}",
        task_form="candidate-pool ranking",
        submission_size=16,
        primary_metric="global_ndcg",
        exact_submission_size=False,
        endpoint=_endpoint,
    )


ALIASES: dict[str, str] = {
    "tfbind10-pho4": "tfbind10_pho4",
    "cell-dag-nas": "cell_dag_nas",
    "hopper-controller": "hopper_controller",
    "utr-mrl": "utr_mrl_egfp_unmodified",
    "utr_mrl": "utr_mrl_egfp_unmodified",
    "drugmatrix:mchc": "drugmatrix_mchc",
    "drugmatrix:mch": "drugmatrix_mch",
    "drugmatrix:creatinine": "drugmatrix_creatinine",
    "drugmatrix:sodium": "drugmatrix_sodium",
    "drugmatrix:chloride": "drugmatrix_chloride",
    "drugmatrix:phosphorus": "drugmatrix_phosphorus",
}


def normalize_task_id(task_id: str) -> str:
    """Return the canonical safe task id used inside Famou run directories."""

    value = str(task_id).strip().lower().replace("-", "_")
    return ALIASES.get(str(task_id).strip().lower(), ALIASES.get(value, value))


def task_spec(task_id: str) -> SciModelingBenchTaskSpec:
    """Look up public metadata for a SciModelingBench task."""

    normalized = normalize_task_id(task_id)
    try:
        return TASK_SPECS[normalized]
    except KeyError as exc:
        raise KeyError(f"unsupported SciModelingBench task: {task_id}") from exc


__all__ = [
    "ALIASES",
    "DEFAULT_HF_REVISION",
    "TASK_SPECS",
    "SciModelingBenchTaskSpec",
    "normalize_task_id",
    "task_spec",
]
