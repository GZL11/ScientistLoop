"""
Runner 层基础抽象

AgentSession  — 统一的消息发送接口，隐藏协议差异
AgentRunner   — 启动 agent session 的工厂
RunnerConfig  — runner 可配置项（与 case 位置无关）
AgentEvent    — 统一的结构化事件
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── 结构化事件 ──

@dataclass
class AgentEvent:
    """Runner 产出的统一事件，各 backend 统一格式。"""
    type: str           # "text" | "tool_call" | "tool_result" | "info"
    content: str = ""   # 主要文本内容
    tool: str = ""      # 工具名（仅 tool_call / tool_result）
    tool_input: str = ""  # 工具输入摘要（仅 tool_call）
    is_error: bool = False  # 仅 tool_result

EventCallback = Callable[[AgentEvent], Any] | None


def default_event_printer(event: AgentEvent) -> None:
    """默认的事件处理：打印到 stdout（CLI 场景）。"""
    if event.type == "text":
        print(event.content)
    elif event.type == "text_chunk":
        print(event.content, end="", flush=True)
    elif event.type == "tool_call":
        print(f"  [tool] {event.tool}: {event.tool_input}")
    elif event.type == "tool_result" and event.is_error:
        print(f"  [error] {event.tool}: {event.content[:300]}")
    elif event.type == "info":
        print(f"  {event.content}")


@dataclass
class RunnerConfig:
    runner_type: str                         # "cc_native" | "cc_famou" | "cc_single" | "opencode_native" | "opencode_famou" | "opencode_single"
    agent_config_dir: Path | None = None     # agents/.opencode/ 或 agents/.claude/
    prompt_variant: str = "default"          # prompt_variants/ 下的子目录名
    prompt_variants_dir: Path | None = None  # None 时用 runners/prompt_variants/
    model: str | None = None                 # 覆盖默认模型（None 表示使用 runner 默认值）
    max_turns: int = 100
    skill_set: str = "default"               # skill_sets/ 下的子目录名
    sandbox: Any = None                      # SandboxConfig | None，避免循环 import
    idle_timeout_s: int = 7200               # opencode 子进程多久无 stdout 事件就 killpg（默认 120min，evolve 长跑安全）


class AgentSession(ABC):
    """统一的 agent 交互接口。"""

    session_id: str | None
    on_event: EventCallback = None

    @abstractmethod
    async def send(self, message: str, *, stop_on_tools: set[str] | None = None) -> str:
        """发送一条消息，阻塞到本轮结束，返回完整回复文本。

        stop_on_tools: 若非 None，在检测到这些工具被调用时立即终止本轮，
                       返回已收集的文本。用于 B2 在执行开始前提前退出。
        """

    @abstractmethod
    async def close(self) -> None:
        """关闭 session，释放资源。"""

    def _emit(self, event: AgentEvent) -> None:
        """发送事件给回调，若无回调则使用默认 printer。"""
        handler = self.on_event or default_event_printer
        handler(event)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()


class AgentRunner(ABC):
    """启动 agent session 的工厂。"""

    def __init__(self, config: RunnerConfig):
        self.config = config

    @abstractmethod
    async def start(self, workspace: Path) -> AgentSession:
        """
        在 workspace 准备 agent 运行环境（复制配置等），返回可交互的 session。
        workspace 内的业务数据由调用方（benchmark 层）在调用前准备好。
        """
