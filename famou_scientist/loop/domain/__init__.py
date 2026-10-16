"""端到端运行时的领域对象与校验逻辑。"""

from .goal import GoalError, goal_query, load_goal, validate_goal_patch
from .graph import (
    AgentGraph,
    GraphContext,
    GraphOutput,
    GraphState,
    NodeInvocation,
    NodeResult,
)
from .schemas import GOAL_STATUSES, QUEUE_STATUSES
from .resources import (
    GPUDevice,
    GPUResourceRequest,
    ResourceBroker,
    ResourceEnvelope,
    ResourceLease,
    ResourceRequest,
)
from .status import LoopStatus

__all__ = [
    "GOAL_STATUSES",
    "AgentGraph",
    "GraphContext",
    "GraphOutput",
    "GraphState",
    "GPUDevice",
    "GPUResourceRequest",
    "QUEUE_STATUSES",
    "LoopStatus",
    "NodeInvocation",
    "NodeResult",
    "ResourceBroker",
    "ResourceEnvelope",
    "ResourceLease",
    "ResourceRequest",
    "GoalError",
    "goal_query",
    "load_goal",
    "validate_goal_patch",
]
