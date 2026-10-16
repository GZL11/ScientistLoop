"""Agent、Bench 与 Evaluation 三类运行设施的公共边界。"""

from .agent import AgentFacility, WorkerAgentFacility
from .benchmark import BenchmarkFacility, RunnerBenchmarkFacility
from .contracts import (
    ArtifactRef,
    CandidateRef,
    EvaluationRequest,
    EvaluationResult,
    RunResult,
    TaskView,
)
from .evaluation import AdapterEvaluationFacility, EvaluationFacility
from .verifier import ValidityVerifier, validate_validity_verdict

__all__ = [
    "AdapterEvaluationFacility",
    "AgentFacility",
    "ArtifactRef",
    "BenchmarkFacility",
    "CandidateRef",
    "EvaluationFacility",
    "EvaluationRequest",
    "EvaluationResult",
    "RunResult",
    "RunnerBenchmarkFacility",
    "TaskView",
    "WorkerAgentFacility",
    "ValidityVerifier",
    "validate_validity_verdict",
]
